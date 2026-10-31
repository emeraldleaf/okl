"""The A/B harness's grading of one sample, and what its receipt records (#164)."""
from __future__ import annotations

import importlib.util
import json
import shlex
from pathlib import Path

import pytest

HARNESS = Path(__file__).resolve().parents[1] / "evals" / "ab_harness.py"
TASK = {"id": "idor_endpoint", "task": "add GET /orders/{id}", "signal": "no ownership check",
        "defect_node": "n_x"}


@pytest.fixture
def ab(monkeypatch):
    """evals/ab_harness.py as a module (it is a script, not part of the package). It reads
    GENERATOR_TOOLS at import, so every test starts one-shot whatever the shell sets (review on
    #305); a test that wants tools on sets the attribute."""
    monkeypatch.delenv("GENERATOR_TOOLS", raising=False)
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


def test_the_generator_is_compared_as_it_ran(ab, monkeypatch):
    """The base command alone let a tools-on run, and one run --restricted, read as the one-shot
    series (review on #305)."""
    one_shot = [_receipt(ab.JUDGE_MAX_CHARS)] * 3
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    current = {"generator": ab.generator_cmd(), "judge": "claude -p --model haiku",
               "judge_max_chars": ab.JUDGE_MAX_CHARS}
    assert ab.instrument_drift(one_shot, current) == {"generator": {"series": "claude -p --model sonnet", "runs": 3}}
    # Receipts before §4ab record the tools apart; they ran the base with --allowedTools (§4r).
    legacy = {**_receipt(ab.JUDGE_MAX_CHARS), "generator_tools": "Bash(okl show:*)"}
    assert ab.ran_commands(legacy)["generator"] == "claude -p --model sonnet --allowedTools 'Bash(okl show:*)'"
    # §4ab's receipt records the command it ran, which this run's --restricted changes.
    recorded = {**legacy, "generator_cmd": "claude -p --model sonnet --strict-mcp-config --allowedTools 'Bash(okl show:*)'"}
    assert ab.instrument_drift([recorded] * 2, current)["generator"]["runs"] == 2
    assert ab.instrument_drift([recorded] * 2, {**current, "generator": recorded["generator_cmd"]}) == {}


def test_the_when_tool_arm_is_compared_with_the_runs_of_that_arm(ab, monkeypatch):
    """Its command and its tool's description are its treatment; the drift check compared only
    the Bash arms' command (review on #305)."""
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    base = {"generator": ab.generator_cmd(), "judge": "claude -p --model haiku",
            "judge_max_chars": ab.JUDGE_MAX_CHARS}
    tool = ab.when_tool_instrument(["line", "when-tool"])
    assert ab.when_tool_instrument(["line"]) == {} and "--restricted" in tool["when_tool_generator"]
    ran = {**_receipt(ab.JUDGE_MAX_CHARS, generator=""), "generator_cmd": ab.generator_cmd(), **tool}
    # The same arm, run the same way: nothing differs.
    assert ab.instrument_drift([ran] * 2, {**base, **tool}) == {}
    # §4ab's when-tool command had no --restricted: a run of the arm now differs from it.
    old = {**ran, "when_tool_generator": tool["when_tool_generator"].replace("--restricted ", "")}
    assert ab.instrument_drift([old], {**base, **tool}) == {
        "when_tool_generator": {"series": old["when_tool_generator"], "runs": 1}}
    # A new description is a new treatment; a run without the arm compares neither.
    assert "fetch_tool_description" in ab.instrument_drift([ran], {**base, **tool, "fetch_tool_description": "x"})
    assert ab.instrument_drift([old], base) == {}


def test_the_models_resolve_from_the_commands_the_run_uses(ab, monkeypatch):
    """With tools on the generator runs --restricted, so its model is resolved that way too
    (review on #305)."""
    monkeypatch.setattr(ab, "resolved_model", lambda cmd, timeout, workdir: cmd)
    assert ab.resolved_models(5, ".") == {"generator": ab.GENERATOR_CMD, "judge": ab.JUDGE_CMD}
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    assert ab.resolved_models(5, ".")["generator"] == ab.generator_cmd()
    assert "--restricted" in ab.generator_cmd()


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


def test_tree_state_fails_closed_when_git_diff_fails(ab, tmp_path, monkeypatch):
    """A dirty tree whose diff cannot be read must not fingerprint equal to itself either."""
    import subprocess
    repo = tmp_path / "r"
    (repo / "src" / "okl").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    (repo / "src" / "okl" / "new.py").write_text("x = 1\n")   # dirty, so the diff runs
    monkeypatch.setattr(ab, "REPO", repo)
    real = subprocess.run

    def broken(cmd, *a, **kw):
        if "diff" in cmd:
            return subprocess.CompletedProcess(cmd, 128, stdout=b"", stderr=b"fatal")
        return real(cmd, *a, **kw)
    monkeypatch.setattr(ab.subprocess, "run", broken)
    one, two = ab.tree_state(), ab.tree_state()
    assert one[0].endswith("+unknown") and one[1] != two[1]


def test_tree_state_fails_closed_when_head_cannot_be_read(ab, tmp_path, monkeypatch):
    """Outside a repository the probe has no HEAD; two readings must still differ."""
    monkeypatch.setattr(ab, "REPO", tmp_path)   # not a git repository
    one, two = ab.tree_state(), ab.tree_state()
    assert one[0] is None and one[1] != two[1]
    assert ab.head_moved(one, two) is not None


def test_tree_state_fails_closed_when_the_full_head_cannot_be_read(ab, monkeypatch):
    """The short HEAD read but the full one did not (review on #262): an empty fingerprint
    would compare equal to itself, so two readings must differ instead."""
    import subprocess
    real = subprocess.run

    def broken(cmd, *a, **kw):
        if list(cmd[-2:]) == ["rev-parse", "HEAD"]:
            return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal")
        return real(cmd, *a, **kw)
    monkeypatch.setattr(ab.subprocess, "run", broken)
    one, two = ab.tree_state(), ab.tree_state()
    assert one[0] is None and one[1] != two[1]
    assert ab.head_moved(one, two) is not None


def test_tree_state_fails_closed_when_an_untracked_file_vanishes_mid_read(ab, tmp_path, monkeypatch):
    """A file git listed as untracked that cannot be read a moment later is a moving tree:
    the probe reports it as such rather than raising past the run's receipt."""
    import subprocess
    repo = tmp_path / "r"
    (repo / "src" / "okl").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "base"], check=True)
    (repo / "src" / "okl" / "new.py").write_text("x = 1\n")   # untracked, so it is read
    monkeypatch.setattr(ab, "REPO", repo)

    def vanished(self):
        raise OSError("gone")
    monkeypatch.setattr(ab.Path, "read_bytes", vanished)
    one, two = ab.tree_state(), ab.tree_state()
    assert one[0].endswith("+unknown") and one[1] != two[1]
    assert ab.head_moved(one, two) is not None


# ---- §4ab: what each line arm says, and the path each arm can fetch by (#304) ----

ALSO = [{"id": "g", "type": "Defect", "title": "Tokens in localStorage", "fix": "hold them in memory."},
        {"id": "o", "type": "Rule", "title": "Pin the IdP policy", "fix": "pin it in config."},
        {"id": "w", "type": "Rule", "title": "Withdrawn", "fix": "", "avoid": "withdrawn"}]
LESSONS = {"g": {"symptom": "tokens written to localStorage", "triggers": "Adding login"},
           "o": {"symptom": "", "triggers": "\nScaling the IdP\nSecond trigger"},
           "w": {"symptom": "anything"}}


def test_a_when_line_says_the_symptom_else_the_first_trigger_cut_at_a_word(ab):
    """As the fix's sentence is cut, so a when line costs what a line costs."""
    assert ab.when_text(LESSONS["g"], 160) == "tokens written to localStorage"
    assert ab.when_text(LESSONS["o"], 160) == "Scaling the IdP"
    assert ab.when_text({}, 160) == ""
    assert ab.when_text({"symptom": "one two three four"}, 12) == "one two…"


def test_the_line_arms_differ_only_in_what_each_line_says(ab):
    """`line` is §4aa's line untouched; `titles` drops the fix; `when` says when the lesson
    applies instead. An AVOID entry is the same warning in every arm."""
    assert ab.restyled(ALSO, "line", LESSONS, 160) is ALSO
    titles = ab.restyled(ALSO, "titles", LESSONS, 160)
    when = ab.restyled(ALSO, "when", LESSONS, 160)
    assert [e["fix"] for e in titles] == ["", "", ""]
    assert [e["fix"] for e in when] == ["when you see: tokens written to localStorage",
                                        "when you see: Scaling the IdP", ""]
    for arm in (titles, when):
        assert [(e["id"], e["title"]) for e in arm] == [(e["id"], e["title"]) for e in ALSO]
        assert arm[2] == ALSO[2]
    assert ALSO[0]["fix"] == "hold them in memory."     # the check result is not changed in place
    assert ab.LINE_STYLES["when-tool"] == "when"         # the tool arm reads the when arm's lines


def test_a_restyle_that_changed_nothing_is_named_so_the_task_fails_closed(ab):
    """An experiment cannot measure a change it never made."""
    line = "- [g] Pin the linter — Pin ruff to an exact version.\n- [o] other — fix"
    when = "- [g] Pin the linter — when you see: CI fails after a ruff release\n- [o] other — fix"
    same = {"line": line, "titles": line, "when": when, "when-tool": when}
    assert ab.unchanged_by_style(same, ["line", "titles", "when"], "g") == ["titles"]
    assert ab.unchanged_by_style(same, ["line", "when", "when-tool"], "g") == []
    # A governing lesson with no symptom or trigger: the when arms lose its fix and gain no
    # "when you see", so they differ from the line arm and still carry no treatment.
    bare = "- [g] Pin the linter\n- [o] other — fix"
    flat = {"line": line, "titles": bare, "when": bare, "when-tool": bare}
    assert ab.unchanged_by_style(flat, ["line", "titles", "when", "when-tool"], "g") == ["when", "when-tool"]
    # The when wording on another lesson's line does not count for the governing one.
    other = "- [g] Pin the linter\n- [o] other — when you see: x"
    assert ab.unchanged_by_style({**flat, "when": other}, ["line", "when"], "g") == ["when"]


def test_a_tier_arm_without_its_treatment_fails_closed_alone(ab, monkeypatch, tmp_path):
    """One shared raise failed every tier arm and the briefed arms with them (review on #305)."""
    line = "- [g] Pin the linter — Pin ruff to an exact version."
    bare = "- [g] Pin the linter"
    monkeypatch.setattr(ab, "tier_briefings", lambda task, governing, timeout:
                        {"full": "FULL", "line": line, "titles": bare, "when": bare, "when-tool": bare})
    task = {**TASK, "defect_node": "g"}
    headers, err = ab.tier_headers_for(task, ["baseline", "full", "line", "titles", "when"], 5)
    assert sorted(headers) == ["full", "line", "titles"]
    assert "the when briefing does not carry its treatment" in err
    rec, ok = ab.run_one(task, "when", 0, briefed_header=None, brief_err=err, timeout=5,
                         workdir=str(tmp_path), tier_headers=headers)
    assert not ok and "does not carry its treatment" in rec["error"]
    assert ab.tier_headers_for(task, ["baseline", "briefed"], 5) == ({}, "")

    def broken(task, governing, timeout):
        raise RuntimeError("okl check failed")
    monkeypatch.setattr(ab, "tier_briefings", broken)
    assert ab.tier_headers_for(task, ["line"], 5) == ({}, "okl check failed")


def test_each_arm_can_fetch_only_by_the_path_it_offers(ab, monkeypatch):
    """With tools on only the named MCP servers load, so the Bash arms cannot reach okl_get and
    the when-tool arm can reach nothing else; with tools off the one-shot command is unchanged."""
    assert ab.generator_cmd("when-tool", "/x/c.json") == ab.GENERATOR_CMD == ab.generator_cmd()
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    bash, tool = ab.generator_cmd("line"), ab.generator_cmd("when-tool", "/x/c.json")
    assert "--strict-mcp-config" in bash and "'Bash(okl show:*)'" in bash and "--mcp-config" not in bash
    assert tool.endswith('--strict-mcp-config --mcp-config /x/c.json --tools "" --allowedTools mcp__okl__okl_get')
    assert "Bash" not in tool
    # No settings file is read, so the user's own allow rules add no way to the store, and the
    # tools are only those named: Bash alone, or none at all in the when-tool arm (review on #305).
    for cmd, tools in ((bash, "Bash"), (tool, "")):
        split = shlex.split(cmd)
        assert "--restricted" in split and split[split.index("--tools") + 1] == tools


def test_the_tool_config_carries_only_what_the_tool_needs(ab, monkeypatch, tmp_path):
    """The config file is written per sample; the environment can hold secrets, so it is never
    copied in."""
    monkeypatch.setenv("SOME_API_KEY", "do-not-write")
    path = ab.write_fetch_tool_config(str(tmp_path / "shim-t-when-tool-0.log"))
    text = Path(path).read_text()
    server = json.loads(text)["mcpServers"]["okl"]
    assert "do-not-write" not in text
    assert set(server["env"]) == {"OKL_SHIM_LOG", "OKL_BRIEFING_LOG", "OKL_DATABASE_URL", "PYTHONPATH"}
    assert server["args"] == [str(ab.FETCH_SERVER)]


def test_a_fetch_through_the_tool_counts_as_a_shim_fetch_does(ab, monkeypatch, tmp_path):
    """Only a fetch that returned a lesson counts, by either path (review on #269)."""
    import okl.client
    spec = importlib.util.spec_from_file_location("fetch_tool", ab.FETCH_SERVER)
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)

    class Store:
        def get(self, id):
            return {"id": id, "title": "T"} if id == "g" else None
    monkeypatch.setattr(okl.client, "Client", Store)
    log = tmp_path / "shim.log"
    monkeypatch.setenv("OKL_SHIM_LOG", str(log))
    assert json.loads(tool.okl_get("g"))["title"] == "T"
    assert tool.okl_get("nope") == "no lesson with id 'nope'"
    assert ab.fetched_ids(str(log)) == ["g"]
    assert ab.fetch_tool_description() == tool.DESCRIPTION


def test_the_when_tool_arm_runs_its_own_briefing_and_command(ab, monkeypatch, tmp_path):
    """Its briefing from the tier headers, its command with a per-sample tool config."""
    seen = {}

    def fake_call(cmd, prompt, timeout, workdir, env=None):
        if cmd == ab.JUDGE_CMD:
            return json.dumps({"implemented": True, "defect_reproduced": False, "reason": "r"})
        seen.update(cmd=cmd, prompt=prompt)
        return "code"
    monkeypatch.setattr(ab, "call", fake_call)
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    headers = {a: f"BRIEFING {a}\n" for a in ab.TIER_ARMS}
    rec, ok = ab.run_one(TASK, "when-tool", 0, briefed_header=None, brief_err="", timeout=5,
                         workdir=str(tmp_path), tier_headers=headers)
    assert ok and rec["fetched"] == [] and rec["fetched_governing"] is False
    assert "BRIEFING when-tool" in seen["prompt"]
    assert "--mcp-config" in seen["cmd"] and ".mcp.json" in seen["cmd"]


def test_the_when_tool_arm_needs_tools_on(ab, monkeypatch):
    """Without GENERATOR_TOOLS the other arms could fetch nothing, so the arms are refused."""
    import argparse
    with pytest.raises(argparse.ArgumentTypeError, match="GENERATOR_TOOLS"):
        ab.parse_arms("line,when-tool")
    # titles and when point at a fetch too: one-shot, nothing logs one (review on #305).
    for arms in ("line,titles", "baseline,when"):
        with pytest.raises(argparse.ArgumentTypeError, match="GENERATOR_TOOLS"):
            ab.parse_arms(arms)
    assert ab.parse_arms("baseline,line,full") == ["baseline", "line", "full"]
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    assert ab.parse_arms("line,titles,when,when-tool") == ["line", "titles", "when", "when-tool"]


def test_a_fetch_path_that_did_not_open_refuses_the_run(ab, monkeypatch):
    """A tool that never loaded would read as an agent that never fetched (§4ab)."""
    asked = []
    # The checkout guard (exit 7) runs first, and in a worktree whose okl is another checkout's
    # it answered before the probe this test is about (review on #305).
    monkeypatch.setattr(ab, "code_outside_checkout", lambda: "")
    monkeypatch.setattr(ab, "GENERATOR_TOOLS", "Bash(okl show:*)")
    monkeypatch.setattr(ab, "probe_fetch", lambda w, g, t, *, tool: asked.append(tool) or ("" if not tool else "no fetch"))
    models = {"generator": None, "judge": None}
    code, why = ab.startup_refusal(models, ["line", "when-tool"], ".", "g", 5)
    assert code == 6 and "okl_get" in why and asked == [False, True]
    assert ab.startup_refusal(models, ["line"], ".", "g", 5) is None
    # A when-tool-only run is offered okl_get alone, so okl show is not probed (review on #305).
    asked.clear()
    ab.startup_refusal(models, ["when-tool"], ".", "g", 5)
    assert asked == [True]


def test_the_tier_arms_differ_only_in_where_the_governing_lesson_is(ab, monkeypatch):
    """§4aa's instrument: the line arm names the lesson as the first one-line entry and nowhere
    in full, the full arm shows it in full and not as a line, and the second tier keeps its
    length (review on #303: tier_briefings had no test)."""
    import dataclasses
    from types import SimpleNamespace

    from okl import core
    from okl.store import Store
    s = Store("sqlite:///:memory:")
    core.record(s, type="Rule", scope="org", id="g", title="rotate webhook signing secrets on schedule")
    for i, title in enumerate(("webhook retries need idempotency keys", "log every webhook delivery",
                               "webhook payloads are untrusted input")):
        core.record(s, type="Rule", scope="org", id=f"o{i}", title=title)
    task = "rotate the webhook signing secrets"
    natural = core.check(s, repo="r", task=task, decision="tiered")
    assert core.briefed_ids(natural) == ["g"] and len(natural["also_matched"]) == 3

    def fake_run(cmd, **_kw):
        out = natural if "check" in cmd else dataclasses.asdict(s.get_node("g"))
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")
    monkeypatch.setattr(ab.subprocess, "run", fake_run)
    arms = ab.tier_briefings(task, "g", 5)
    full, line = arms["full"], arms["line"]

    def entries(text):
        return [ln.split("]")[0][3:] for ln in text.splitlines() if ln.startswith("- [")]
    assert full == core.render_check_for_agent(natural)
    assert entries(line) == ["g", *entries(full)[:2]]
    assert "rotate webhook signing secrets on schedule" in full.split("### Also matched")[0]
    assert "rotate webhook signing secrets" not in line.split("### Also matched")[0]


def test_the_full_arm_keeps_the_natural_order_when_the_lesson_is_already_in_full(ab, monkeypatch):
    """Moving the governing lesson to the end of its section reordered the routed actions, so
    the full arm was not the natural briefing for three of §4aa's tasks (review on #303)."""
    import dataclasses
    from types import SimpleNamespace

    from okl import core
    from okl.store import Store
    s = Store("sqlite:///:memory:")
    core.record(s, type="Rule", scope="org", id="g", title="rotate webhook signing secrets on schedule")
    core.record(s, type="Rule", scope="org", id="h", title="webhook signing secrets rotate with a grace window")
    task = "rotate the webhook signing secrets"
    natural = core.check(s, repo="r", task=task, decision="tiered")
    assert core.briefed_ids(natural)[:2] == ["g", "h"]

    def fake_run(cmd, **_kw):
        out = natural if "check" in cmd else dataclasses.asdict(s.get_node("g"))
        return SimpleNamespace(returncode=0, stdout=json.dumps(out), stderr="")
    monkeypatch.setattr(ab.subprocess, "run", fake_run)
    full = ab.tier_briefings(task, "g", 5)["full"]
    assert full == core.render_check_for_agent(natural)


def test_the_run_refuses_to_measure_another_checkouts_code(ab, monkeypatch, tmp_path):
    """An editable install points `python -m okl` at the checkout it was installed from, so a run
    from a worktree without PYTHONPATH measured another tree's code (review on #303). It passes
    when both load this process's okl, which PYTHONPATH arranges here as a run arranges it; a
    bare worktree's shell is exactly the mismatch it refuses."""
    import okl
    src = Path(okl.__file__).resolve().parents[1]
    monkeypatch.setattr(ab, "REPO", src.parent)
    monkeypatch.setenv("PYTHONPATH", str(src))
    assert ab.code_outside_checkout() == ""
    monkeypatch.setattr(ab, "REPO", tmp_path)
    assert str(tmp_path / "src") in ab.code_outside_checkout()
    code, why = ab.startup_refusal({"generator": None, "judge": None}, ["line"], ".", "g", 5)
    assert code == 7 and "PYTHONPATH" in why
