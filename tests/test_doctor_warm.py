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
    """A stand-in for another environment's Python. It answers the question the check asks, whether
    it can find a module, the way a real one does (exit 0, or the probe's own 3): every module is
    there but fastembed, which is there only with the extra."""
    path = folder / name
    path.write_text(f'#!/bin/sh\ncase "$2" in *fastembed*) exit {0 if has_the_extra else 3} ;; *) exit 0 ;; esac\n')
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
    monkeypatch.delenv("OKL_BIN", raising=False)
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


def test_the_fault_is_the_model_turned_on_where_the_pinned_okl_cannot_load_it(envs, monkeypatch, tmp_path):
    """A fault only when the repo turned the model on and its pinned okl lacks the extra. Left to
    its default, or turned off, nothing is said; an okl that can load it says nothing; one that
    cannot be asked gets a line and no fault. A setting that is neither on nor off raises, for the
    command line to report as it does for every command that reads it."""
    has, lacks, _ = envs
    line, fault = warm_gap({"warm": True, "okl_bin": f"{lacks} -m okl"}, None)
    assert fault and "cannot load it" in line and str(lacks) in line and "observed-knowledge-ledger[warm]" in line, line
    assert warm_gap({"warm": True, "okl_bin": f"{has} -m okl"}, None) == ("", False)
    assert warm_gap({"okl_bin": f"{lacks} -m okl"}, None) == ("", False), "the default uses the model only where it loads"
    assert warm_gap({"warm": False, "okl_bin": f"{lacks} -m okl"}, None) == ("", False)
    assert warm_gap({"warm": True, "okl_bin": f"{lacks} -m okl"}, "off") == ("", False), "OKL_WARM wins over the config"
    assert warm_gap({"okl_bin": f"{lacks} -m okl"}, "on")[1] is True
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    monkeypatch.setattr(warm, "installed", lambda: False)
    nowhere, fault = warm_gap({"warm": True, "okl_bin": "/no/such/okl"}, None)
    assert fault and "this okl cannot load it" in nowhere, "no okl where the hooks look: the running one is asked"
    # An okl that answers one question and not the next cannot be said to lack the extra: a line, and no fault.
    monkeypatch.setattr(warm, "installed_for", lambda _okl: None)
    unknown, fault = warm_gap({"warm": True, "okl_bin": f"{has} -m okl"}, None)
    assert not fault and "could not tell" in unknown and str(has) in unknown, unknown
    with pytest.raises(ValueError, match="warm must be on or off"):
        warm_gap({"warm": "onn"}, None)


def test_the_okl_asked_is_the_one_the_hooks_run_in_the_order_they_look(envs, monkeypatch, tmp_path):
    """Each hook looks for okl in OKL_BIN, then the config's pin, then `okl` on PATH, then
    `python3 -m okl`, and runs the first that answers. The check asks that same okl: a pin with the
    extra says nothing of a session whose OKL_BIN names an okl without it, and a repo with no pin,
    or a pin that is gone, runs the okl on PATH."""
    has, lacks, folder = envs
    pin_has, pin_lacks = f"{has} -m okl", f"{lacks} -m okl"
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    assert warm.hooks_okl(pin_has) == pin_has
    monkeypatch.setenv("OKL_BIN", pin_lacks)
    assert warm.hooks_okl(pin_has) == pin_lacks
    line, fault = warm_gap({"warm": True, "okl_bin": pin_has}, None)
    assert fault and str(lacks) in line, "OKL_BIN names the okl the hooks run, whatever the pin can load"
    monkeypatch.delenv("OKL_BIN")
    on_path = tmp_path / "bin"
    on_path.mkdir()
    script = _okl_script(on_path, "okl", f"#!{lacks}\n")
    monkeypatch.setenv("PATH", str(on_path))
    assert warm.hooks_okl(None) == script and warm.hooks_okl("/no/such/okl") == script
    assert warm_gap({"warm": True}, None)[1] is True, "no pin: the okl on PATH is asked"
    assert warm.hooks_okl(pin_has) == pin_has, "a pin that answers comes before PATH"
    # A pin, or OKL_BIN, that is a bare command name is found on PATH, as the hooks find it.
    assert warm.hooks_okl("okl") == "okl" and warm.installed_for("okl") is False
    monkeypatch.setenv("OKL_BIN", "okl")
    assert warm.hooks_okl(pin_has) == "okl"


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


def test_a_model_stopped_on_purpose_is_said_and_is_no_fault(envs, monkeypatch):
    """`okl warm stop` keeps the model off until someone starts it again. In a repo that turned the
    model on, that is the person's own choice, so it is said with how to resume and counts as no fault."""
    from okl import client
    has, _, _ = envs
    monkeypatch.setattr(client.warm, "stopped", lambda: True)
    line, fault = warm_gap({"warm": True, "okl_bin": f"{has} -m okl"}, None)
    assert not fault and "stopped with `okl warm stop`" in line and "okl warm start" in line, line
    monkeypatch.setattr(client.warm, "stopped", lambda: False)
    assert warm_gap({"warm": True, "okl_bin": f"{has} -m okl"}, None) == ("", False)


def _doctor(proj: Path, home: Path) -> subprocess.CompletedProcess:
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONPATH": str(Path(warm.__file__).parents[1]),
           "OKL_WARM_SOCKET": str(home / "no-server.sock")}
    for name in ("CLAUDE_CONFIG_DIR", "OKL_WARM", "OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_BIN"):
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
    # A setting that is neither on nor off is refused as every command refuses it: exit 2, on stderr.
    config.write_text(json.dumps({"repo": "proj", "warm": "onn", "okl_bin": f"{has} -m okl"}))
    refused = _doctor(proj, home)
    assert refused.returncode == 2 and "warm must be on or off" in refused.stderr, refused.stdout + refused.stderr


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
    # A setting that is neither on nor off: init refused it only at its end before this check, after
    # its own steps, and still does. The check must not stop it earlier, with the config written and
    # the rest of init not done.
    (proj / ".okl" / "config.json").write_text(json.dumps({"repo": "proj", "warm": "onn"}))
    main(["init", "--repo", "proj", "--no-seed", "--no-claude", "--no-ci", "--no-git-hook"])
    assert "review after writing" in capsys.readouterr().out, "init went on past the warm check"
