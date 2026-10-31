#!/usr/bin/env python3
"""How good okl's drift is at its job (REPORT §4ae): replay this repo's own history and re-run
each watched lesson's check where drift was red, and on a sample of commits where it was green.

    PYTHONPATH=$PWD/src python3 evals/drift_replay.py --dry-run   # counts only; runs no check
    PYTHONPATH=$PWD/src python3 evals/drift_replay.py             # writes evals/results/drift-replay-<stamp>.json
    python3 evals/drift_replay.py --judge evals/results/drift-replay-<stamp>.json

The history is the committed snapshot's (okl-drift.json): every commit reachable from --until.
At a commit, drift is red for a lesson when the lesson's governed files differ from the commit
its stamp in that commit's own snapshot was verified at, which is what CI's gate read there. An
event is a snapshot commit that replaced a lesson's stamp: the stamp in its first parent's
snapshot (the check last passed at P) gave way to one verified at V.

Each check runs as `okl verify` runs it (a shell; a pass is exit 0 with the expected text in the
output), in one scratch worktree checked out at the commit under test, with that commit's src
first on PYTHONPATH and no OKL_ or git-location variable set, so no check reaches a real store or
another repository. A verdict counts only when the same check also passes, here and now, at the
commits history says it passed at; one that does not is not reproducible and is counted apart.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    from okl.store import Store

T = TypeVar("T")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
RESULTS = REPO / "evals" / "results"
# The pins the section fixes before any check runs (REPORT §4ae).
UNTIL = "485f0ed"
SEED = 264
SAMPLE = 300
JUDGED = 40
TIMEOUT = 300
# The check as a stamp records it; older stamps end "@ <date>" instead of "on commit <sha>".
CHECK = re.compile(r"`(.*)` exit (\d+), matched '(.*?)' (?:on commit|@)", re.S)
# Checks whose answer comes from outside the commit under test, so a replay would ask today.
OUTSIDE = (("gh ", "reads live GitHub settings"),
           ("evals/preflight.py", "runs the preflight, which reads the lesson store"))


def git(*a: str, repo: Path = REPO) -> str:
    """git's stdout for `a`, run in `repo`."""
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True).stdout


def git_ok(*a: str, repo: Path = REPO) -> bool:
    """Whether git `a`, run in `repo`, exits 0."""
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True).returncode == 0


def snapshot(rev: str, repo: Path = REPO) -> dict[str, dict]:
    """The committed snapshot's lessons at `rev`, by id; {} where it has none."""
    try:
        return {r["id"]: r for r in json.loads(git("show", f"{rev}:okl-drift.json", repo=repo)).get("rules", [])}
    except ValueError:
        return {}


def parse_check(verified_by: str | None) -> tuple[str, str] | None:
    """The command and expected text a stamp records, or None when it records neither."""
    m = CHECK.match(verified_by or "")
    return (m.group(1), m.group(3)) if m else None


def outside_commit(cmd: str) -> str:
    """Why a check's answer does not come from the commit under test, or ""."""
    return next((why for token, why in OUTSIDE if token in cmd), "")


def governs(rule: dict) -> list[str]:
    """The path globs a snapshot rule governs."""
    return [g.strip() for g in rule.get("files", "").split(",") if g.strip()]


def differs(a: str, b: str, files: list[str], repo: Path = REPO) -> bool:
    """Whether `files` differ between commits `a` and `b`: drift's test (src/okl/drift.py)."""
    return subprocess.run(["git", "-C", str(repo), "diff", "--quiet", a, b, "--", *files],
                          capture_output=True).returncode == 1


def changed_commits(span: str, files: list[str], repo: Path = REPO) -> list[str]:
    """The commits in `span`, oldest first, whose `files` differ from their first parent's. Not
    `git rev-list <span> -- <files>`: its history simplification leaves out a merge whose files
    match one parent, though the merged tree can fail a check that reads other files. The first
    §4ae run used it, and its census missed 563 such merges."""
    out = []
    for x in git("rev-list", "--reverse", span, repo=repo).split():
        parent = git("rev-parse", "--verify", "-q", f"{x}^1", repo=repo).strip()
        if parent and differs(parent, x, files, repo):
            out.append(x)
    return out


@dataclass
class Event:
    """One replaced stamp: the check last passed at `p`, was re-verified at `v`, and the
    snapshot commit `c` recorded it. `touched` are the commits in p..v, oldest first, that
    changed the lesson's governed files: the changes drift reacted to."""
    lesson: str
    p: str
    v: str
    c: str
    kind: str
    cmd: str = ""
    expect: str = ""
    touched: list[str] = field(default_factory=list)
    outcome: str = ""
    first_fail: str = ""


def events(watched: dict[str, dict], until: str, repo: Path = REPO) -> list[Event]:
    """Every replaced stamp of a watched lesson in the snapshot history reachable from `until`,
    classified; only kind "drift-red" is replayed."""
    out = []
    for c in changed_commits(until, ["okl-drift.json"], repo):
        parent = git("rev-parse", "--verify", "-q", f"{c}^1", repo=repo).strip()
        now, before = snapshot(c, repo), snapshot(parent, repo)
        for lid, rule in watched.items():
            if lid not in now:
                continue
            v, p = now[lid].get("verified_commit"), (before.get(lid) or {}).get("verified_commit")
            if lid in before and v == p:
                continue
            e = Event(lid, p or "", v or "", c, "")
            files = governs(rule)
            check = parse_check((before.get(lid) or {}).get("verified_by"))
            if lid not in before:
                e.kind = "first stamp"
            elif not v or not p:
                e.kind = "no commit recorded"
            elif not git_ok("merge-base", "--is-ancestor", p, v, repo=repo):
                e.kind = "previous stamp not an ancestor"
            elif not differs(p, v, files, repo):
                e.kind = "re-verified, governed content unchanged"
            elif differs(v, c, files, repo):
                e.kind = "verified before its code commit"
            elif check is None:
                e.kind = "check not recorded"
            elif outside_commit(check[0]):
                e.kind = outside_commit(check[0])
            else:
                e.kind = "drift-red"
                e.cmd, e.expect = check
                e.touched = changed_commits(f"{p}..{v}", files, repo)
            out.append(e)
    return out


@dataclass
class Pair:
    """A lesson at a commit: drift red or green there, by the commit's own snapshot."""
    lesson: str
    x: str
    stamp: str
    red: bool
    cmd: str
    expect: str
    outcome: str = ""


def unusable(stamp: dict) -> str:
    """Why a stamp's check cannot be replayed, or ""."""
    check = parse_check(stamp.get("verified_by"))
    if not stamp.get("verified_commit"):
        return "no commit recorded"
    if check is None:
        return "check not recorded"
    return outside_commit(check[0])


def left_out(stamp: dict | None, x: str, repo: Path = REPO) -> str:
    """Why a lesson at commit `x` is not a pair to replay, given the stamp in x's snapshot; ""
    when it is one."""
    if stamp is None:
        return "not in this commit's snapshot"
    if unusable(stamp):
        return unusable(stamp)
    if stamp["verified_commit"] == x:
        return "the verified commit itself"
    if not git_ok("merge-base", "--is-ancestor", stamp["verified_commit"], x, repo=repo):
        return "stamp not an ancestor"
    return ""


def pairs(watched: dict[str, dict], until: str, repo: Path = REPO) -> tuple[list[Pair], dict[str, int]]:
    """Every (watched lesson, commit) whose snapshot holds a usable stamp from this history,
    red or green; and the counts of those left out, by reason. Commits before the snapshot
    existed are not counted."""
    out: list[Pair] = []
    left: dict[str, int] = {}
    for x in git("rev-list", until, repo=repo).split():
        snap = snapshot(x, repo)
        if not snap:
            continue
        for lid, rule in watched.items():
            stamp = snap.get(lid)
            why = left_out(stamp, x, repo)
            check = parse_check((stamp or {}).get("verified_by"))
            if why or stamp is None or check is None:
                left[why] = left.get(why, 0) + 1
                continue
            out.append(Pair(lid, x, stamp["verified_commit"],
                            differs(stamp["verified_commit"], x, governs(rule), repo), *check))
    return out, left


def git_location_vars() -> set[str]:
    """The variables that point git at a repository; a check must not inherit them."""
    return set(subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True,
                              text=True).stdout.split())


class Replayer:
    """Runs a check at a commit in one scratch worktree; each verdict is cached."""

    def __init__(self, scratch: Path, repo: Path = REPO) -> None:
        self.repo, self.wt = repo, scratch / "replay"
        git("worktree", "add", "-q", "--detach", str(self.wt), "HEAD", repo=repo)
        drop = git_location_vars()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("OKL_") and k not in drop}
        self.env["PYTHONPATH"] = str(self.wt / "src")
        self.env["OKL_WARM_SOCKET"] = str(scratch / "no-warm.sock")
        self.cache: dict[tuple[str, str, str], str] = {}
        self.runs = 0

    def verdict(self, commit: str, cmd: str, expect: str) -> str:
        """"pass", "fail" or "timed out", by `okl verify`'s rule."""
        key = (commit, cmd, expect)
        if key not in self.cache:
            git("checkout", "-q", "-f", "--detach", commit, repo=self.wt)
            git("clean", "-fdxq", repo=self.wt)
            self.runs += 1
            try:
                r = subprocess.run(cmd, shell=True, cwd=self.wt, env=self.env, capture_output=True,
                                   text=True, timeout=TIMEOUT)
                out = (r.stdout or "") + (r.stderr or "")
                self.cache[key] = "pass" if r.returncode == 0 and expect in out else "fail"
            except subprocess.TimeoutExpired:
                self.cache[key] = "timed out"
        return self.cache[key]

    def close(self) -> None:
        """Remove the scratch worktree."""
        git("worktree", "remove", "--force", str(self.wt), repo=self.repo)


def replay_event(r: Replayer, e: Event) -> None:
    """needed: the check failed at a commit that changed the governed files; unneeded: it
    passed at every one; not reproducible: it does not pass here at P or V, where it passed."""
    if any(r.verdict(c, e.cmd, e.expect) != "pass" for c in (e.p, e.v)):
        e.outcome = "not reproducible"
        return
    for x in e.touched:
        got = r.verdict(x, e.cmd, e.expect)
        if got != "pass":
            e.outcome, e.first_fail = ("needed" if got == "fail" else "timed out"), x
            return
    e.outcome = "unneeded"


def replay_pair(r: Replayer, q: Pair) -> None:
    """broken or intact at the commit; not reproducible when the check fails at its stamp."""
    if r.verdict(q.stamp, q.cmd, q.expect) != "pass":
        q.outcome = "not reproducible"
        return
    got = r.verdict(q.x, q.cmd, q.expect)
    q.outcome = {"pass": "intact", "fail": "broken"}.get(got, "timed out")


def draw(items: list[T], n: int, key: Callable[[T], str]) -> list[T]:
    """The first `n` of `items` in the order of a seeded hash of each one's key: a sample anyone
    can redraw from the receipt, as evals/bench/assemble_queries.py splits its lessons."""
    return sorted(items, key=lambda i: hashlib.sha256(f"{SEED}:{key(i)}".encode()).hexdigest())[:n]


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    """The 95% Wilson interval for k of n."""
    if n == 0:
        return [0.0, 1.0]
    p, d = k / n, 1 + z * z / n
    c, h = p + z * z / (2 * n), z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return [round((c - h) / d, 4), round((c + h) / d, 4)]


def main_store() -> Path:
    """The main checkout's store. A worktree has none of its own, and the first §4ae run read
    its check log from the worktree's path, so it recorded none."""
    common = git("rev-parse", "--git-common-dir").strip()
    return (REPO / common).resolve().parent / ".okl" / "okl.db"


@contextlib.contextmanager
def store_copy(db: Path) -> Iterator[Store]:
    """The lesson store at `db`, opened from a copy, so nothing this run does can touch it."""
    from okl.store import Store
    with tempfile.TemporaryDirectory() as d:
        copy = Path(d) / "okl.db"
        shutil.copy2(db, copy)
        yield Store(f"sqlite:///{copy}")


def check_log(watched: dict[str, dict], db: Path) -> dict[str, dict[str, int]]:
    """Each lesson's logged check runs on this machine (okl review R3), passed and failed. A
    failure is a catch that may never have reached a commit."""
    if not db.exists():
        return {}
    with store_copy(db) as s:
        return {lid: {"passed": sum(r.passed for r in s.checks(lid)),
                      "failed": sum(not r.passed for r in s.checks(lid))} for lid in watched}


def summary(evs: list[Event], red: list[Pair], green: list[Pair], n_red: int, n_green: int) -> dict:
    """The rates the section registers, each with its count and Wilson interval."""
    needed = sum(e.outcome == "needed" for e in evs)
    decided = sum(e.outcome in ("needed", "unneeded") for e in evs)
    # A PR's merge replaces main's stamp with the one its branch already recorded, so one
    # verification can be two events. Counted once per (lesson, V), needed if any event was:
    # declared before the corrected run, as §4ae's threat on the unit asks.
    per_v: dict[tuple[str, str], bool] = {}
    for e in evs:
        if e.outcome in ("needed", "unneeded"):
            per_v[(e.lesson, e.v)] = per_v.get((e.lesson, e.v), False) or e.outcome == "needed"
    v_needed = sum(per_v.values())
    br = [q for q in red if q.outcome in ("broken", "intact")]
    bg = [q for q in green if q.outcome in ("broken", "intact")]
    kr, kg = sum(q.outcome == "broken" for q in br), sum(q.outcome == "broken" for q in bg)
    b_red, b_green = (kr / len(br) if br else 0.0), (kg / len(bg) if bg else 0.0)
    broken_red, broken_green = n_red * b_red, n_green * b_green
    return {
        "event_precision": {"needed": needed, "decided": decided,
                            "rate": round(needed / decided, 4) if decided else None,
                            "wilson95": wilson(needed, decided)},
        "verification_precision": {"needed": v_needed, "decided": len(per_v),
                                   "rate": round(v_needed / len(per_v), 4) if per_v else None,
                                   "wilson95": wilson(v_needed, len(per_v))},
        "red_break_rate": {"broken": kr, "decided": len(br), "rate": round(b_red, 4), "wilson95": wilson(kr, len(br))},
        "green_miss_rate": {"broken": kg, "decided": len(bg), "rate": round(b_green, 4), "wilson95": wilson(kg, len(bg))},
        "recall_estimate": (round(broken_red / (broken_red + broken_green), 4)
                            if broken_red + broken_green else None),
        "not_reproducible": {"events": sum(e.outcome == "not reproducible" for e in evs),
                             "pairs": sum(q.outcome == "not reproducible" for q in red + green)},
    }


def main() -> int:
    """Count, and unless --dry-run replay, the events and samples; or judge a receipt."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--until", default=UNTIL)
    ap.add_argument("--store", type=Path, default=main_store(),
                    help="the store whose check log and lesson text are read, from a copy")
    ap.add_argument("--dry-run", action="store_true", help="count events and pairs; run no check")
    ap.add_argument("--judge", metavar="RECEIPT", help="judge a sample of a receipt's events (§4ae step 3)")
    args = ap.parse_args()
    if args.judge:
        return judge(Path(args.judge), args.store)
    until = git("rev-parse", "--verify", "-q", args.until).strip()
    if not until:
        sys.exit(f"ABORT: {args.until} is not a commit here")
    watched = snapshot(until)
    evs = events(watched, until)
    kinds: dict[str, int] = {}
    for e in evs:
        kinds[e.kind] = kinds.get(e.kind, 0) + 1
    replayed = [e for e in evs if e.kind == "drift-red"]
    lessons = sorted({e.lesson for e in replayed})
    all_pairs, left = pairs(watched, until)
    red_pool = [q for q in all_pairs if q.red]
    green_pool = [q for q in all_pairs if not q.red]
    red = draw(red_pool, SAMPLE, lambda q: f"{q.lesson}:{q.x}")
    green = draw(green_pool, SAMPLE, lambda q: f"{q.lesson}:{q.x}")
    print(f"until {until[:7]}: {len(watched)} watched lessons, {len(lessons)} with replayable events")
    print("replaced stamps by kind: " + ", ".join(f"{k} {n}" for k, n in sorted(kinds.items())))
    print(f"drift-red events {len(replayed)}, governed-file commits in them {sum(len(e.touched) for e in replayed)}")
    print(f"(lesson, commit) pairs: red {len(red_pool)}, green {len(green_pool)}; left out: "
          + ", ".join(f"{k} {n}" for k, n in sorted(left.items())))
    print(f"sampled: red {len(red)}, green {len(green)} (seed {SEED})")
    if args.dry_run:
        return 0
    started = time.time()
    with tempfile.TemporaryDirectory(prefix="okl-drift-replay-") as d:
        r = Replayer(Path(d))
        try:
            for i, e in enumerate(replayed, 1):
                replay_event(r, e)
                if i % 50 == 0:
                    print(f"  events {i}/{len(replayed)}, {r.runs} check runs", file=sys.stderr)
            for q in red + green:
                replay_pair(r, q)
        finally:
            r.close()
    result = {
        "section": "§4ae", "until": until, "harness_commit": git("rev-parse", "HEAD").strip(),
        "seed": SEED, "sample": SAMPLE, "timeout_s": TIMEOUT, "check_runs": r.runs,
        "minutes": round((time.time() - started) / 60, 1),
        "watched": sorted(watched), "replayed_lessons": lessons, "kinds": kinds,
        "pairs": {"red": len(red_pool), "green": len(green_pool), "left_out": left},
        "summary": summary(replayed, red, green, len(red_pool), len(green_pool)),
        "by_lesson": {lid: {o: sum(e.lesson == lid and e.outcome == o for e in replayed)
                            for o in ("needed", "unneeded", "not reproducible", "timed out")}
                      for lid in lessons},
        "check_log": check_log(watched, args.store),
        "events": [asdict(e) for e in evs],
        "red_sample": [asdict(q) for q in red], "green_sample": [asdict(q) for q in green],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    path = RESULTS / f"drift-replay-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.json"
    path.write_text(json.dumps(result, indent=1) + "\n")
    print(json.dumps(result["summary"], indent=1))
    print(f"receipt: {path.relative_to(REPO)}")
    return 0


JUDGE_PROMPT = """You are judging whether code changes broke a rule a project keeps.

The rule:
  title: {title}
  when it applies: {symptom}
  what to do: {fix}

The changes, commit by commit, to the files the rule governs:
{diff}

Did any of these changes, at any point, make the project break this rule, or make the rule's
advice wrong for the project? Answer with JSON only: {{"broken": true or false, "why": "<one sentence>"}}"""


def judge(receipt: Path, db: Path) -> int:
    """§4ae step 3: a second judge, not the check, on a seeded sample of the replayed events,
    half needed and half unneeded where there are enough, blind to the check's verdict."""
    receipt = receipt.resolve()
    data = json.loads(receipt.read_text())
    evs = [e for e in data["events"] if e["outcome"] in ("needed", "unneeded")]
    def key(e: dict) -> str:
        return f"{e['lesson']}:{e['p']}:{e['v']}"
    need = draw([e for e in evs if e["outcome"] == "needed"], JUDGED // 2, key)
    unneed = draw([e for e in evs if e["outcome"] == "unneeded"], JUDGED - len(need), key)
    chosen = draw(need + unneed, JUDGED, key)
    rules = snapshot(data["until"])
    with store_copy(db) as s:
        nodes = {e["lesson"]: s.get_node(e["lesson"]) for e in chosen}
    out = []
    for e in chosen:
        node = nodes[e["lesson"]]
        diff = git("log", "-p", "--reverse", "--format=commit %h %s", f"{e['p']}..{e['v']}", "--",
                   *governs(rules[e["lesson"]]))[:12000]
        prompt = JUDGE_PROMPT.format(title=node.title if node else e["lesson"],
                                     symptom=(node and node.symptom) or "-", fix=(node and node.fix) or "-",
                                     diff=diff)
        # From an empty directory: run in the checkout it would read this repo's CLAUDE.md, which
        # --restricted does not skip, and the judge must see only the lesson and the diffs.
        with tempfile.TemporaryDirectory(prefix="okl-judge-") as room:
            r = subprocess.run(["claude", "-p", "--model", "sonnet", "--restricted", "--tools", ""],
                               input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=room)
        m = re.search(r"\{.*\}", r.stdout, re.S)
        try:
            said = json.loads(m.group(0)) if m else {}
        except ValueError:
            said = {}
        out.append({"lesson": e["lesson"], "p": e["p"], "v": e["v"], "check": e["outcome"],
                    "judge": said.get("broken"), "why": said.get("why", "")})
    agree = sum((o["judge"] is True) == (o["check"] == "needed") for o in out if o["judge"] is not None)
    answered = sum(o["judge"] is not None for o in out)
    path = receipt.with_name(receipt.stem + "-judge.json")
    path.write_text(json.dumps({"receipt": receipt.name, "judge": "claude -p --model sonnet --restricted",
                                "agree": agree, "answered": answered, "wilson95": wilson(agree, answered),
                                "judged": out}, indent=1) + "\n")
    print(f"judge agrees with the check on {agree} of {answered}; receipt: {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
