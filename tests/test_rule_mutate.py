"""REPORT §4bf's instrument: what it hides from the breaker, how it sorts a check, what it counts."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
spec = importlib.util.spec_from_file_location("rule_mutate", ROOT / "evals" / "rule_mutate.py")
assert spec and spec.loader
rm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rm)


def test_the_population_is_nine_and_nine():
    """Nine lessons #415 hardened and nine whose check came before it, each with its stored check."""
    groups = [p["group"] for p in rm.POPULATION.values()]
    assert groups.count(rm.HARDENED) == 9 and groups.count(rm.OLDER) == 9
    assert all("stored" in p["checks"] for p in rm.POPULATION.values())


def test_the_split_lessons_have_an_incident_part_and_a_rulewide_part():
    """The four whose stored check joins an incident test to a sweep run both parts alone too."""
    assert sorted(rm.SPLIT) == sorted(["n_e7988ff536fb", "n_5ddb0776a863", "n_02cc84da158d", "n_0637c92c032f"])
    for lid in rm.SPLIT:
        checks = rm.POPULATION[lid]["checks"]
        assert {"incident", "rulewide"} <= set(checks) and rm.POPULATION[lid]["group"] == rm.HARDENED


def test_every_check_file_a_check_names_is_hidden():
    """A breaker that could read the check could write past it (lesson n_85b9d0a7823d)."""
    for p in rm.POPULATION.values():
        for run, _expect in p["checks"].values():
            for word in run.replace("::", " ").split():
                if word.startswith(("tests/", "ci/", "./ci/")) and "." in word.rsplit("/", 1)[-1]:
                    assert word.removeprefix("./") in rm.HIDE, word


def test_a_governed_file_is_never_hidden(tmp_path):
    """docs-agent-neutral's breaker must read and edit docs/, posts included."""
    for x in ("docs/posts", "evals/REPORT.md", "tests/test_exit_codes.py"):
        (tmp_path / x).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / x).write_text("") if "." in x else (tmp_path / x).mkdir()
    assert rm.hidden(tmp_path, ["README.md", "docs/"]) == ["evals/REPORT.md", "tests/test_exit_codes.py"]
    assert "docs/posts" in rm.hidden(tmp_path, [])


def test_a_check_is_caught_only_by_its_own_failure():
    """A check that did not run has not caught anything (§4bd's rule, every check passing at BASE)."""
    assert rm.sort_one({"passed": True, "own_failure": False}) == "missed"
    assert rm.sort_one({"passed": False, "own_failure": True}) == "caught"
    assert rm.sort_one({"passed": False, "own_failure": False}) == "cannot_judge"


def _row(lid: str, kind: str, judge: str, **sorted_: str) -> dict:
    return {"lesson": lid, "group": rm.POPULATION[lid]["group"], "kind": kind, "k": 0, "diff": "x",
            "judge": judge, "sorted": sorted_}


def test_the_summary_counts_only_judged_breaks_and_controls():
    """A break counts when the judge says broken, a control when it says intact."""
    rows = [
        _row("n_02cc84da158d", "breaking", "broken", stored="caught", incident="missed", rulewide="caught"),
        _row("n_02cc84da158d", "breaking", "intact", stored="caught", incident="missed", rulewide="caught"),
        _row("n_e7988ff536fb", "breaking", "broken", stored="caught", incident="missed", rulewide="caught",
             **{"rulewide-no-inventory": "missed"}),
        _row("n_6b65aa35593c", "breaking", "broken", stored="missed"),
        _row("n_6b65aa35593c", "harmless", "intact", stored="caught"),
        _row("n_6b65aa35593c", "harmless", "broken", stored="caught"),
    ]
    s = rm.summarize(rows)
    assert s["breaks"] == 3
    assert (s["groups"][rm.HARDENED]["caught"], s["groups"][rm.HARDENED]["of"]) == (2, 2)
    assert (s["groups"][rm.OLDER]["caught"], s["groups"][rm.OLDER]["of"]) == (0, 1)
    assert (s["groups"][rm.OLDER]["controls"], s["groups"][rm.OLDER]["controls_failed"]) == (1, 1)
    assert (s["split"]["rulewide_only"], s["split"]["incident_only"], s["split"]["breaks"]) == (2, 0, 2)
    assert s["inventory_only"] == 1


PRECHECK = ROOT / "evals" / "results" / "rule-mutate-precheck-20261113-2349.json"
CONTROL = ROOT / "evals" / "results" / "rule-mutate-control-20261113-2349.json"


def _section() -> str:
    text = (ROOT / "evals" / "REPORT.md").read_text()
    return text.split("## 4bf.", 1)[1].split("\n## ", 1)[0]


def test_the_pre_registration_quotes_its_receipts():
    """Every figure §4bf quotes from drafting is read here from the receipt it names."""
    import json
    sec, pre, ctl = _section(), json.loads(PRECHECK.read_text()), json.loads(CONTROL.read_text())
    assert PRECHECK.name in sec and CONTROL.name in sec
    assert pre["left_out"] == {} and len(pre["checks"]) == 18 == len(rm.POPULATION)
    assert all(r["passed"] for checks in pre["checks"].values() for r in checks.values())
    older = sorted(lid for lid, p in rm.POPULATION.items() if p["group"] == rm.OLDER)
    assert pre["older_by_rule"] == older
    by_group = {g: sum(sum(pre["past_breaks"][lid].values()) for lid, p in rm.POPULATION.items() if p["group"] == g)
                for g in (rm.HARDENED, rm.OLDER)}
    assert by_group == {rm.HARDENED: 38, rm.OLDER: 25}
    assert "| 38 |" in sec and "| 25 |" in sec
    assert ctl["sorted"] == {"stored": "caught", "incident": "missed", "rulewide": "caught"}
    assert pre["okl_commit"] == ctl["okl_commit"] and ctl["file"] == rm.CONTROL_FILE
    assert "usable" not in pre and "usable" not in ctl


def test_the_budget_matches_the_instrument_and_section_4af():
    """108 patches, 72 of them breaking; §4af's 78 patches cost $5.20."""
    import json
    sec, n = _section(), len(rm.POPULATION)
    assert (n * (rm.BREAKING + rm.HARMLESS), n * rm.BREAKING) == (108, 72)
    assert "108" in sec and "72 breaking" in sec
    af = json.loads((ROOT / "evals" / "results" / "drift-mutate-20261031-1522.json").read_text())
    assert (af["cost_usd"], len(af["patches"])) == (5.2, 78) and "$5.20" in sec


def test_a_throwaway_commit_runs_no_git_hooks():
    """--no-verify skips pre-commit and commit-msg, not prepare-commit-msg: §4bf's run sent every
    patch commit through the developer's own prepare-commit-msg hook. Both mutation scripts turn hooks off."""
    for script in ("rule_mutate.py", "drift_mutate.py"):
        src = (ROOT / "evals" / script).read_text()
        assert '"-c", "core.hooksPath=/dev/null", "commit"' in src, script


RESULT = ROOT / "evals" / "results" / "rule-mutate-20261114-1606.json"
REJUDGE = ROOT / "evals" / "results" / "rule-mutate-rejudge-20261114-1624.json"


def _pct(k: int, n: int) -> str:
    return f"{100 * k / n:.1f}%"


def _interval(pair: list[float]) -> str:
    """A receipt's four-place bounds as percentages to one place, rounding the written digits half up:
    a float's own formatting turns 0.3145 into 31.4, where the unrounded bound is 31.4513."""
    from decimal import ROUND_HALF_UP, Decimal

    def one(x: float) -> str:
        return str((Decimal(str(x)) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP))
    return f"{one(pair[0])}–{one(pair[1])}%"


def test_the_result_quotes_its_receipt():
    """Every figure in §4bf's result is read here from the receipt it names."""
    import json
    sec, rec = _section(), json.loads(RESULT.read_text())
    s = rec["summary"]
    assert RESULT.name in sec and rec["rows_made_at"] == ["eb6cc25"] and rec["base"] == ["eb6cc25c0e62"]
    assert "usable" not in rec and f"made at BASE `{rec['rows_made_at'][0]}`" in sec
    assert len(list((RESULT.parent / RESULT.stem).with_name(RESULT.stem + "-patches").iterdir())) == 108
    assert s["unusable"] == 0 and s["judge"]["breaking:broken"] == 61 and s["judge"]["breaking:intact"] == 6
    assert s["judge"]["harmless:intact"] == 35 and s["judge"]["breaking:none"] + s["judge"]["harmless:none"] == 6
    assert "61 of the 72 breaking" in sec and "called 6 intact" in sec and "35 of the\n  36 harmless" in sec
    assert f"${rec['cost_usd']:.2f}" == "$8.62" and "$8.62" in sec
    for g, label in ((rm.HARDENED, "hardened"), (rm.OLDER, "older")):
        v = s["groups"][g]
        assert not v["sorted"].get("cannot_judge")
        row = (f"{v['caught']} of {v['of']} ({_pct(v['caught'], v['of'])}), Wilson {_interval(v['wilson95'])}, "
               f"lesson bootstrap {_interval(v['bootstrap95_by_lesson'])}")
        assert row in sec, (label, row)
        assert f"{v['controls_failed']} of {v['controls']}" in sec
    sp = s["split"]
    assert (sp["breaks"], sp["rulewide_only"], sp["incident_only"], sp["both"], sp["neither"]) == (15, 2, 4, 0, 9)
    assert "the rule-wide part alone caught 2, the incident part\nalone 4, both 0, neither 9" in sec
    assert s["inventory_only"] == 0
    h, o = s["groups"][rm.HARDENED], s["groups"][rm.OLDER]
    assert round(100 * (h["rate"] - o["rate"])) == 21 and "21 points" in sec


def test_the_miss_table_matches_the_rows():
    """The per-lesson misses the reading names, read from the receipt."""
    import json
    s = json.loads(RESULT.read_text())["summary"]["per_lesson"]
    missed = {lid: v["breaks"] - v["stored_caught"] for lid, v in s.items() if v["group"] == rm.HARDENED}
    assert sum(missed.values()) == 18
    sec = _section()
    for lid, n in missed.items():
        short = lid.rsplit(":", 1)[-1]
        assert f"| {short} | {n} of {s[lid]['breaks']} |" in sec, short
    assert s["remote-timeout-not-a-deadline"]["stored_caught"] == 4
    assert all(s[lid]["stored_caught"] == 1 for lid in ("n_6b65aa35593c", "n_849a5b0425ef", "n_adea7f2c7373"))
    assert s["n_8a6e1abce5cc"]["breaks"] == 0
    assert s["n_5ddb0776a863"]["rulewide_caught"] == 0 and s["n_5ddb0776a863"]["incident_caught"] == 3


def test_the_rejudge_quotes_its_receipt():
    """Re-judged apart: two verdicts, four still none, the older group at exactly a quarter."""
    import json
    sec, rj = _section(), json.loads(REJUDGE.read_text())
    assert REJUDGE.name in sec and f"${rj['cost_usd']:.2f}" == "$0.52" and "$0.52" in sec
    assert len(rj["rejudged"]) == 6 and sum(a["judge"] is None for a in rj["rejudged"]) == 4
    got = {(a["lesson"], a["k"]): a["judge"] for a in rj["rejudged"] if a["judge"]}
    assert got == {("n_c95bdc056620", 2): "broken", ("n_b550ba9c5c8a", 1): "intact"}
    o = rj["summary"]["groups"][rm.OLDER]
    assert (o["caught"], o["of"]) == (7, 28) and "7 of 28 (25.0%)" in sec
    assert rj["summary"]["groups"][rm.HARDENED]["caught"] == 16


SENSITIVITY = ROOT / "evals" / "results" / "rule-mutate-sensitivity-20261114-1648.json"


def test_the_sensitivity_note_quotes_its_receipt():
    """§4bf's note on how firm the reading is, read from its receipt."""
    import json
    sec, s = _section(), json.loads(SENSITIVITY.read_text())
    assert SENSITIVITY.name in sec and "usable" not in s
    assert s["lessons_governing_files"] == ["docs-agent-neutral"]
    assert s["breaks_on_edit_would_check"] == [3, 4] and "checked 4 of\n  the 61 confirmed breaks and caught 3" in sec
    assert s["registered"] == {rm.HARDENED: [16, 34], rm.OLDER: [7, 27]}
    k, n = s["without_n_0637c92c032f"][rm.HARDENED]
    assert (k, n) == (16, 31) and f"{_pct(k, n)}" == "51.6%" and "16\n  of 31 (51.6%)" in sec
    assert round(100 * (k / n - 7 / 27), 1) == 25.7 and "25.7 points" in sec
    h, o = s["unjudged_breaking_counted_missed"][rm.HARDENED], s["unjudged_breaking_counted_missed"][rm.OLDER]
    assert (h, o) == ([16, 35], [7, 31]) and _pct(*o) == "22.6%" and len(s["unjudged_breaking"]) == 5
    assert "16 of 35 and 7 of 31 (22.6%)" in sec
    assert s["judged_on_a_cut_diff"] == ["n_0637c92c032f harmless 0 172615 chars"] and "172,615 characters" in sec
    perm = s["permutation"]
    assert (perm["lessons"], perm["hardened"], perm["splits"]) == (17, 9, 24310)
    assert round(100 * perm["observed_gap"], 1) == 21.1 and round(100 * perm["two_sided_p"], 1) == 25.5
    assert "(24,310 splits)" in sec and "21.1 points in 25.5%" in sec
