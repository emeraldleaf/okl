"""The A/B harness's grading of one sample, and what its receipt records (#164)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / "evals" / "ab_harness.py"
TASK = {"id": "idor_endpoint", "task": "add GET /orders/{id}", "signal": "no ownership check",
        "defect_node": "n_x"}


@pytest.fixture
def ab():
    """evals/ab_harness.py as a module (it is a script, not part of the package)."""
    spec = importlib.util.spec_from_file_location("ab_harness", HARNESS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _replies(ab, monkeypatch, code: str, verdict: dict | str):
    """The generator returns `code`; the judge returns `verdict`."""
    def fake_call(cmd, prompt, timeout, workdir):
        if cmd == ab.JUDGE_CMD:
            return verdict if isinstance(verdict, str) else json.dumps(verdict)
        return code
    monkeypatch.setattr(ab, "call", fake_call)


def _run(ab, arm="briefed"):
    return ab.run_one(TASK, arm, 1, briefed_header="BRIEFING\n", brief_err="",
                      timeout=5, workdir=".")


def test_a_sample_with_no_implementation_is_a_failure_not_a_clean_run(ab, monkeypatch):
    """§4j's briefed idor_endpoint sample 1 returned a plan; the judge said there was no
    code, and the harness still scored it clean, flattering the briefed arm (#164)."""
    _replies(ab, monkeypatch, "Plan: scope the query by buyer_id and return 404 otherwise.",
             {"implemented": False, "defect_reproduced": False,
              "reason": "No actual code was submitted, only a plan."})

    rec, ok = _run(ab)

    assert ok is False
    assert rec["unevaluable"] is True
    assert "no implementation to judge" in rec["error"] and "only a plan" in rec["error"]
    assert "reproduced" not in rec   # it is in no arm's denominator
    # what a reader needs to audit the verdict, since the receipt keeps no code
    assert rec["code_chars"] == len("Plan: scope the query by buyer_id and return 404 otherwise.")
    assert rec["excerpt"].startswith("Plan: scope the query")


def test_an_implemented_sample_is_scored_as_before(ab, monkeypatch):
    """The new field changes nothing for a sample that has code."""
    _replies(ab, monkeypatch, "def get_order(id): return db.get(id)",
             {"implemented": True, "defect_reproduced": True, "reason": "no ownership check"})

    rec, ok = _run(ab)

    assert ok is True and rec["reproduced"] is True and "unevaluable" not in rec
    assert rec["code_chars"] > 0 and "excerpt" not in rec


def test_a_verdict_that_does_not_say_whether_there_was_code_is_a_judge_failure(ab, monkeypatch):
    """The judge prompt is part of the instrument: a verdict in the old shape is not read
    as clean, it is counted as the judge failing."""
    _replies(ab, monkeypatch, "def get_order(id): ...",
             {"defect_reproduced": False, "reason": "scoped"})

    rec, ok = _run(ab)

    assert ok is False and "implemented" in rec["error"] and "unevaluable" not in rec


def test_the_judge_prompt_asks_whether_there_was_code(ab):
    """The verdict's new field is asked for in the prompt, with what counts as no code."""
    prompt = ab.JUDGE_PROMPT.format(task="t", signal="s", output="o")
    assert '"implemented": true or false' in prompt
    assert "only a plan" in prompt


def _stub_claude(tmp_path: Path, body: str) -> str:
    claude = tmp_path / "bin" / "claude"
    claude.parent.mkdir(parents=True, exist_ok=True)
    claude.write_text(f"#!/bin/sh\n{body}\n"); claude.chmod(0o755)
    return str(claude)


def test_the_receipt_can_name_the_model_an_alias_resolved_to(ab, tmp_path):
    """§4j's unbriefed arm fell 26 points and the receipt named only `sonnet` (R12)."""
    args = tmp_path / "args"
    claude = _stub_claude(tmp_path, f'echo "$@" > "{args}"\n'
                          'echo \'{"modelUsage": {"claude-sonnet-5-5-20260901": {}, '
                          '"claude-haiku-4-5-20251001": {}}, "result": "OK"}\'')

    models = ab.resolved_model(f"{claude} -p --model sonnet", 10, str(tmp_path))

    assert models == ["claude-haiku-4-5-20251001", "claude-sonnet-5-5-20260901"]
    assert args.read_text().split() == ["-p", "--model", "sonnet", "--output-format", "json"]


@pytest.mark.parametrize("case", ["not claude", "fails", "not json", "no modelUsage", "own format"])
def test_a_model_that_cannot_be_resolved_is_recorded_as_unknown(ab, tmp_path, case):
    """None, never a guess from the alias, and never an exception that stops the run."""
    cmd = {"not claude": "my-llm --model x",
           "fails": f"{_stub_claude(tmp_path, 'exit 1')} -p",
           "not json": f"{_stub_claude(tmp_path, 'echo OK')} -p",
           "no modelUsage": f"{_stub_claude(tmp_path, 'echo [1]')} -p",
           "own format": "claude -p --output-format text"}[case]

    assert ab.resolved_model(cmd, 10, str(tmp_path)) is None


@pytest.mark.parametrize(("generator", "judge", "same"), [
    (["claude-sonnet-5-5-20260901"], ["claude-sonnet-5-5-20260901"], True),
    (["claude-sonnet-5-5-20260901"], ["claude-haiku-4-5-20251001"], False),
    # unknown on either side cannot prove a match; the command-string guard still applies
    (None, ["claude-haiku-4-5-20251001"], False),
    (None, None, False),
])
def test_a_judge_that_resolves_to_the_generators_model_is_caught(ab, generator, judge, same):
    """Two command strings can name one model (`--model sonnet` and the full id), and the
    startup guard compared only the strings, so the judge could grade its own model's
    output (CodeRabbit on #168)."""
    assert ab.judge_is_generator({"generator": generator, "judge": judge}) is same


def test_the_judge_sees_a_long_submission_whole(ab, monkeypatch):
    """The judge saw only the first 8,000 characters: a 15,585-character rate limiter was
    cut off mid-line, the judge said there was no code, and §4l lost that sample (#182)."""
    seen = {}

    def fake_call(cmd, prompt, timeout, workdir):
        if cmd == ab.JUDGE_CMD:
            seen["prompt"] = prompt
            return json.dumps({"implemented": True, "defect_reproduced": False, "reason": "ok"})
        return "x = 1\n" * 2600   # 15,600 characters

    monkeypatch.setattr(ab, "call", fake_call)

    rec, ok = _run(ab)

    assert ok is True and rec["code_chars"] == 15600
    assert "x = 1\n" * 2600 in seen["prompt"]          # every character reached the judge


def test_a_submission_over_the_judges_window_is_unevaluable_without_a_judge_call(ab, monkeypatch):
    """Judging a cut-off copy is a guess: past the window the sample is a failure, marked
    as too long, and no judge is asked."""
    calls = []

    def fake_call(cmd, prompt, timeout, workdir):
        calls.append(cmd)
        return "y" * (ab.JUDGE_MAX_CHARS + 1)

    monkeypatch.setattr(ab, "call", fake_call)

    rec, ok = _run(ab)

    assert ok is False and rec["unevaluable"] is True and rec["truncated"] is True
    assert "longer than the judge's" in rec["error"]
    assert calls == [ab.GENERATOR_CMD]                  # the judge was never called


def test_the_receipt_names_the_judges_window(ab):
    """A receipt says how much of each submission its judge could read."""
    assert ab.JUDGE_MAX_CHARS >= 40_000


def test_a_submission_over_the_window_reads_too_long_not_no_code(ab, monkeypatch):
    """An over-window submission holds code; calling it NO CODE in the log and "no
    implementation to judge" in the report was false (review of #198)."""
    _replies(ab, monkeypatch, "x" * (ab.JUDGE_MAX_CHARS + 1), {})
    too_long, ok = _run(ab)
    _replies(ab, monkeypatch, "a plan", {"implemented": False, "defect_reproduced": False,
                                         "reason": "only a plan"})
    no_code, _ = _run(ab)

    assert not ok
    assert ab.failure_label(too_long) == "TOO LONG"
    assert ab.failure_label(no_code) == "NO CODE"
    assert ab.failure_label({"error": "timeout"}) == "FAILED"
    summary = ab.failure_causes([too_long, no_code, {"error": "timeout"}])
    assert "1 of them no implementation to judge" in summary
    assert "1 longer than the judge's window" in summary


def _receipt(window=None, generator="claude -p --model sonnet", judge="claude -p --model haiku"):
    r = {"generator": generator, "judge": judge}
    if window:
        r["judge_max_chars"] = window
    return r


@pytest.mark.parametrize(("prior", "window", "flagged"), [
    # The first run on the new window, after receipts that predate the field: flagged.
    ([_receipt()] * 5, 40_000, {"series": 8_000, "runs": 5}),
    # The new series, still outnumbered by older receipts: not flagged.
    ([_receipt()] * 5 + [_receipt(40_000)], 40_000, None),
    # A detour from the recorded series: flagged.
    ([_receipt()] * 5 + [_receipt(40_000)] * 2, 20_000, {"series": 40_000, "runs": 2}),
    # Old receipts, old window: the series.
    ([_receipt()] * 5, 8_000, None),
])
def test_the_judges_window_is_part_of_instrument_drift(ab, prior, window, flagged):
    """Going from 8,000 to 40,000 characters started a new series (REPORT §4m), and the
    drift check compared only the commands, so it said nothing (review of #198)."""
    current = {"generator": "claude -p --model sonnet", "judge": "claude -p --model haiku",
               "judge_max_chars": window}

    drift = ab.instrument_drift(prior, current)

    assert drift.get("judge_max_chars") == flagged
    assert "generator" not in drift and "judge" not in drift


def test_a_changed_judge_command_is_still_drift(ab):
    """The commands are still compared with their mode across every receipt."""
    current = {"generator": "claude -p --model sonnet", "judge": "claude -p --model opus",
               "judge_max_chars": ab.JUDGE_MAX_CHARS}

    drift = ab.instrument_drift([_receipt(ab.JUDGE_MAX_CHARS)] * 3, current)

    assert drift == {"judge": {"series": "claude -p --model haiku", "runs": 3}}


def test_a_run_whose_working_tree_moved_is_marked_not_usable(ab):
    """REPORT §4o: a branch switch during a run briefs the later samples with other code.
    The helper names both commits, and the banner says what to do instead."""
    same = ("acdcb99", "acdcb99full")
    assert ab.head_moved(same, same) is None
    assert ab.head_moved(None, same) is None       # unknown proves nothing, as elsewhere
    moved = ab.head_moved(("acdcb99", "acdcb99full"), ("b54e075", "b54e075full"))
    assert moved == {"okl_commit_at_start": "acdcb99", "okl_commit": "b54e075",
                     "working_tree_moved": True}
    banner = ab.moved_banner(moved)
    assert "NOT USABLE" in banner and "acdcb99" in banner and "b54e075" in banner
    # A tree that was already dirty and whose uncommitted code then changed: the label is
    # the same "+dirty" on both sides, the fingerprint is not, and that counts as movement.
    dirty_a = ("acdcb99+dirty", "acdcb99full+1111")
    dirty_b = ("acdcb99+dirty", "acdcb99full+2222")
    assert ab.head_moved(dirty_a, dirty_b)["working_tree_moved"] is True


def test_tree_state_fingerprints_uncommitted_code(ab, tmp_path, monkeypatch):
    """The label stays `<head>+dirty` while the fingerprint follows the uncommitted content."""
    import subprocess
    repo = tmp_path / "r"
    (repo / "src" / "okl").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    monkeypatch.setattr(ab, "REPO", repo)
    label, fp = ab.tree_state()
    assert "+dirty" not in label and "+" not in fp
    (repo / "src" / "okl" / "new.py").write_text("x = 1\n")
    label1, fp1 = ab.tree_state()
    (repo / "src" / "okl" / "new.py").write_text("x = 2\n")
    label2, fp2 = ab.tree_state()
    assert label1 == label2 and label1.endswith("+dirty")
    assert fp1 != fp2


def test_tree_state_hashes_each_untracked_file_separately(ab, tmp_path, monkeypatch):
    """Two untracked files whose contents shift a boundary must not fingerprint alike, and a
    path git would quote still reaches the manifest."""
    import subprocess
    repo = tmp_path / "r"
    (repo / "src" / "okl").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    monkeypatch.setattr(ab, "REPO", repo)
    a, b = repo / "src" / "okl" / "a.py", repo / "src" / "okl" / "b.py"
    a.write_text("ab"); b.write_text("c")
    _, fp1 = ab.tree_state()
    a.write_text("a"); b.write_text("bc")
    _, fp2 = ab.tree_state()
    assert fp1 != fp2
    quoted = repo / "src" / "okl" / "wei\u00dfe datei.py"   # a name git quotes in porcelain v1
    quoted.write_text("x = 1")
    _, fp3 = ab.tree_state()
    quoted.write_text("x = 2")
    _, fp4 = ab.tree_state()
    assert fp3 != fp4


def test_tree_state_fails_closed_when_git_status_fails(ab, tmp_path, monkeypatch):
    """A status probe that cannot run yields a fingerprint that equals nothing, so the run
    reads as moved and the receipt as not usable."""
    import subprocess
    real = subprocess.run

    def broken(cmd, *a, **kw):
        if "status" in cmd:
            return subprocess.CompletedProcess(cmd, 128, stdout=b"", stderr=b"fatal")
        return real(cmd, *a, **kw)
    monkeypatch.setattr(ab.subprocess, "run", broken)
    one, two = ab.tree_state(), ab.tree_state()
    assert one[0].endswith("+unknown") and one[1] != two[1]
    assert ab.head_moved(one, two) is not None
