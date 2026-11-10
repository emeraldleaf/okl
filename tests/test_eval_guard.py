"""Every eval script that writes a receipt names the code that made it, start and end.

Lesson harness-reads-a-moving-working-tree, broken five times in new scripts that read HEAD once
(#300, #307, #309, #312, #363; #415). A script that refers to evals/results uses
evals/run_guard.py, or is listed below: the scripts written before the guard existed (2026-11-10),
which come off the list when they adopt it, and those that only read receipts.
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "evals"))
REFERS = re.compile(r"""["']results["']|evals/results|\bRESULTS\b""")
USES_GUARD = re.compile(r"^\s*(?:import run_guard|from run_guard import)", re.M)
GUARDED_OTHERWISE = {"evals/ab_harness.py": "its own start-and-end check (tree_state, head_moved), which run_guard lends out"}
READ_ONLY: dict[str, str] = {}   # a script that only reads receipts, with why
BEFORE_THE_GUARD = frozenset({
    "evals/admission_grid.py",
    "evals/bench/precision_detail.py",
    "evals/bench/precision_pairs.py",
    "evals/bench/rank_quality.py",
    "evals/bench/real_prompts.py",
    "evals/bench/run.py",
    "evals/bench/run_dense.py",
    "evals/bench/run_rerank.py",
    "evals/bench/run_v2.py",
    "evals/briefed_follow.py",
    "evals/briefing_arms.py",
    "evals/briefing_arms_detail.py",
    "evals/briefing_marks_size.py",
    "evals/briefing_size.py",
    "evals/common_word_grid.py",
    "evals/default_read.py",
    "evals/doc_claim_coverage.py",
    "evals/drift_mutate.py",
    "evals/drift_replay.py",
    "evals/drift_widen_cost.py",
    "evals/e2e_read_briefing.py",
    "evals/embedder_select.py",
    "evals/explain_search.py",
    "evals/harness_transcripts.py",
    "evals/hybrid_grid.py",
    "evals/layout_preflight.py",
    "evals/lesson_census.py",
    "evals/lesson_review.py",
    "evals/missed_evidence.py",
    "evals/missed_lessons.py",
    "evals/model_files.py",
    "evals/path_triggers.py",
    "evals/precision.py",
    "evals/preflight.py",
    "evals/probe_rephrase.py",
    "evals/reach_detail.py",
    "evals/realwork_reach.py",
    "evals/realwork_tasks.py",
    "evals/rerank_select.py",
    "evals/rerank_spike.py",
    "evals/review_action.py",
    "evals/review_action_detail.py",
    "evals/review_repo.py",
    "evals/review_repo_detail.py",
    "evals/review_state_detail.py",
    "evals/semantic_scale.py",
    "evals/standing_table.py",
    "evals/stem_latency.py",
    "evals/warm_latency.py",
    "evals/warm_memory.py",
    "evals/window_grid.py",
})


def eval_scripts() -> list[str]:
    """The committed eval scripts."""
    return subprocess.run(["git", "-C", str(REPO), "ls-files", "evals/*.py"], capture_output=True,
                          text=True, check=True).stdout.split()


def test_a_new_receipt_writer_uses_the_run_guard():
    """A script that refers to the results directory uses run_guard, or says why not."""
    missing = [f for f in eval_scripts() if f != "evals/run_guard.py" and REFERS.search((REPO / f).read_text())
               and not USES_GUARD.search((REPO / f).read_text())
               and f not in BEFORE_THE_GUARD | set(GUARDED_OTHERWISE) | set(READ_ONLY)]
    assert missing == [], ("use evals/run_guard.py: run = run_guard.start() before the first sample, "
                           f"run.stamp(receipt) before writing it: {missing}")


def test_the_list_only_shrinks():
    """A listed script that adopted the guard, or no longer exists, comes off the list."""
    scripts = set(eval_scripts())
    assert scripts >= BEFORE_THE_GUARD, sorted(BEFORE_THE_GUARD - scripts)
    adopted = [f for f in BEFORE_THE_GUARD if USES_GUARD.search((REPO / f).read_text())]
    assert adopted == [], f"remove from BEFORE_THE_GUARD: {adopted}"


def test_a_run_whose_code_moved_is_not_usable(monkeypatch, capsys):
    """The guard compares the code at the end with the code at the start."""
    import ab_harness as ab
    import run_guard
    states = iter([("abc1234", "full-a"), ("def5678", "full-b")])
    monkeypatch.setattr(ab, "tree_state", lambda reads=ab.RUN_READS: next(states))
    receipt = run_guard.start().stamp({"usable": True})
    assert receipt["usable"] is False and receipt["working_tree_moved"] is True
    assert (receipt["okl_commit_at_start"], receipt["okl_commit"]) == ("abc1234", "def5678")
    assert "NOT USABLE" in capsys.readouterr().err
    same = iter([("abc1234", "full-a"), ("abc1234", "full-a")])
    monkeypatch.setattr(ab, "tree_state", lambda reads=ab.RUN_READS: next(same))
    assert run_guard.start().stamp({"usable": True}) == {"usable": True, "okl_commit_at_start": "abc1234",
                                                         "okl_commit": "abc1234"}
