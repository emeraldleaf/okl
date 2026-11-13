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
