"""evals/audit_sample.py: the person's audit for #446 is blind, and scores what it registered."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))
spec = importlib.util.spec_from_file_location("audit_sample", ROOT / "evals" / "audit_sample.py")
assert spec and spec.loader
au = importlib.util.module_from_spec(spec)
spec.loader.exec_module(au)


def test_the_page_never_carries_a_models_answer():
    """An item that says what the judge or the key answered, or which stratum it came from, is refused."""
    au.assert_blind([{"id": "j01", "lesson": {}, "diff": "x", "files": [], "text_checked": True}])
    for leak in ("judge", "key", "suggested", "kind", "run"):
        with pytest.raises(ValueError, match="blind"):
            au.assert_blind([{"id": "j01", leak: "broken"}])


def test_answers_are_read_from_the_pages_documents():
    """The page stores {verdict, at}; a bare string works too; an empty or missing answer is none."""
    labels = {"a01": {"verdict": "needed", "at": "t"}, "k01": "broken", "k02": {"verdict": ""}, "j01": None}
    assert au.answered(labels, ["a01", "k01", "k02", "j01", "j02"]) == {"a01": "needed", "k01": "broken"}


def test_the_key_bar_is_on_what_it_calls_broken():
    """Of the pairs the key calls broken, the share the person calls broken; unsure is left out."""
    key = {f"k{i}": {"set": "key", "key": "broken"} for i in range(1, 5)} | {"k9": {"set": "key", "key": "followed"}}
    got = {"k1": "broken", "k2": "broken", "k3": "followed", "k4": "unsure", "k9": "followed"}
    out = au.score_key(key, got)
    assert (out["broken_precision"]["k"], out["broken_precision"]["n"]) == (2, 3) and out["passed"] is False
    assert out["table"] == {"broken->broken": 2, "broken->followed": 1, "broken->unsure": 1, "followed->followed": 1}


def test_the_judge_is_scored_per_stratum_and_reweighted_to_the_runs():
    """Protection removed counts as the claim holding. Sensitivity and specificity are estimated from
    each stratum's share and its size in the runs."""
    key = {"j1": "broken", "j2": "broken", "j3": "broken", "j4": "broken", "j5": "intact", "j6": "intact",
           "j7": None, "j8": None}
    key = {i: {"set": "judge", "judge": v} for i, v in key.items()}
    got = {"j1": "broken", "j2": "broken", "j3": "broken", "j4": "protection", "j5": "intact", "j6": "broken",
           "j7": "broken", "j8": "intact"}
    out = au.score_judge(key, got, {"broken": 100, "intact": 50, "none": 10})
    assert (out["broken_precision"]["k"], out["broken_precision"]["n"]) == (3, 4)
    assert (out["intact_precision"]["k"], out["intact_precision"]["n"]) == (1, 2)
    assert out["protection_removed"] == 1 and out["passed"] is False
    assert out["sensitivity_reweighted"] == round(75 / 105, 4) and out["specificity_reweighted"] == round(1 - 25 / 55, 4)


def test_the_audits_section_quotes_its_receipts():
    """REPORT §4bh: every figure is read from the audit's receipts, its draw made before any score, and who
    labelled each set is said; the key's broken population is §4bc to §4be's 124."""
    import json
    report = (ROOT / "evals" / "REPORT.md").read_text()
    sec = report.split("## 4bh.", 1)[1].split("\n## ", 1)[0]
    draw = json.loads((ROOT / "evals" / "results" / "audit-draw-20261114-1932.json").read_text())
    got = json.loads((ROOT / "evals" / "results" / "audit-20261114-1937.json").read_text())
    assert "audit-draw-20261114-1932.json" in sec and "audit-20261114-1937.json" in sec
    assert draw["sets"] == {"adjudication": 21, "key": 30, "judge": 60}
    assert draw["key_population"]["dev:broken"] + draw["key_population"]["test:broken"] == 124
    a, k, j = got["adjudication"], got["key"], got["judge"]
    assert (a["agreements_overturned"], a["agreements_sampled"], a["kappa_judge_vs_final"], a["passed"]) == (2, 10, 0.865, False)
    assert "2 of 10 overturned, κ 0.865" in sec
    assert (k["broken_precision"]["k"], k["broken_precision"]["n"], k["table"]["broken->followed"]) == (4, 12, 7)
    assert "4 of the 12" in sec and "read 7 of them as followed" in sec
    lo, hi = k["broken_precision"]["wilson95"]
    assert f"[{lo:.3f}, {hi:.3f}]" in sec.replace("0.1381", "0.138")
    assert (j["broken_precision"]["k"], j["broken_precision"]["n"], j["intact_precision"]["k"], j["passed"]) == (26, 30, 20, True)
    assert (j["none_broken_share"]["k"], j["protection_removed"]) == (10, 3)
    jlo, jhi = j["broken_precision"]["wilson95"]
    assert f"[{jlo:.3f}, {jhi:.3f}]" in sec and "Three of its broken calls" in sec
    assert draw["judge_left_out"] == {"lesson text changed since the run": 6}
    assert "`8cb38ba`" in sec and "`071accd`" in sec
    assert "not by a person" in sec and "I labelled the 21 adjudication pairs blind" in sec
    assert all(v.startswith(("the maintainer", "a second model")) for v in got["labelled_by"].values())
