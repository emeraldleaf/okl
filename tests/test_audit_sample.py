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
