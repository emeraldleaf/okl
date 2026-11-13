"""REPORT §4bd's instrument: how a stored check's runs at a change's base and at the change are sorted,
and the figures the pre-registration quotes from what was seen while drafting it."""
import importlib.util
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "evals"))
spec = importlib.util.spec_from_file_location("check_reach", REPO / "evals" / "check_reach.py")
assert spec and spec.loader
cr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cr)


def _run(passed, own=False):
    return {"passed": passed, "own_failure": own}


def test_a_pair_is_caught_only_when_the_check_passed_at_the_base_and_fails_by_its_own_failure():
    """The registered rule: caught needs a pass at the base and a failure of the check's own at the
    change; a check that could not pass at the base, or fails at the change only by not running,
    cannot judge; one passing at both missed."""
    assert cr.sort_pair(_run(True), _run(False, own=True)) == "caught"
    assert cr.sort_pair(_run(True), _run(True)) == "missed"
    assert cr.sort_pair(_run(True), _run(False, own=False)) == "cannot_judge"
    assert cr.sort_pair(_run(False), _run(False, own=True)) == "cannot_judge"


def test_a_check_that_did_not_run_is_not_its_own_failure(tmp_path):
    """Exit 1 and a missing signal are the check failing; a pytest collection, usage or empty
    selection error, a command not found, or a missing file are the check not running."""
    (tmp_path / "src").mkdir()
    py = sys.executable
    assert cr.run_check(tmp_path, f"{py} -c 'print(\"OK\")'", "OK")["passed"]
    failed = cr.run_check(tmp_path, f"{py} -c 'import sys; sys.exit(1)'", None)
    assert (failed["passed"], failed["own_failure"]) == (False, True)
    quiet = cr.run_check(tmp_path, f"{py} -c 'print(\"nope\")'", "OK")
    assert (quiet["passed"], quiet["own_failure"], quiet["why"]) == (False, True, "exit 0, signal missing")
    for code in (2, 4, 5, 127):
        r = cr.run_check(tmp_path, f"{py} -c 'import sys; sys.exit({code})'", None)
        assert (r["passed"], r["own_failure"]) == (False, False), code
    missing = cr.run_check(tmp_path, f"{py} no_such_script.py", None)
    assert (missing["passed"], missing["own_failure"]) == (False, False)


def test_the_figures_seen_while_drafting_are_the_receipts():
    """§4bd quotes the pilot and the store's fields; each figure is read from its receipt."""
    results = REPO / "evals" / "results"
    pilot = json.loads(sorted(results.glob("check-reach-pilot-2*.json"))[-1].read_text())
    count = json.loads(sorted(results.glob("check-reach-count-2*.json"))[-1].read_text())["counts"]
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = " ".join(report[report.index("## 4bd."):report.index("## 5. Findings")].split())
    assert (pilot["tasks"], pilot["told_apart"], pilot["with_a_check"], pilot["with_files"]) == (5, 0, 4, 0)
    assert "none told them apart" in section and "None of the five lessons names files" in section
    assert (f"of the {count['broken']} broken lessons, {count['has_check']} carry a stored check and "
            f"{count['has_files']} name files, {count['governs_a_changed_path']} of them a file their change "
            "touched") in section
    assert f"{count['changes']} past changes" in section
    assert math.ceil(count["broken"] * 0.10) == cr.CATCHES_NEEDED   # the fewest catches that make 10%
    assert f"at least {cr.CATCHES_NEEDED} of the {count['broken']}" in section


def test_the_result_figures_are_the_receipts():
    """§4bd's result quotes the score and the positive control; each figure is read from its receipt."""
    import statistics
    results = REPO / "evals" / "results"
    score = json.loads(sorted(results.glob("check-reach-2026*.json"))[-1].read_text())
    control = json.loads(sorted(results.glob("check-reach-control-*.json"))[-1].read_text())
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = " ".join(report[report.index("## 4bd."):report.index("## 5. Findings")].split())
    s = score["sorted"]
    assert f"| {score['broken']} | {score['with_a_check']} | {s.get('caught', 0)} | {s['missed']} | {s['cannot_judge']} |" in section
    assert score["reading"] == "they cannot, as lessons stand" and "they cannot, as lessons stand" in section
    assert s.get("caught", 0) < 13 and score["caught_governing_a_changed_path"] == 0
    half = score["per_half"]
    assert f"dev {half['dev']['caught']} of {half['dev']['broken']}, test {half['test']['caught']} of {half['test']['broken']}" in section
    why = score["cannot_judge_why"]
    assert why["base exit 4; change exit 4"] == 20 and "20 name a test file not yet written" in section
    assert why["base exit 2; change exit 2"] == 2 and why["base exit 1; change exit 1"] == 3
    seconds = score["check_seconds_at_change"]
    assert f"{statistics.median(seconds)} s at the median and {max(seconds)} s at most" in section
    assert control["sorted"] == "caught" and control["before"]["passed"] and control["after"]["own_failure"]


def test_the_rule_wide_pilot_names_what_the_mapping_and_the_counts_say():
    """§4be's table: each lesson's check is the file the mapping copies, each break count is the
    concentration receipt's, the total is 38, and every check exists on main at the source commit."""
    import subprocess
    concentration = json.loads((REPO / "evals" / "results" / "break-concentration-20261110-1600.json").read_text())
    breaks = {r["lesson"]: r["breaks"] for r in concentration["top20"]}
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = report[report.index("## 4be."):report.index("## 5. Findings")]
    total = 0
    for lesson, (path, _selector) in cr.RULEWIDE.items():
        short = lesson.rsplit(":", 1)[-1]
        row = next(line for line in section.splitlines() if line.startswith(f"| {short}"))
        assert f"| {breaks[lesson]} | {path} |" in row, (lesson, row)
        total += breaks[lesson]
        assert subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{cr.SOURCE}:{path}"]).returncode == 0
    assert total == 38 and "Together, 38 of the 124 breaks" in " ".join(section.split())
    assert f"main at {cr.SOURCE[:7]}" in section


def test_the_rule_wide_result_figures_are_the_receipt():
    """§4be's result quotes its receipt: the counts, the reasons, the reading."""
    receipt = json.loads(sorted((REPO / "evals" / "results").glob("check-reach-rulewide-*.json"))[-1].read_text())
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = " ".join(report[report.index("## 4be."):report.index("## 5. Findings")].split())
    s = receipt["sorted"]
    assert f"| {receipt['covered']} | {s.get('caught', 0)} | {s.get('missed', 0)} | {s['cannot_judge']} |" in section
    assert receipt["reading"] == "the backward method cannot judge today's checks" and receipt["reading"] in section
    why = receipt["cannot_judge_why"]
    assert (why["base exit 1; change exit 1"], why["base exit 2; change exit 2"]) == (23, 13)
    assert "23 by a failing test or script, 13 by a test file that would not even collect" in section
    assert receipt["per_check"]["ci/check-diagram-names.py"] == {"missed": 2}
