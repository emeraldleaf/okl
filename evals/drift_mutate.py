#!/usr/bin/env python3
"""What drift catches (REPORT §4af): each replayable watched lesson broken on purpose.

    PYTHONPATH=src python3 evals/drift_mutate.py [--workers 3]
        # writes evals/results/drift-mutate-<stamp>.json and drift-mutate-<stamp>-patches/

BASE is the commit that adds §4af. Its okl-drift.json names the watched lessons; the three whose
check answers from outside the commit are left out (drift_replay.OUTSIDE), and a lesson whose
check does not pass at BASE is reported and left out too.

Per lesson, a breaker model makes four changes meant to break it, blind to its check and its
governed files (okl-drift.json is removed from its worktree), each told the files the earlier
ones changed; then two harmless changes to its governed files, the negative control. A judge
model sees the lesson and each diff, never a verdict, and says broken, intact or unsure. Each
patch is committed on BASE in a scratch worktree, and there:
- red: the patch changes a governed file, so drift goes red;
- check: the lesson's check, run as okl verify runs it (drift_replay.Replayer);
- CI: the mechanical steps of ci.yml's lint-and-test job, breaking patches only. A step that
  already fails at BASE is reported and not counted.

Patches are kept as they arrive, so a run that stops resumes where it stopped.

    PYTHONPATH=src python3 evals/drift_mutate.py --rejudge evals/results/drift-mutate-<stamp>.json
        # writes drift-mutate-<stamp>-rejudge.json beside it

--rejudge asks the judge once more, with the same prompt and model, about each patch whose judge
call gave no verdict (in the first run, time-outs while other model sessions ran), and recomputes
the measures. The registered receipt is left as it is; this one is reported beside it.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import subprocess
import sys
import tempfile
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import drift_replay as dr

BASE = "eb93b16"
BREAKING, HARMLESS = 4, 2
TIMEOUT = 300
SEED = 264
BOOT = 2000
CI_STEPS = ("ruff check .", "mypy src/okl", "lint-imports", "python3 -m pytest -q -p no:cacheprovider",
            "./ci/check-diagram-figures.sh", "bash gates/run-gates.sh")
# --allowedTools takes the rest of the line, so it comes last and the prompt goes on stdin.
BREAKER = ["claude", "-p", "--model", "sonnet", "--restricted", "--strict-mcp-config", "--output-format", "json",
           "--permission-mode", "acceptEdits", "--tools", "Read,Grep,Glob,Edit",
           "--allowedTools", "Read", "Grep", "Glob", "Edit"]
JUDGE = ["claude", "-p", "--model", "opus", "--restricted", "--strict-mcp-config", "--output-format", "json",
         "--tools", ""]
LESSON = "Title: {title}\nSymptom: {symptom}\nFix: {fix}"
BREAK_PROMPT = """You are working in a software repository, your working directory. The project keeps this
lesson about itself:

{lesson}

Make one realistic change to this repository, of the kind a contributor might make in the course
of other work, after which the lesson is no longer true of the repository. Edit files with your
tools, and change only what the break needs. Do not mention the lesson, and add no comment
explaining the change.{avoid}

When you are done, answer with one sentence saying what you changed."""
HARMLESS_PROMPT = """You are working in a software repository, your working directory. The project keeps this
lesson about itself:

{lesson}

Make one realistic change to one of these files: {files}. Make it the kind of change a
contributor might make in the course of other work, after which the lesson still holds. Edit
with your tools, and do not mention the lesson.{avoid}

When you are done, answer with one sentence saying what you changed."""
JUDGE_PROMPT = """You are judging whether a change to a software repository broke a lesson the project keeps
about itself.

The lesson:
{lesson}

The change, as a unified diff:
{diff}

Before this change the lesson held. After it, is the lesson's claim false of the repository?
Answer with one JSON object and nothing else:
{{"verdict": "broken|intact|unsure", "reason": "one sentence"}}"""


def ci_run_lesson(cmd: str) -> bool:
    """Whether CI already runs the lesson's check: lint-imports, or a pytest selection."""
    return cmd.strip() == "lint-imports" or cmd.strip().startswith("python3 -m pytest")


def judged(result: str) -> str | None:
    """The judge's last valid verdict from its answer, or None when it gave none."""
    got = dr.last_object(result, lambda o: o.get("verdict") in ("broken", "intact", "unsure"))
    return got["verdict"] if got else None


def changed_files(diff: str) -> list[str]:
    """The files a unified diff changes."""
    return sorted(set(re.findall(r"^\+\+\+ b/(.+)$", diff, re.M)))


def summarize(patches: list[dict]) -> dict:
    """§4af's measures from the evaluated patches."""
    breaks = [p for p in patches if p["kind"] == "breaking" and p.get("judge") == "broken" and p.get("diff")]
    controls = [p for p in patches if p["kind"] == "harmless" and p.get("judge") == "intact" and p.get("diff")]

    def caught(p: dict) -> bool:
        return p["red"] and p["check"] == "fail"

    def rate(ps: list[dict]) -> dict:
        k, n = sum(caught(p) for p in ps), len(ps)
        return {"caught": k, "breaks": n, "rate": round(k / n, 4) if n else None, "wilson95": dr.wilson(k, n)}

    lessons = sorted({p["lesson"] for p in breaks})
    rng, boot = random.Random(SEED), []   # noqa: S311 - a seeded bootstrap, not a secret
    for _ in range(BOOT):
        pick = [rng.choice(lessons) for _ in lessons]
        ps = [p for lid in pick for p in breaks if p["lesson"] == lid]
        if ps:
            boot.append(sum(caught(p) for p in ps) / len(ps))
    boot.sort()

    def against_ci(ps: list[dict]) -> dict:
        c = Counter(("drift" if caught(p) else "") + ("+ci" if p.get("ci") == "fail" else "") for p in ps)
        return {"drift_only": c["drift"], "both": c["drift+ci"], "ci_only": c["+ci"], "neither": c[""], "breaks": len(ps)}

    return {
        "breaking_patches": sum(p["kind"] == "breaking" for p in patches),
        "breaks": len(breaks),
        "judge": dict(Counter(f'{p["kind"]}:{p.get("judge") or "invalid"}' for p in patches)),
        "catch": {**rate(breaks), "bootstrap95_by_lesson": [round(boot[int(len(boot) * .025)], 4),
                                                             round(boot[int(len(boot) * .975)], 4)] if boot else None},
        "coverage_misses": sum(not p["red"] for p in breaks),
        "sensitivity_misses": sum(p["red"] and p["check"] == "pass" for p in breaks),
        "check_timed_out": sum(p["check"] == "timed out" for p in breaks),
        "against_ci": {"ci_run_lessons": against_ci([p for p in breaks if p["ci_run"]]),
                       "other_lessons": against_ci([p for p in breaks if not p["ci_run"]])},
        "controls": {"n": len(controls), "check_failed": sum(p["check"] == "fail" for p in controls)},
        "unusable": sum(1 for p in patches if not p.get("diff") or p.get("error")),
        "per_lesson": {lid: {"breaks": sum(p["lesson"] == lid for p in breaks),
                             "caught": sum(p["lesson"] == lid and caught(p) for p in breaks),
                             "coverage_misses": sum(p["lesson"] == lid and not p["red"] for p in breaks),
                             "sensitivity_misses": sum(p["lesson"] == lid and p["red"] and p["check"] == "pass" for p in breaks),
                             "controls_failed": sum(p["lesson"] == lid and p["check"] == "fail" for p in controls)}
                       for lid in sorted({p["lesson"] for p in patches})},
    }


def claude(cmd: list[str], prompt: str, cwd: Path) -> dict:
    """One headless session: its result text and cost, or the error."""
    try:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=TIMEOUT, cwd=cwd)
    except subprocess.TimeoutExpired:
        return {"error": "timed out"}
    try:
        env = json.loads(p.stdout)
    except ValueError:
        return {"error": (p.stderr or p.stdout or "no output")[-300:]}
    return {"result": env.get("result") or "", "cost_usd": env.get("total_cost_usd") or 0.0,
            **({"error": (env.get("result") or "")[-300:]} if env.get("is_error") else {})}


def run_ci(r: dr.Replayer, commit: str, skip: set[str]) -> tuple[str, list[str]]:
    """CI's mechanical steps at `commit` in the replayer's worktree: "fail" when any counted step
    fails, with the failed steps named."""
    dr.git("checkout", "-q", "-f", "--detach", commit, repo=r.wt)
    dr.git("clean", "-fdxq", repo=r.wt)
    failed = []
    for step in CI_STEPS:
        if step in skip:
            continue
        try:
            p = subprocess.run(step, shell=True, cwd=r.wt, env=r.env, capture_output=True, text=True, timeout=1200)
            ok = p.returncode == 0
        except subprocess.TimeoutExpired:
            ok = False
        if not ok:
            failed.append(step)
    return ("fail" if failed else "pass"), failed


def rejudge(receipt: Path) -> int:
    """Judge again each patch of `receipt` that has no verdict, and write the measures beside it."""
    rec = json.loads(receipt.read_text())
    with dr.store_copy(dr.main_store()) as store:
        nodes = {lid: store.get_node(lid) for lid in rec["lessons"]}
    waiting = {p["lesson"] for p in rec["patches"] if p.get("judge") is None}
    dr.as_recorded({lid: nodes[lid] for lid in waiting}, rec.get("lesson_sha"))
    room = Path(tempfile.mkdtemp(prefix="okl-rejudge-"))
    patches, redone = rec["patches"], []
    for p in patches:
        if p.get("patch"):
            p["diff"] = (dr.RESULTS / p["patch"]).read_text()
        if p.get("judge") is None and p.get("diff"):
            n = nodes[p["lesson"]]
            text = LESSON.format(title=n.title, symptom=n.symptom or "", fix=n.fix or "")
            j = claude(JUDGE, JUDGE_PROMPT.format(lesson=text, diff=p["diff"][:12000]), room)
            p.update(judge_first=p.get("judge_said"), judge=judged(j.get("result") or ""),
                     judge_cost=j.get("cost_usd", 0.0), judge_said=(j.get("result") or j.get("error") or "")[-300:],
                     rejudged=True)
            redone.append(f'{p["lesson"]}-{p["kind"]}-{p["k"]}')
            print(f'{redone[-1]:40} judge={p["judge"]}', flush=True)
    out = receipt.with_name(f"{receipt.stem}-rejudge.json")
    out.write_text(json.dumps({
        "what": "drift catch rate, patches without a verdict judged once more (REPORT §4af)",
        "at": f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}", "receipt": receipt.name,
        "code": dr.git("rev-parse", "--short=12", "HEAD").strip(), "judge": " ".join(JUDGE), "rejudged": redone,
        "cost_usd": round(sum(p.get("judge_cost", 0) for p in patches if p.get("rejudged")), 2),
        "summary": summarize(patches),
        "patches": [{k: v for k, v in p.items() if k != "diff"} for p in patches],
    }, indent=1) + "\n")
    print(f"receipt: {out.relative_to(dr.REPO)}")
    return 0


def main() -> int:
    """Break each lesson, judge and evaluate every patch, and write the receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3, help="lessons worked at once")
    ap.add_argument("--rejudge", type=Path, help="judge again the patches of this receipt that have no verdict")
    args = ap.parse_args()
    if args.rejudge:
        return rejudge(args.rejudge.resolve())
    base = dr.git("rev-parse", BASE).strip()
    rules = dr.snapshot(base)
    with dr.store_copy(dr.main_store()) as store:
        nodes = {i: store.get_node(i) for i in rules}
        store.close()
    stamp = f"{datetime.now(UTC):%Y%m%d-%H%M}"
    partial = Path(tempfile.gettempdir()) / f"okl-drift-mutate-{base[:12]}.jsonl"
    done: dict[tuple, dict] = {}
    if partial.exists():
        for line in partial.read_text().splitlines():
            got = json.loads(line)
            done[(got["lesson"], got["kind"], got["k"])] = got
    main_status = dr.git("status", "--porcelain", repo=dr.main_store().parent.parent)
    lessons, left_out = [], {}
    for lid, rule in rules.items():
        check = dr.parse_check(rule.get("verified_by"))
        why = "no check recorded" if not check else dr.outside_commit(check[0])
        if why:
            left_out[lid] = why
        else:
            lessons.append((lid, rule, check))

    room = Path(tempfile.mkdtemp(prefix="okl-mutate-"))
    (room / "control").mkdir()
    control = dr.Replayer(room / "control")
    try:
        ci_base, ci_base_failed = run_ci(control, base, set())
        for lid, _rule, check in list(lessons):
            if control.verdict(base, *check) != "pass":
                left_out[lid] = "its check does not pass at BASE"
                lessons = [x for x in lessons if x[0] != lid]
    finally:
        control.close()
    skip = set(ci_base_failed)
    print(f"{len(lessons)} lessons; left out: {left_out}; CI at BASE {ci_base} {ci_base_failed}", flush=True)

    def work(slot: int, lesson: tuple) -> list[dict]:
        lid, rule, (cmd, expect) = lesson
        n = nodes[lid]
        text = LESSON.format(title=n.title, symptom=n.symptom or "", fix=n.fix or "")
        files = dr.governs(rule)
        wt = room / f"breaker-{slot}-{lid[:16]}"
        dr.git("worktree", "add", "-q", "--detach", str(wt), base)
        (room / f"eval-{slot}").mkdir()
        r = dr.Replayer(room / f"eval-{slot}")
        out = []
        try:
            for kind, count in (("breaking", BREAKING), ("harmless", HARMLESS)):
                earlier: list[str] = []
                for k in range(count):
                    key = (lid, kind, k)
                    if key in done:
                        p = done[key]
                        earlier += changed_files(p.get("diff") or "")
                        out.append(p)
                        continue
                    dr.git("checkout", "-q", "-f", "--detach", base, repo=wt)
                    dr.git("clean", "-fdxq", repo=wt)
                    (wt / "okl-drift.json").unlink(missing_ok=True)
                    avoid = (f"\n\nEarlier changes for this lesson edited {', '.join(sorted(set(earlier)))}; make a "
                             "different change." if earlier else "")
                    prompt = (BREAK_PROMPT.format(lesson=text, avoid=avoid) if kind == "breaking" else
                              HARMLESS_PROMPT.format(lesson=text, files=", ".join(files), avoid=avoid))
                    s = claude(BREAKER, prompt, wt)
                    dr.git("checkout", "-q", "HEAD", "--", "okl-drift.json", repo=wt)
                    diff = dr.git("diff", "HEAD", repo=wt)
                    p = {"lesson": lid, "kind": kind, "k": k, "ci_run": ci_run_lesson(cmd), "diff": diff,
                         "said": (s.get("result") or "")[-300:], "breaker_cost": s.get("cost_usd", 0.0)}
                    if s.get("error"):
                        p["error"] = s["error"]
                    if diff:
                        dr.git("add", "-A", repo=wt)
                        dr.git("-c", "user.name=drift-mutate", "-c", "user.email=drift-mutate@localhost",
                               "commit", "-q", "--no-verify", "-m", f"{kind} {k} for {lid}", repo=wt)
                        commit = dr.git("rev-parse", "HEAD", repo=wt).strip()
                        if commit == base:   # git() never raises: a commit that failed is caught here
                            raise RuntimeError(f"could not commit {kind} {k} for {lid}")
                        p["red"] = dr.differs(base, commit, files)
                        p["check"] = r.verdict(commit, cmd, expect)
                        if kind == "breaking":
                            p["ci"], p["ci_failed"] = run_ci(r, commit, skip)
                        j = claude(JUDGE, JUDGE_PROMPT.format(lesson=text, diff=diff[:12000]), room)
                        p["judge"], p["judge_cost"] = judged(j.get("result") or ""), j.get("cost_usd", 0.0)
                        p["judge_said"] = (j.get("result") or j.get("error") or "")[-300:]
                    earlier += changed_files(diff)
                    with partial.open("a") as f:
                        f.write(json.dumps(p) + "\n")
                    print(f"{lid[:20]:20} {kind:8} {k} red={p.get('red')} check={p.get('check')} "
                          f"ci={p.get('ci')} judge={p.get('judge')} files={changed_files(diff)}", flush=True)
                    out.append(p)
        finally:
            r.close()
            dr.git("worktree", "remove", "--force", str(wt))
        return out

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        patches = [p for ps in pool.map(work, range(len(lessons)), lessons) for p in ps]
    moved = dr.git("status", "--porcelain", repo=dr.main_store().parent.parent) != main_status
    patch_dir = dr.RESULTS / f"drift-mutate-{stamp}-patches"
    patch_dir.mkdir(exist_ok=True)
    for p in patches:
        if p.get("diff"):
            name = f'{p["lesson"]}-{p["kind"]}-{p["k"]}.diff'
            (patch_dir / name).write_text(p["diff"])
            p["patch"] = f"{patch_dir.name}/{name}"
    receipt = {
        "what": "drift catch rate (REPORT §4af)", "at": f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}",
        "code": dr.git("rev-parse", "--short=12", "HEAD").strip(), "base": base[:12],
        "breaker": " ".join(BREAKER), "judge": " ".join(JUDGE), "ci_steps": CI_STEPS,
        "ci_at_base": {"verdict": ci_base, "failed": ci_base_failed}, "left_out": left_out,
        "lessons": [lid for lid, _r, _c in lessons], "main_checkout_changed": moved,
        "lesson_sha": {lid: dr.text_sha(nodes[lid]) for lid, _r, _c in lessons},
        "cost_usd": round(sum(p.get("breaker_cost", 0) + p.get("judge_cost", 0) for p in patches), 2),
        "summary": summarize(patches),
        "patches": [{k: v for k, v in p.items() if k != "diff"} for p in patches],
    }
    out = dr.RESULTS / f"drift-mutate-{stamp}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps(receipt["summary"], indent=1))
    print(f"receipt: {out.relative_to(dr.REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
