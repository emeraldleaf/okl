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
