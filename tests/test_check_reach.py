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
    """§4bd's result quotes the score, the count and the positive control; every figure in it is read
    here from its receipt (the review of #442 changed eleven and this test passed them all)."""
    import statistics
    results = REPO / "evals" / "results"
    score = json.loads(sorted(results.glob("check-reach-2026*.json"))[-1].read_text())
    count = json.loads(sorted(results.glob("check-reach-count-2*.json"))[-1].read_text())["counts"]
    control = json.loads(sorted(results.glob("check-reach-control-*.json"))[-1].read_text())
    report = (REPO / "evals" / "REPORT.md").read_text()
    section = " ".join(report[report.index("## 4bd."):report.index("## 5. Findings")].split())
    s = score["sorted"]
    receipt_name = sorted(results.glob("check-reach-2026*.json"))[-1].name
    assert f"receipt `{receipt_name}`; rows made at `{score['rows_made_at'][0]}`" in section
    assert f"All {score['with_a_check']} checks ran at both ends" in section
    assert f"| {score['broken']} | {score['with_a_check']} | {s.get('caught', 0)} | {s['missed']} | {s['cannot_judge']} |" in section
    assert score["reading"] == "they cannot, as lessons stand" and "they cannot, as lessons stand" in section
    assert s.get("caught", 0) < 13 and f"{s['missed']} checks passed at both ends" in section
    half = score["per_half"]
    assert f"dev {half['dev']['caught']} of {half['dev']['broken']}, test {half['test']['caught']} of {half['test']['broken']}" in section
    why = score["cannot_judge_reasons"]
    for phrase, key in (("{} a test not yet written", "a test not yet written"),
                        ("{} the pre-flight, which needs a store", "needs a store, which the environment does not name"),
                        ("{} a script not yet there", "a script not yet there"),
                        ("{} their signal missing at both ends", "its signal missing at both ends"),
                        ("{} a script not there at the base that passed at the change",
                         "a script not there at the base, passing at the change")):
        assert phrase.format(why[key]) in section, (phrase, why[key])
    assert sum(why.values()) == s["cannot_judge"]
    seconds = score["check_seconds_at_change"]
    assert f"{statistics.median(seconds)} s at the median and {max(seconds)} s at most" in section
    assert max(seconds) < 9 and "under nine seconds" in section
    named = score["lessons_naming_files"]
    assert len(named) == count["has_files"] and all(r["sorted"] == "cannot_judge" for r in named)
    assert sum(r["governs_a_changed_path"] for r in named) == count["governs_a_changed_path"]
    assert (f"The {count['has_files']} broken lessons that name files, {count['governs_a_changed_path']} of them "
            "a file their change touched, all cannot judge") in section
    assert f"{count['has_files']} of these {count['broken']}, and this count could not judge any of them" in section
    assert control["sorted"] == "caught" and control["before"]["passed"] and control["after"]["own_failure"]
    assert control["check"].startswith("python3 ci/") and "by a ci/ script failing in one tree" in section
    for phrase in (f"the {s['missed']} that passed at the base passed on the change",
                   f"for the {s['missed']} checks that passed at the base, as they were at each change"):
        assert phrase in section, phrase
    # the hook paragraph's changes are the receipt's, each named
    hook = section[section.index("The lessons the hook as built would run"):section.index("Not registered, a positive")]
    for r in named:
        assert f"#{r['pr']}" in hook, r
    # the erratum's two rows: the pilot ran these commands at these changes, and both passed
    pilot = json.loads(sorted(results.glob("check-reach-pilot-2*.json"))[-1].read_text())
    ran = {(r["pr"], r["check"]): r["frozen"]["passed"] for r in pilot["rows"] if r.get("check")}
    assert ran[(309, next(c for pr, c in ran if pr == 309))] and ran[(198, next(c for pr, c in ran if pr == 198))]
    assert next(c for pr, c in ran if pr == 198) == "python3 -m pytest -q -k 'off_series_instrument'"
    assert "as 2 of the 75 rows below" in section and "`-k 'off_series_instrument'`" in section
    # §4af's figure, quoted here, is §4af's
    af = " ".join(report[report.index("## 4af."):report.index("## 4ag.")].split())
    assert "8 passed a check too narrow" in af and "in §4af, 8 of drift's misses passed a check too narrow" in section
