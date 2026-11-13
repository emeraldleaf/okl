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
