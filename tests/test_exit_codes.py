"""Exit codes are this CLI's public API, and a check that read nothing never passes.

Lessons n_e7988ff536fb (0 clean, 1 findings, 2 refused, with the reason on stderr and stdout
empty) and n_5ddb0776a863 (a gate that inspected nothing has not passed). Past work broke the
first eight times and the second four (§4al and §4aq's keys; #415): a refusal on stdout, a
could-not-run read as a finding, a "nothing to check" that exited 0. This sweep runs every
command, every CI check and every gate where it cannot do its job, so a new one has to answer
the question here before it ships.
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from okl.cli import main
from okl.cli.parser import build_parser

REPO = Path(__file__).resolve().parent.parent

# Each command run in a directory where no store is named. Expected: 2 with nothing on stdout, or
# 0 where the command needs no store; a command the sweep cannot run says why.
COMMANDS: dict[str, list[str] | str] = {
    "push": ["--to", "https://okl.invalid"],
    "check": ["--task", "add a login page"], "record": ["--type", "Rule", "--title", "t", "--scope", "org"],
    "update": ["x", "--title", "y"], "retire": ["x", "--reason", "wrong"], "show": ["x"], "triggers": [],
    "recap": [], "link": ["a", "supersedes", "b"], "verify": ["x", "--run", "true", "--expect", "ok"],
    "reverify": [], "standing": ["list"], "on-edit": ["list"], "changes": [], "review": ["--list"], "search": ["login"],
    "metric": [], "drift": [], "export": ["--drift"], "dedup": [], "coverage": [],
    "doctor": "exits 0: it reports on the setup, and an unconfigured one is a finding it prints",
    "bootstrap": "exits 0: it proposes records from the repository's own signals and needs no store",
    "seed": "exits 0 with no pack named: it lists the bundled packs",
    "init": "writes the repository's wiring; tests/test_scaffold.py covers it",
    "connect": "writes a config naming a service; tests cover it",
    "scaffold": "writes the method kit into a repository; tests/test_scaffold.py covers it",
    "embed": "downloads a model on first use",
    "warm": "starts or stops a local model server",
    "serve": "starts a web service",
    "mcp": "starts an MCP server on stdio",
    "intake": "reads a pull request through gh and the network",
}
# Where the command needs no store, the code it must give anyway.
NO_STORE_CODE = {"changes": 2}   # outside a git repository it cannot read a change


def subcommands() -> set[str]:
    """Every subcommand the parser has."""
    import argparse
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    return set(sub.choices)


def test_every_command_is_in_the_sweep():
    """A new command answers here: what it does when it cannot run."""
    assert subcommands() == set(COMMANDS), "add the command to COMMANDS in tests/test_exit_codes.py"


@pytest.mark.parametrize("name", sorted(k for k, v in COMMANDS.items() if isinstance(v, list)))
def test_a_command_with_no_store_refuses_with_2_and_says_why_on_stderr(name, tmp_path, monkeypatch, capsys):
    """Run where nothing names a store: exit 2, the reason on stderr, stdout empty."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    args = COMMANDS[name]
    assert isinstance(args, list)
    try:
        code = main([name, *args])
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    got = capsys.readouterr()
    assert code == NO_STORE_CODE.get(name, 2), (code, got.err[-300:])
    assert got.out == "", f"a refusal printed to stdout: {got.out[:200]!r}"
    assert got.err.strip(), "a refusal must say why on stderr"


CHECKS_NOT_SWEPT = {"e2e.py": "installs okl into a fresh environment, for minutes; CI runs it",
                    "review-agent.sh": "runs a model on the pull request",
                    "lesson-review.sh": "runs a model on the pull request",
                    "_ran.py": "the helper each check installs, not a check"}
GATE_SKIP_SAYS = {"check-canon-size.sh": "skipping", "check-diagram-pairs.sh": "nothing to check",
                  "check-doc-orphans.sh": "skipping", "check-links.sh": "nothing to check",
                  "check-retractions.sh": "skipping", "check-tombstones.sh": "skipping"}


def _empty_repo(tmp_path: Path, script: Path, where: str) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "empty"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / where).mkdir()
    shutil.copy(script, repo / where / script.name)
    if script.suffix == ".py" and (script.parent / "_ran.py").exists():
        shutil.copy(script.parent / "_ran.py", repo / where / "_ran.py")
    return repo


def _run(repo: Path, rel: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, rel] if rel.endswith(".py") else ["bash", rel]
    env = {"PATH": os.environ["PATH"], "HOME": str(repo), "OKL_BRIEFING_LOG": "0"}
    return subprocess.run(cmd, cwd=repo, env=env, capture_output=True, text=True, timeout=300)


@pytest.mark.parametrize("name", sorted(f.name for f in (REPO / "ci").iterdir()
                                        if f.suffix in (".py", ".sh") and f.name not in CHECKS_NOT_SWEPT))
def test_a_ci_check_with_nothing_to_read_did_not_run(name, tmp_path):
    """In a repository holding none of its inputs, each of okl's CI checks exits 2 with stdout
    empty: not 1, which says it found something, and never 0, which says it passed."""
    repo = _empty_repo(tmp_path, REPO / "ci" / name, "ci")
    p = _run(repo, f"ci/{name}")
    assert p.returncode == 2, (p.returncode, p.stdout[-200:], p.stderr[-300:])
    assert p.stdout.strip() == "", p.stdout[-200:]


def test_every_ci_script_is_swept_or_says_why():
    """A new check in ci/ is swept unless it names its reason here."""
    scripts = {f.name for f in (REPO / "ci").iterdir() if f.suffix in (".py", ".sh")}
    assert set(CHECKS_NOT_SWEPT) <= scripts


@pytest.mark.parametrize("name", sorted(GATE_SKIP_SAYS))
def test_a_gate_with_nothing_to_read_says_it_skipped(name, tmp_path):
    """The gates okl gives other repositories are a no-op where their input is not set up (the
    README's own promise), so they exit 0 there; but they say they skipped, so an empty run never
    reads as a check that passed."""
    repo = _empty_repo(tmp_path, REPO / "gates" / name, "gates")
    p = _run(repo, f"gates/{name}")
    assert p.returncode == 0, (p.returncode, p.stderr[-300:])
    assert GATE_SKIP_SAYS[name] in (p.stdout + p.stderr), (p.stdout + p.stderr)[-300:]


def test_every_gate_is_in_the_sweep():
    """run-gates.sh runs the others; every other gate is listed with what its skip line says."""
    gates = {f.name for f in (REPO / "gates").iterdir() if f.suffix == ".sh"}
    assert gates - {"run-gates.sh"} == set(GATE_SKIP_SAYS)


def test_the_crash_hook_turns_an_uncaught_error_into_exit_2(tmp_path):
    """ci/_ran.py: a check that raised did not run."""
    (tmp_path / "ci").mkdir()
    shutil.copy(REPO / "ci" / "_ran.py", tmp_path / "ci" / "_ran.py")
    (tmp_path / "ci" / "boom.py").write_text(
        'if __name__ == "__main__":\n    import _ran\n    _ran.install()\nraise ValueError("malformed input")\n')
    p = subprocess.run([sys.executable, "ci/boom.py"], cwd=tmp_path, capture_output=True, text=True)
    assert p.returncode == 2 and "could not run" in p.stderr and "ValueError" in p.stderr


def test_a_database_that_cannot_be_opened_is_exit_2_and_not_a_traceback(tmp_path, monkeypatch, capsys):
    """A store okl cannot open ended the command in the driver's traceback and exit 1, which this CLI
    keeps for findings: with a shared database down, a drift gate would have read the outage as drift
    (#125). Any command now exits 2 with one line saying the store could not be opened or read."""
    not_a_db = tmp_path / "store.db"; not_a_db.write_bytes(b"not an SQLite file. " * 60)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{not_a_db}")
    assert main(["search", "login"]) == 2
    said = capsys.readouterr()
    assert said.out == "" and "Traceback" not in said.err
    assert said.err.startswith("OKL: the store could not be opened or read (DatabaseError)") and said.err.count("\n") == 1


def test_a_postgres_server_that_cannot_be_reached_is_exit_2(tmp_path, monkeypatch, capsys):
    """The same for the shared store: a Postgres URL nothing answers on. Which error the driver
    raises is the machine's to say (refused on macOS, a timeout on CI's Linux runner, where the
    first version of this test named the kind and failed), so the kind is not asserted."""
    import socket
    pytest.importorskip("psycopg")
    with socket.socket() as s:                 # a port that was free a moment ago, with nothing listening
        s.bind(("127.0.0.1", 0)); port = s.getsockname()[1]
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("OKL_DATABASE_URL", f"postgresql://okl@127.0.0.1:{port}/okl?connect_timeout=2")
    assert main(["check", "--task", "add a login page"]) == 2
    said = capsys.readouterr()
    assert said.out == "" and "Traceback" not in said.err
    assert said.err.startswith("OKL: the store could not be opened or read (") and said.err.count("\n") == 1


def test_a_database_error_is_reported_in_one_line():
    """A driver's message can run to many lines: psycopg lists every address it tried. The first
    line says what failed, and an error with no message still names its kind."""
    import sqlite3

    from okl.cli import store_error_line
    assert store_error_line(sqlite3.OperationalError("connection failed: refused\n- host: a\n- host: b")) \
        == "OKL: the store could not be opened or read (OperationalError): connection failed: refused"
    assert store_error_line(sqlite3.DatabaseError("")) == "OKL: the store could not be opened or read (DatabaseError): no message"


def test_a_postgres_store_without_its_driver_names_the_extra(tmp_path, monkeypatch, capsys):
    """With OKL_DATABASE_URL naming Postgres and psycopg not installed, `okl record` ended in a
    RuntimeError traceback and exit 1 (#125). It exits 2 and names the extra to install."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setitem(sys.modules, "psycopg", None)      # as on a machine without the extra
    monkeypatch.setenv("OKL_DATABASE_URL", "postgresql://okl@127.0.0.1:1/okl")
    assert main(["record", "--type", "Rule", "--title", "t", "--scope", "org"]) == 2
    said = capsys.readouterr()
    assert said.out == "" and "Traceback" not in said.err
    assert "observed-knowledge-ledger[postgres]" in said.err and said.err.startswith("OKL: ")


def test_the_service_will_not_start_on_a_store_nothing_named(tmp_path, monkeypatch):
    """`okl serve` with no OKL_DATABASE_URL opened ./okl.db in whatever directory it started in: a
    deployment that lost the variable came up healthy, serving and writing a new, empty file (#125,
    the service's half of #117). It now resolves its store as every command does, and refuses when
    nothing names one, before it binds a port."""
    pytest.importorskip("fastapi"); pytest.importorskip("uvicorn")
    from okl import service
    from okl.client import OKLNotConfiguredError
    monkeypatch.chdir(tmp_path)
    with pytest.raises(OKLNotConfiguredError, match="nothing names a store to serve"):
        service.create_app()
    env = {k: v for k, v in os.environ.items() if not k.startswith("OKL_")}
    env["PYTHONPATH"] = str(REPO / "src")
    p = subprocess.run([sys.executable, "-m", "okl", "serve", "--host", "127.0.0.1", "--port", "0"],
                       cwd=tmp_path, env=env, capture_output=True, text=True, timeout=60)
    assert p.returncode == 2 and p.stdout == "" and "nothing names a store to serve" in p.stderr, p.stderr
    assert not (tmp_path / "okl.db").exists(), "it must not invent a store"
    # In a repo set up with okl, it serves that repo's store, as `okl check` reads it.
    (tmp_path / ".okl").mkdir(); (tmp_path / ".okl" / "config.json").write_text('{"repo": "r"}')
    from fastapi.testclient import TestClient
    assert TestClient(service.create_app()).get("/health").json()["backend"] == "sqlite"
    assert (tmp_path / ".okl" / "okl.db").exists() and not (tmp_path / "okl.db").exists()
