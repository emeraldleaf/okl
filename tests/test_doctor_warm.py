"""`okl doctor` and `okl init` say when a repo turned the warm model on and the okl its hooks run
cannot load it (#522).

On okl's own repo the config pinned a released okl installed without the warm extra. Every
briefing fell back to word search for six days, and the only sign was the end of a status line
under each prompt: `okl doctor` had no check for it. The pack lesson measured_default_not_running
says what was missing: a health check that fails when what runs differs from what is configured.
The okl that runs `doctor` is not always the one the hooks run, so the check asks the pinned one.
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from okl import warm
from okl.client import warm_gap


def _fake_python(folder: Path, name: str, has_the_extra: bool) -> Path:
    """A stand-in for another environment's Python: it answers the one question asked of it,
    whether it can find fastembed, the way a real one does (exit 0, or the probe's own 3)."""
    path = folder / name
    path.write_text(f"#!/bin/sh\nexit {0 if has_the_extra else 3}\n")
    path.chmod(0o755)
    return path


def _okl_script(folder: Path, name: str, first_lines: str) -> str:
    path = folder / name
    path.write_text(first_lines + "import sys\n")
    path.chmod(0o755)
    return str(path)


@pytest.fixture
def envs(tmp_path, monkeypatch):
    """Two environments' Pythons, one with the warm extra and one without, and a folder for scripts.
    No warm server answers and no shared service is named: a developer's own running server, or a
    service URL in their shell, would otherwise decide these tests."""
    monkeypatch.setenv("OKL_WARM_SOCKET", str(tmp_path / "no-server.sock"))
    monkeypatch.delenv("OKL_SERVICE_URL", raising=False)
    return _fake_python(tmp_path, "python-with", True), _fake_python(tmp_path, "python-without", False), tmp_path


def test_the_pinned_okl_is_asked_through_its_own_interpreter(envs):
    """Each way an okl command names its Python is followed: a console script's first line, the
    two-line form an installer writes for a long path or one with a space (pip in double quotes, or
    bare; uv in single quotes), and `<python> -m okl`. The answer is that environment's, not the
    running one's."""
    has, lacks, folder = envs
    assert warm.installed_for(_okl_script(folder, "okl-a", f"#!{has}\n")) is True
    assert warm.installed_for(_okl_script(folder, "okl-b", f"#!{lacks}\n")) is False
    spaced = folder / "a folder"
    spaced.mkdir()
    there = _fake_python(spaced, "python", False)
    assert warm.installed_for(_okl_script(folder, "okl-c", f"#!/bin/sh\n'''exec' \"{there}\" \"$0\" \"$@\"\n' '''\n")) is False
    assert warm.installed_for(_okl_script(folder, "okl-f", f"#!/bin/sh\n'''exec' '{there}' \"$0\" \"$@\"\n' '''\n")) is False
    assert warm.installed_for(_okl_script(folder, "okl-g", f"#!/bin/sh\n'''exec' {lacks} \"$0\" \"$@\"\n' '''\n")) is False
    assert warm.installed_for(_okl_script(folder, "okl-h", f"#!/bin/sh\n'''exec' {has} \"$0\" \"$@\"\n' '''\n")) is True
    assert warm.installed_for(f"{has} -m okl") is True and warm.installed_for(f"{lacks} -m okl") is False


def test_what_cannot_be_asked_is_not_answered(envs, tmp_path):
    """A pin that is not there, a file with no interpreter line, an interpreter that is gone, and
    one that fails some other way all give None: neither "it can" nor "it cannot"."""
    _, _, folder = envs
    broken = tmp_path / "python-broken"
    broken.write_text("#!/bin/sh\nexit 1\n")
    broken.chmod(0o755)
    for pinned in (str(tmp_path / "no-such-okl"), _okl_script(folder, "okl-d", "print('no first line')\n"),
                   _okl_script(folder, "okl-e", f"#!{tmp_path / 'gone'}\n"), f"{broken} -m okl", " -m okl"):
        assert warm.installed_for(pinned) is None, pinned


def test_the_fault_is_the_model_turned_on_where_the_pinned_okl_cannot_load_it(envs):
    """A fault only when the repo turned the model on and its pinned okl lacks the extra. Left to
    its default, or turned off, nothing is said; an okl that can load it says nothing; one that
    cannot be asked gets a line and no fault; a setting that is neither on nor off is a fault."""
    has, lacks, _ = envs
    line, fault = warm_gap({"warm": True, "okl_bin": f"{lacks} -m okl"}, None)
    assert fault and "cannot load it" in line and str(lacks) in line and "observed-knowledge-ledger[warm]" in line, line
    assert warm_gap({"warm": True, "okl_bin": f"{has} -m okl"}, None) == ("", False)
    assert warm_gap({"okl_bin": f"{lacks} -m okl"}, None) == ("", False), "the default uses the model only where it loads"
    assert warm_gap({"warm": False, "okl_bin": f"{lacks} -m okl"}, None) == ("", False)
    assert warm_gap({"warm": True, "okl_bin": f"{lacks} -m okl"}, "off") == ("", False), "OKL_WARM wins over the config"
    assert warm_gap({"okl_bin": f"{lacks} -m okl"}, "on")[1] is True
    unknown, fault = warm_gap({"warm": True, "okl_bin": "/no/such/okl"}, None)
    assert not fault and "could not tell" in unknown, unknown
    mistyped, fault = warm_gap({"warm": "onn"}, None)
    assert fault and "warm must be on or off" in mistyped, mistyped


def test_a_repo_a_shared_service_briefs_is_not_asked_about_the_local_model(envs, monkeypatch):
    """With a service named in the config or the environment, the service makes the briefing and the
    local model is never asked: a missing extra on this machine is no fault there."""
    _, lacks, _ = envs
    wants = {"warm": True, "okl_bin": f"{lacks} -m okl"}
    assert warm_gap(wants, None)[1] is True, "the control: a fault with no service"
    assert warm_gap({**wants, "service_url": "https://okl.example.invalid"}, None) == ("", False)
    monkeypatch.setenv("OKL_SERVICE_URL", "https://okl.example.invalid")
    assert warm_gap(wants, None) == ("", False)


def test_a_server_that_answers_is_the_model_working_and_is_said_as_one_that_can_stop(envs, monkeypatch):
    """One warm server serves the whole user account, so a server another okl started answers the
    pinned one too. That is no fault, but the pinned okl cannot start it again: said, with exit 0."""
    from okl import client
    _, lacks, _ = envs
    monkeypatch.setattr(client.warm, "ping", lambda _timeout=0: {"model": "m", "pid": 1, "loaded_s": 1})
    line, fault = warm_gap({"warm": True, "okl_bin": f"{lacks} -m okl"}, None)
    assert not fault and "a server is answering" in line and "cannot start one" in line and str(lacks) in line, line


def _doctor(proj: Path, home: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONPATH": str(Path(warm.__file__).parents[1]),
           "OKL_WARM_SOCKET": str(home / "no-server.sock")}
    for name in ("CLAUDE_CONFIG_DIR", "OKL_WARM", "OKL_DATABASE_URL", "OKL_SERVICE_URL"):
        env.pop(name, None)
    return subprocess.run([sys.executable, "-m", "okl", "doctor"], capture_output=True, text=True, cwd=proj, env=env)


def test_doctor_exits_1_and_says_so_when_the_hooks_okl_cannot_load_the_model(envs, tmp_path):
    """The whole command, in a repo of its own: exit 1 with the line while the pinned okl lacks the
    extra, and exit 0 with no word of it once the pin can load the model."""
    has, lacks, _ = envs
    proj, home = tmp_path / "proj", tmp_path / "home"
    (proj / ".okl").mkdir(parents=True)
    home.mkdir()
    config = proj / ".okl" / "config.json"
    config.write_text(json.dumps({"repo": "proj", "warm": True, "okl_bin": f"{lacks} -m okl"}))
    off = _doctor(proj, home)
    assert off.returncode == 1 and "the warm model is on here" in off.stdout and "cannot load it" in off.stdout, off.stdout + off.stderr
    config.write_text(json.dumps({"repo": "proj", "warm": True, "okl_bin": f"{has} -m okl"}))
    on = _doctor(proj, home)
    assert on.returncode == 0 and "warm model" not in on.stdout, on.stdout + on.stderr


def test_init_says_it_when_it_pins_an_okl_that_cannot_load_the_model(tmp_path, monkeypatch, capsys):
    """Re-running init is how the pin moved on okl's own repo. Where the config already turns the
    model on, init names the gap as it writes the pin; with the model left to its default it does not."""
    from okl import client
    from okl.cli import main

    proj = tmp_path / "proj"
    (proj / ".okl").mkdir(parents=True)
    subprocess.run(["git", "init", "-q", str(proj)], check=True)
    monkeypatch.chdir(proj)
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in ("OKL_WARM", "OKL_DATABASE_URL", "OKL_SERVICE_URL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("OKL_WARM_SOCKET", str(tmp_path / "no-server.sock"))
    monkeypatch.setattr(client.warm, "installed_for", lambda _pinned: False)
    (proj / ".okl" / "config.json").write_text(json.dumps({"repo": "proj", "warm": True}))
    main(["init", "--repo", "proj", "--no-seed", "--no-claude", "--no-ci", "--no-git-hook"])
    assert "the warm model is on here" in capsys.readouterr().out
    (proj / ".okl" / "config.json").write_text(json.dumps({"repo": "proj"}))
    main(["init", "--repo", "proj", "--no-seed", "--no-claude", "--no-ci", "--no-git-hook"])
    assert "warm model" not in capsys.readouterr().out
