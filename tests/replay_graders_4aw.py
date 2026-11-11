"""REPORT §4aw's graders, by behaviour: each drives a script through what it had when the change was frozen.

The real fixes' own tests called functions those fixes invented, so no agent could pass them without
guessing the names (§4aw's amendment). These ask what the lesson asks, with a positive control so a
fix that simply refuses everything fails too. Copied into a room as tests/test_replay_grader.py.
"""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "evals" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


class ReachedError(Exception):
    """The run went past the point a refusal belongs."""


def _harness(monkeypatch, tmp_path, gen, judge):
    ab = _load("ab_harness")
    monkeypatch.setattr(ab, "GENERATOR_CMD", gen)
    monkeypatch.setattr(ab, "JUDGE_CMD", judge)
    results = tmp_path / "results"
    results.mkdir()
    monkeypatch.setattr(ab, "RESULTS_DIR", results)
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps({"id": "t", "task": "x", "defect_node": ""}) + "\n")
    return ab, results, tasks


@pytest.mark.parametrize(("judge_model", "refused"), [("claude-sonnet-5-5", True), ("claude-haiku-5-5", False)])
def test_pr168(monkeypatch, tmp_path, judge_model, refused):
    """Two commands that resolve to one model must not start a run; two different models must."""
    gen, judge = "claude -p --model sonnet", f"claude -p --model {judge_model}"
    ab, _, tasks = _harness(monkeypatch, tmp_path, gen, judge)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text('{"repo": "r"}')
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{tmp_path / 'okl.db'}")
    monkeypatch.setattr(sys, "argv", ["ab_harness.py", "--tasks", str(tasks)])
    real_run = subprocess.run
    monkeypatch.setattr(ab.subprocess, "run", lambda cmd, *a, **k: SimpleNamespace(returncode=0, stdout="", stderr="")
                        if any("preflight" in str(c) for c in cmd) else real_run(cmd, *a, **k))
    models = {gen: ["claude-sonnet-5-5"], judge: [judge_model]}
    monkeypatch.setattr(ab, "resolved_model", lambda cmd, *a, **k: models[cmd])
    monkeypatch.setattr(ab, "get_briefing", lambda *a, **k: "b")

    def reached(*a, **k):
        raise ReachedError
    monkeypatch.setattr(ab, "run_one", reached)
    if refused:
        try:
            code = ab.main()
        except SystemExit as e:
            code = e.code
        except ReachedError:
            pytest.fail("the judge resolved to the generator's model and the run started")
        assert code not in (0, None)
    else:
        with pytest.raises(ReachedError):
            ab.main()


@pytest.mark.parametrize(("series_window", "flagged"), [(8000, True), (40000, False)])
def test_pr198(monkeypatch, tmp_path, capsys, series_window, flagged):
    """The judge's window is part of the instrument: a run on another window is refused or said so."""
    gen, judge = "claude -p --model sonnet", "claude -p --model haiku"
    ab, results, tasks = _harness(monkeypatch, tmp_path, gen, judge)
    for i in range(3):
        (results / f"ab-2026010{i}-0000.json").write_text(json.dumps({"generator": gen, "judge": judge, "judge_max_chars": series_window}))
    monkeypatch.setattr(sys, "argv", ["ab_harness.py", "--tasks", str(tasks), "--dry-run"])
    try:
        code = ab.main()
    except SystemExit as e:
        code = e.code
    got = capsys.readouterr()
    said = re.search(r"judge_max_chars|max.?chars|window", got.out + got.err, re.I) is not None
    assert (said or code not in (0, None)) is flagged, (code, (got.out + got.err)[-400:])


def test_pr196(monkeypatch, tmp_path):
    """An untracked seed pack must not reach the measurement; a tracked one must, unless the run refuses."""
    precision = _load("precision")
    repo = tmp_path / "repo"
    (repo / "seed").mkdir(parents=True)
    (repo / "seed" / "tracked.json").write_text("[]")
    subprocess.run(["git", "-C", str(repo), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "seed/tracked.json"], check=True)
    (repo / "seed" / "untracked.json").write_text("[]")
    monkeypatch.setattr(precision, "REPO", repo)
    seeded = []
    import okl.seed
    monkeypatch.setattr(okl.seed, "seed_from_file", lambda _client, path, *a, **k: seeded.append(Path(path).name))
    work = tmp_path / "work"
    work.mkdir()
    for name in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    try:
        precision._seeded_client(work)
    except (SystemExit, RuntimeError, ValueError):
        return   # refusing a dirty seed directory also keeps it out of the measurement
    assert seeded == ["tracked.json"], seeded


def _latency(monkeypatch, tmp_path, url):
    lat = _load("stem_latency")
    repo = tmp_path / "repo"
    (repo / ".okl").mkdir(parents=True)
    (repo / ".okl" / "config.json").write_text('{"repo": "r"}')
    (repo / ".okl" / "okl.db").write_text("")
    private = tmp_path / "private"
    private.mkdir()
    (private / "real-arms-heldout.json").write_text(json.dumps({"chosen": [["task", "p1"]]}))
    (private / "prompts.jsonl").write_text(json.dumps({"id": "p1", "text": "x"}) + "\n")
    monkeypatch.setattr(lat, "REPO", repo)
    monkeypatch.setattr(lat, "PRIVATE", private)
    monkeypatch.setenv("OKL_DATABASE_URL", url)
    monkeypatch.delenv("OKL_SERVICE_URL", raising=False)
    monkeypatch.chdir(repo)
    copied = []

    def reached(live, *a, **k):
        copied.append(Path(live))
        raise ReachedError
    monkeypatch.setattr(lat, "store_copy", reached)
    return lat, copied


def test_pr309_refuses_a_store_it_cannot_copy(monkeypatch, tmp_path):
    """A URL naming a store the script cannot time is refused, not swapped for a default file."""
    lat, copied = _latency(monkeypatch, tmp_path, "postgresql://h/db")
    try:
        lat.main()
    except SystemExit as e:
        assert e.code not in (0, None)
    except ReachedError:
        pytest.fail(f"a Postgres URL silently timed {copied}")
    else:
        pytest.fail("a Postgres URL neither refused nor stopped")


def test_pr309_still_honours_a_sqlite_url(monkeypatch, tmp_path):
    """The control: a SQLite URL is the store it copies."""
    other = tmp_path / "other.db"
    other.write_text("")
    lat, copied = _latency(monkeypatch, tmp_path, f"sqlite:///{other}")
    with pytest.raises(ReachedError):
        lat.main()
    assert copied == [other]
