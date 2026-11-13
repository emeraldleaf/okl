#!/usr/bin/env python3
"""REPORT §4bf: on fresh breaks of each rule on today's code, do the checks `okl on-edit` runs catch them?

§4bd ran lessons' checks backwards, at past changes, and §4be found that today's rule-wide checks
(#415) cannot be carried back: they fail on the older code before any break. This breaks each rule on
today's code instead, where every check passes to begin with (§4af's method): a breaker model writes
the break from the lesson's text alone, a judge model confirms it, and each check the lesson has runs
on it. Eighteen lessons in two groups: the nine #415 gave a check that sweeps the rule, and the nine
with the most breaks in past work among those whose check came before it.

    python3 evals/rule_mutate.py precheck [--receipt]   # every check at BASE; no model is called
    python3 evals/rule_mutate.py control [--receipt]    # one hand-written break; no model is called
    python3 evals/rule_mutate.py run [--workers 3]      # the registered measurement, resumable
    python3 evals/rule_mutate.py score [--receipt]
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
import tempfile
from collections import Counter
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import check_reach as cr
import drift_mutate as dm
import drift_replay as dr
import lesson_review as lr
import run_guard

REPO = dr.REPO
RESULTS = dr.RESULTS
ROWS = lr.PRIVATE / "rule-mutate-4bf.jsonl"
BREAKING, HARMLESS = 4, 2
SEED, BOOT = 264, 2000
HARDENED, OLDER = "hardened", "older"

# Each lesson's checks, by name. "stored" is the check `okl verify` stored for it, the one `okl on-edit`
# runs; it is read from the store at run time and must equal this, or the run refuses. For four of the
# hardened lessons the stored check joins a test of the lesson's incident to #415's sweep, and the two
# also run alone: "incident" and "rulewide". "rulewide-no-inventory" is the sweep without the tests that
# fail only because a new command, script or gate is not on its list.
EXIT_SWEEP = "python3 -m pytest -q tests/test_exit_codes.py"
NO_INVENTORY = (EXIT_SWEEP + " -k 'not (every_command_is_in_the_sweep or every_ci_script_is_swept_or_says_why"
                " or every_gate_is_in_the_sweep)'")
POPULATION: dict[str, dict] = {
    "n_e7988ff536fb": {"group": HARDENED, "checks": {
        "stored": ("python3 -m pytest -q -k 'fails_closed or empty_store_is_never_reported or search_scope_refuses"
                   " or never_reports_clean or test_exit_codes'", "passed"),
        "incident": ("python3 -m pytest -q -k 'fails_closed or empty_store_is_never_reported or search_scope_refuses"
                     " or never_reports_clean'", "passed"),
        "rulewide": (EXIT_SWEEP, "passed"), "rulewide-no-inventory": (NO_INVENTORY, "passed")}},
    "n_5ddb0776a863": {"group": HARDENED, "checks": {
        "stored": ("python3 -m pytest -q -k 'never_reports_clean or drift_step_warns or test_exit_codes'", "passed"),
        "incident": ("python3 -m pytest -q -k 'never_reports_clean or drift_step_warns'", "passed"),
        "rulewide": (EXIT_SWEEP, "passed"), "rulewide-no-inventory": (NO_INVENTORY, "passed")}},
    "n_02cc84da158d": {"group": HARDENED, "checks": {
        "stored": ("python3 -m pytest -q -k 'naming_a_store_by_env_var or client_resolves_the_shared_layer"
                   " or test_store_resolution'", "passed"),
        "incident": ("python3 -m pytest -q -k 'naming_a_store_by_env_var or client_resolves_the_shared_layer'",
                     "passed"),
        "rulewide": ("python3 -m pytest -q tests/test_store_resolution.py", "passed")}},
    "n_0637c92c032f": {"group": HARDENED, "checks": {
        "stored": ("python3 -m pytest -q tests/test_architecture.py::test_a_render_that_disagrees_with_its_source_fails",
                   "1 passed"),
        "incident": ("python3 -m pytest -q tests/test_architecture.py::test_a_render_that_disagrees_with_its_source_fails",
                     "1 passed"),
        "rulewide": ("python3 ci/check-diagram-names.py", "ok: every")}},
    "harness-reads-a-moving-working-tree": {"group": HARDENED, "checks": {
        "stored": ("python3 -m pytest -q tests/test_eval_guard.py", "passed")}},
    "seed:geospatial-enforcement-defects:r_single_source_sets": {"group": HARDENED, "checks": {
        "stored": ("python3 -m pytest -q tests/test_single_source.py", "4 passed")}},
    "seed:python-canon:py_dont_mock_what_you_dont_own": {"group": HARDENED, "checks": {
        "stored": ("python3 -m pytest -q tests/test_mock_ownership.py", "3 passed")}},
    "remote-path-test-through-client": {"group": HARDENED, "checks": {
        "stored": ("python3 -m pytest -q tests/test_client_service_contract.py", "2 passed")}},
    "docs-agent-neutral": {"group": HARDENED, "checks": {
        "stored": ("python3 ci/check-agent-neutral.py", "AGENT NEUTRAL")}},
    "n_6b65aa35593c": {"group": OLDER, "checks": {
        "stored": ("python3 -m pytest -q -k 'pipeline_diagram_is_current'", "passed")}},
    "n_00985805cdbb": {"group": OLDER, "checks": {
        "stored": ("python3 -m pytest -q -k 'token_out_of_git or safety_property'", "1 passed")}},
    "remote-timeout-not-a-deadline": {"group": OLDER, "checks": {
        "stored": ("env -u OKL_DATABASE_URL python3 -m pytest -q tests/test_remote_failures.py", "passed")}},
    "n_849a5b0425ef": {"group": OLDER, "checks": {
        "stored": ("python3 -m pytest -q -k 'applies_to or off_stack'", "passed")}},
    "n_adea7f2c7373": {"group": OLDER, "checks": {
        "stored": ("python3 -m pytest -q -k 'stored_data_never_reaches_a_shell'", "passed")}},
    "n_8a6e1abce5cc": {"group": OLDER, "checks": {
        "stored": ("python3 -m pytest -q -k 'off_series_instrument'", "passed")}},
    "n_b550ba9c5c8a": {"group": OLDER, "checks": {
        "stored": ("./ci/check-diagram-figures.sh", "DIAGRAM_FIGURES_RECEIPTED")}},
    "n_b74bad29fd87": {"group": OLDER, "checks": {
        "stored": ("python3 -m pytest -q -k 'backend_conformance'", "passed")}},
    "n_c95bdc056620": {"group": OLDER, "checks": {
        "stored": ("python3 -m pytest -q -k 'shipped_workflows_are_hardened'", "passed")}},
}
SPLIT = [lid for lid, p in POPULATION.items() if "incident" in p["checks"]]

# What tells a breaker how these lessons are checked (lesson n_85b9d0a7823d), kept out of its worktree:
# §4ah's list, every file a check here names, the eval scripts and tests that name the checks, and the
# write-ups of past breaks. A file the lesson governs is never hidden, since the breaker must read and
# edit it (docs-agent-neutral governs README.md and docs/). Contributor guidance stays: CLAUDE.md,
# CONTRIBUTING.md, AGENTS.md, the README, docs/ and the CI workflow name some checks, as they would for
# any contributor.
HIDE = (*dm.BLIND, "evals/check_reach.py", "tests/test_check_reach.py", "evals/rule_mutate.py",
        "evals/rule_mutate_control.txt",
        "tests/test_rule_mutate.py", "evals/drift_mutate.py", "evals/realwork", "evals/replay-tasks-4aw.json",
        "docs/posts",
        "tests/test_exit_codes.py", "tests/test_store_resolution.py", "tests/test_architecture.py",
        "ci/check-diagram-names.py", "tests/test_eval_guard.py", "tests/test_single_source.py",
        "tests/test_mock_ownership.py", "tests/test_client_service_contract.py", "ci/check-agent-neutral.py",
        "tests/test_remote_failures.py", "ci/check-diagram-figures.sh")

HARMLESS_PROMPT = """You are working in a software repository, your working directory. The project keeps this
lesson about itself:

{lesson}

Make one realistic change to this repository, in the part of it this lesson is about, of the kind a
contributor might make in the course of other work, after which the lesson still holds. Edit with your
tools, and do not mention the lesson.{avoid}

When you are done, answer with one sentence saying what you changed."""

# One hand-written break of n_02cc84da158d (a second reader of the storage variable), for `control`:
# can the instrument see a catch at all? The lines live in a text file because that lesson's sweep reads
# every committed .py outside tests/ and cannot tell a quoted read from a real one: written inline here,
# it failed the sweep at BASE.
CONTROL_FILE = "src/okl/cli/on_edit.py"
CONTROL_LINES = (REPO / "evals" / "rule_mutate_control.txt").read_text()


def hidden(tree: Path, governed: list[str]) -> list[str]:
    """The paths kept from the breaker: those of HIDE that exist and overlap nothing it governs."""
    return [x for x in dict.fromkeys(HIDE) if (tree / x).exists() and not dm.overlaps(x, governed)]


def sort_one(result: dict) -> str:
    """One check on one break, every check having passed at BASE: caught (it failed by its own
    failure), cannot judge (it failed only by not running) or missed (it passed)."""
    if result["passed"]:
        return "missed"
    return "caught" if result["own_failure"] else "cannot_judge"


def run_checks(tree: Path, lid: str) -> dict[str, dict]:
    """Every check of lesson `lid`, run in `tree`."""
    out = {}
    for name, (run, expect) in POPULATION[lid]["checks"].items():
        r = cr.run_check(tree, run, expect)
        out[name] = {k: r.get(k) for k in ("passed", "own_failure", "why", "exit", "tail", "seconds")}
    return out


def git(*a: str, repo: Path = REPO) -> str:
    """git in `repo`, this checkout by default."""
    return dr.git(*a, repo=repo)


def nodes_and_refusals() -> tuple[dict, dict[str, str]]:
    """Each lesson's text from a copy of the store, and why any lesson cannot run: missing, or its
    stored check no longer the one registered here."""
    from okl.cli.verification import _stored_check
    with dr.store_copy(dr.main_store()) as store:
        nodes = {lid: store.get_node(lid) for lid in POPULATION}
    refused = {}
    for lid, n in nodes.items():
        if n is None:
            refused[lid] = "not in the store"
            continue
        got = _stored_check(n.verified_by)
        want = POPULATION[lid]["checks"]["stored"]
        if got is None or got[0] != want[0] or (got[1] or None) != want[1]:
            refused[lid] = f"stored check is {got!r}, registered {want!r}"
    return nodes, refused


def base_of() -> str:
    """BASE: the commit that adds §4bf, named by the receipt; HEAD when it is clean."""
    if dr.dirty():
        raise SystemExit("rule_mutate: the checkout has uncommitted changes; BASE must be a commit")
    return git("rev-parse", "HEAD").strip()


def past_breaks() -> dict[str, dict[str, int]]:
    """§4bd's breaks per lesson, by how its check sorted them there."""
    out: dict[str, Counter] = {}
    for line in cr.ROWS.read_text().splitlines():
        row = json.loads(line)
        out.setdefault(row["lesson"], Counter())[row["sorted"]] += 1
    return {lid: dict(c) for lid, c in out.items()}


def older_by_rule(past: dict[str, dict[str, int]]) -> list[str]:
    """The older group's rule: outside #415's nine, at least two of §4bd's breaks, and a check §4bd
    could run at both ends of every one (none sorted cannot judge)."""
    hardened = {lid for lid, p in POPULATION.items() if p["group"] == HARDENED}
    return sorted(lid for lid, c in past.items()
                  if lid not in hardened and sum(c.values()) >= 2 and not c.get("cannot_judge"))


def precheck(args: argparse.Namespace) -> int:
    """Every check at BASE, in a clean tree. A lesson any of whose checks does not pass is left out.
    Also confirms the older group is the one its rule picks from §4bd's rows."""
    guard = run_guard.start()
    base = base_of()
    past = past_breaks()
    chosen = older_by_rule(past)
    older = sorted(lid for lid, p in POPULATION.items() if p["group"] == OLDER)
    if chosen != older:
        raise SystemExit(f"rule_mutate: the rule picks {chosen}, the registration names {older}")
    _nodes, refused = nodes_and_refusals()
    rows = {}
    with cr.Tree(base) as tree:
        for lid in POPULATION:
            rows[lid] = run_checks(tree, lid)
            print(f"{lid[:40]:40} " + " ".join(f"{k}={v['why']}" for k, v in rows[lid].items()), flush=True)
    left = {lid: "a check does not pass at BASE" for lid, r in rows.items() if not all(v["passed"] for v in r.values())}
    left.update(refused)
    if args.receipt:
        cr.write("rule-mutate-precheck", guard.stamp({"what": "REPORT §4bf: every check at BASE", "base": base[:12],
                                                     "left_out": left, "older_by_rule": chosen,
                                                     "past_breaks": {lid: past.get(lid, {}) for lid in POPULATION},
                                                     "checks": rows}))
    print(json.dumps({"lessons": len(POPULATION), "left_out": left}))
    return 0


def control(args: argparse.Namespace) -> int:
    """One hand-written break (a second reader of OKL_DATABASE_URL), committed in a scratch tree:
    n_02cc84da158d's rule-wide check should catch it and its incident check should not. Not
    registered as a measure."""
    guard = run_guard.start()
    base = base_of()
    with cr.Tree(base) as tree:
        with (tree / CONTROL_FILE).open("a") as f:
            f.write(CONTROL_LINES)
        got = run_checks(tree, "n_02cc84da158d")
    row = {name: sort_one(r) for name, r in got.items()}
    print(json.dumps(row))
    if args.receipt:
        cr.write("rule-mutate-control", guard.stamp({"what": "REPORT §4bf: a hand-written break, not registered",
                                                    "base": base[:12], "file": CONTROL_FILE,
                                                    "lines": CONTROL_LINES, "sorted": row, "checks": got}))
    return 0


def done() -> dict[tuple[str, str, int], dict]:
    """Rows already written for this BASE and these lesson texts, so a stopped run resumes."""
    if not ROWS.exists():
        return {}
    out = {}
    for line in ROWS.read_text().splitlines():
        row = json.loads(line)
        out[(row["lesson"], row["kind"], row["k"])] = row
    return out


def run(args: argparse.Namespace) -> int:
    """The registered measurement: four breaks and two harmless changes per lesson, each judged, and
    every check of the lesson run on each."""
    guard = run_guard.start()
    base = base_of()
    nodes, refused = nodes_and_refusals()
    if refused:
        raise SystemExit(f"rule_mutate: refused, the store no longer matches the registration: {refused}")
    with cr.Tree(base) as tree:
        failing = [f"{lid} {name}" for lid in POPULATION for name, r in run_checks(tree, lid).items() if not r["passed"]]
    if failing:
        raise SystemExit(f"rule_mutate: refused, these checks do not pass at BASE: {failing}")
    shas = {lid: dr.text_sha(n) for lid, n in nodes.items()}
    seen = {k: r for k, r in done().items() if r["base"] == base[:12] and r["lesson_sha"] == shas[r["lesson"]]}
    main_status = git("status", "--porcelain")
    room = Path(tempfile.mkdtemp(prefix="okl-4bf-"))

    def work(slot: int, lid: str) -> list[dict]:
        n = nodes[lid]
        text = dm.LESSON.format(title=n.title, symptom=n.symptom or "", fix=n.fix or "")
        governed = [g.strip() for g in (n.files or "").split(",") if g.strip()]
        wt = room / f"breaker-{slot}"
        git("worktree", "add", "-q", "--detach", str(wt), base)
        out = []
        try:
            for kind, count in (("breaking", BREAKING), ("harmless", HARMLESS)):
                earlier: list[str] = []
                for k in range(count):
                    if (lid, kind, k) in seen:
                        p = seen[(lid, kind, k)]
                        earlier += dm.changed_files(p.get("diff") or "")
                        out.append(p)
                        continue
                    git("checkout", "-q", "-f", "--detach", base, repo=wt)
                    git("clean", "-fdxq", repo=wt)
                    kept_out = hidden(wt, governed)
                    for x in kept_out:
                        (shutil.rmtree if (wt / x).is_dir() else Path.unlink)(wt / x)
                    avoid = (f"\n\nEarlier changes for this lesson edited {', '.join(sorted(set(earlier)))}; make a "
                             "different change." if earlier else "")
                    prompt = (dm.BREAK_PROMPT.format(lesson=text, avoid=avoid) if kind == "breaking" else
                              HARMLESS_PROMPT.format(lesson=text, avoid=avoid))
                    s = dm.claude(dm.BREAKER, prompt, wt)
                    git("checkout", "-q", "HEAD", "--", *kept_out, repo=wt)
                    git("add", "-A", repo=wt)
                    diff = git("diff", "--cached", "HEAD", repo=wt)   # with any file the breaker created
                    p = {"lesson": lid, "group": POPULATION[lid]["group"], "lesson_sha": shas[lid], "base": base[:12],
                         "okl_commit": guard.started[0], "kind": kind, "k": k, "hidden": kept_out, "diff": diff,
                         "said": (s.get("result") or "")[-300:], "breaker_cost": s.get("cost_usd", 0.0),
                         "breaker_models": s.get("models", [])}
                    if s.get("error"):
                        p["error"] = s["error"]
                    if diff:
                        git("-c", "user.name=rule-mutate", "-c", "user.email=rule-mutate@localhost",
                            "commit", "-q", "--no-verify", "-m", f"{kind} {k} for {lid}", repo=wt)
                        if git("rev-parse", "HEAD", repo=wt).strip() == base:
                            raise RuntimeError(f"could not commit {kind} {k} for {lid}")
                        p["checks"] = run_checks(wt, lid)
                        p["sorted"] = {name: sort_one(r) for name, r in p["checks"].items()}
                        j = dm.claude(dm.JUDGE, dm.JUDGE_PROMPT.format(lesson=text, diff=diff[:12000]), room)
                        p["judge"], p["judge_cost"] = dm.judged(j.get("result") or ""), j.get("cost_usd", 0.0)
                        p["judge_models"] = j.get("models", [])
                        p["judge_said"] = (j.get("result") or j.get("error") or "")[-300:]
                    earlier += dm.changed_files(diff)
                    with ROWS.open("a") as f:
                        f.write(json.dumps(p) + "\n")
                    print(f"{lid[:24]:24} {kind:8} {k} {p.get('sorted')} judge={p.get('judge')} "
                          f"files={dm.changed_files(diff)}", flush=True)
                    out.append(p)
        finally:
            git("worktree", "remove", "--force", str(wt))
        return out

    ROWS.parent.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(pool.map(work, range(len(POPULATION)), POPULATION))
    shutil.rmtree(room, ignore_errors=True)
    if git("status", "--porcelain") != main_status:
        print("rule_mutate: the main checkout changed during the run", file=sys.stderr)
    if guard.stamp({}).get("working_tree_moved"):
        print("rule_mutate: the code moved during the run; its rows are not usable", file=sys.stderr)
        return 1
    return 0


def rate(k: int, n: int) -> dict:
    """k of n, with its Wilson 95% interval."""
    return {"caught": k, "of": n, "rate": round(k / n, 4) if n else None, "wilson95": dr.wilson(k, n)}


def by_lesson_bootstrap(breaks: list[dict], caught: Callable[[dict], bool]) -> list[float] | None:
    """A 95% interval for the catch rate that resamples lessons, since one lesson's breaks are not independent."""
    lessons = sorted({p["lesson"] for p in breaks})
    rng, boot = random.Random(SEED), []   # noqa: S311 - a seeded bootstrap, not a secret
    for _ in range(BOOT):
        ps = [p for lid in (rng.choice(lessons) for _ in lessons) for p in breaks if p["lesson"] == lid]
        if ps:
            boot.append(sum(map(caught, ps)) / len(ps))
    boot.sort()
    return [round(boot[int(len(boot) * .025)], 4), round(boot[int(len(boot) * .975)], 4)] if boot else None


def summarize(rows: list[dict]) -> dict:
    """§4bf's measures from the rows."""
    breaks = [p for p in rows if p["kind"] == "breaking" and p.get("judge") == "broken" and p.get("diff")]
    controls = [p for p in rows if p["kind"] == "harmless" and p.get("judge") == "intact" and p.get("diff")]

    def stored_caught(p: dict) -> bool:
        return p["sorted"]["stored"] == "caught"

    groups = {}
    for g in (HARDENED, OLDER):
        bs = [p for p in breaks if p["group"] == g]
        cs = [p for p in controls if p["group"] == g]
        groups[g] = {**rate(sum(map(stored_caught, bs)), len(bs)),
                     "bootstrap95_by_lesson": by_lesson_bootstrap(bs, stored_caught),
                     "sorted": dict(Counter(p["sorted"]["stored"] for p in bs)),
                     "controls": len(cs), "controls_failed": sum(p["sorted"]["stored"] == "caught" for p in cs)}
    split = [p for p in breaks if p["lesson"] in SPLIT]
    pair = Counter(("rulewide" if p["sorted"]["rulewide"] == "caught" else "") +
                   ("+incident" if p["sorted"]["incident"] == "caught" else "") for p in split)
    swept = [p for p in breaks if "rulewide-no-inventory" in p["sorted"]]
    return {
        "breaking_patches": sum(p["kind"] == "breaking" for p in rows),
        "harmless_patches": sum(p["kind"] == "harmless" for p in rows),
        "judge": dict(Counter(f'{p["kind"]}:{p.get("judge") or "none"}' for p in rows)),
        "unusable": sum(1 for p in rows if not p.get("diff") or p.get("error")),
        "breaks": len(breaks), "groups": groups,
        "split": {"lessons": SPLIT, "breaks": len(split), "rulewide_only": pair["rulewide"],
                  "incident_only": pair["+incident"], "both": pair["rulewide+incident"], "neither": pair[""]},
        "inventory_only": sum(p["sorted"]["rulewide"] == "caught" and p["sorted"]["rulewide-no-inventory"] != "caught"
                              for p in swept),
        "per_lesson": {lid: {"group": POPULATION[lid]["group"],
                             "breaks": sum(p["lesson"] == lid for p in breaks),
                             **{f"{name}_caught": sum(p["lesson"] == lid and p["sorted"][name] == "caught" for p in breaks)
                                for name in POPULATION[lid]["checks"]},
                             "cannot_judge": sum(p["lesson"] == lid and p["sorted"]["stored"] == "cannot_judge"
                                                 for p in breaks),
                             "controls": sum(p["lesson"] == lid for p in controls),
                             "controls_failed": sum(p["lesson"] == lid and p["sorted"]["stored"] == "caught"
                                                    for p in controls)}
                       for lid in POPULATION},
    }


def score(args: argparse.Namespace) -> int:
    """The measures, and with --receipt the receipt and its patches."""
    guard = run_guard.start()
    rows = list(done().values())
    made_at = sorted({p.get("okl_commit") or "unknown" for p in rows})
    if len(made_at) > 1:
        print(f"rule_mutate: rows were made by different code: {made_at}", file=sys.stderr)
        return 1
    summary = summarize(rows)
    print(json.dumps(summary, indent=1))
    if args.receipt:
        stamp = f"{datetime.now(UTC):%Y%m%d-%H%M}"
        patch_dir = RESULTS / f"rule-mutate-{stamp}-patches"
        patch_dir.mkdir(exist_ok=True)
        for p in rows:
            if p.get("diff"):
                name = f'{p["lesson"].replace(":", "_")}-{p["kind"]}-{p["k"]}.diff'
                (patch_dir / name).write_text(p["diff"])
                p["patch"] = f"{patch_dir.name}/{name}"
        cr.write("rule-mutate", guard.stamp({
            "what": "REPORT §4bf: fresh breaks of each rule, and the checks okl on-edit runs",
            "base": sorted({p["base"] for p in rows}), "rows_made_at": made_at, "breaker": " ".join(dm.BREAKER), "judge": " ".join(dm.JUDGE),
            "models": {who: sorted({m for p in rows for m in p.get(f"{who}_models", [])}) for who in ("breaker", "judge")},
            "cost_usd": round(sum(p.get("breaker_cost", 0) + p.get("judge_cost", 0) for p in rows), 2),
            "summary": summary, "patches": [{k: v for k, v in p.items() if k != "diff"} for p in rows]}))
    return 0


def main() -> int:
    """Run the named step."""
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    for name, fn in (("precheck", precheck), ("control", control), ("run", run), ("score", score)):
        s = sub.add_parser(name)
        if name == "run":
            s.add_argument("--workers", type=int, default=3, help="lessons worked at once")
        else:
            s.add_argument("--receipt", action="store_true")
        s.set_defaults(func=fn)
    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
