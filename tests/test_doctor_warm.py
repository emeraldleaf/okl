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


HOOKS_THAT_LOOK = ("userpromptsubmit-okl-check.sh", "stop-okl-encode.sh", "posttooluse-okl-read.sh",
                   "posttooluse-okl-edit.sh", "okl-mcp.sh")


def _the_hook_picks(hook: str, pin: str | None, folder: Path) -> str:
    """What one hook script's own `try_pinned` and `resolve_okl` pick, run in bash as the hook
    runs them: the functions are cut from the shipped script, and only where the config is found
    is stood in for. The environment is this process's, so the hook and the check look at the
    same OKL_BIN and PATH."""
    text = (Path(warm.__file__).parent / "scaffold" / "hooks" / hook).read_text()
    cut = text[text.index("try_pinned() {"):]
    cut = cut[:cut.index("\n}\n", cut.index("resolve_okl() {")) + 3]
    config = folder / "config.json"
    config.write_text(json.dumps({"okl_bin": pin} if pin else {}))
    # The edit hook has read the config's path into `config` by the time it looks; the others ask okl_config.
    script = (f'okl_config() {{ printf "%s\\n" "$CFG"; }}\nconfig="$CFG"\n{cut}\n'
              'if resolve_okl; then printf "%s" "${OKL[*]}"; fi\n')
    done = subprocess.run([BASH, "-c", script], capture_output=True, text=True, env={**os.environ, "CFG": str(config)})
    assert done.returncode == 0, done.stderr
    return done.stdout


BASH = __import__("shutil").which("bash")


@pytest.mark.skipif(not BASH, reason="the hooks are bash scripts")
@pytest.mark.parametrize("hook", HOOKS_THAT_LOOK)
def test_the_check_names_the_okl_each_hook_script_itself_picks(hook, envs, monkeypatch, tmp_path):
    """The check says which okl the hooks run, so it must pick the one they pick. Each shipped
    hook's own lookup is run here beside the check's, case by case: a `<python> -m okl` whose
    Python cannot import okl is passed over by both, and a command whose first line names no
    Python is taken by both. Before this, the check took the first and passed over the second."""
    import shutil
    has, _lacks, folder = envs
    no_okl = folder / "python-no-okl"
    no_okl.write_text('#!/bin/sh\ncase "$2" in *okl*) exit 3 ;; *) exit 0 ;; esac\n')
    no_okl.chmod(0o755)
    unreadable = folder / "okl-launcher"
    unreadable.write_bytes(b"\x7fELF\x02\x01\x01")
    unreadable.chmod(0o755)
    good = _okl_script(folder, "okl-good", f"#!{has}\n")
    bare, with_okl = tmp_path / "bare", tmp_path / "with-okl"
    for path in (bare, with_okl):
        path.mkdir()
        (path / "python3").write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n')
        (path / "python3").chmod(0o755)
    on_path = _okl_script(with_okl, "okl", f"#!{has}\n")

    def same(okl_bin: str | None, pin: str | None, path: Path) -> str:
        monkeypatch.setenv("PATH", str(path))
        monkeypatch.delenv("OKL_BIN", raising=False)
        if okl_bin:
            monkeypatch.setenv("OKL_BIN", okl_bin)
        picked = _the_hook_picks(hook, pin, tmp_path)
        # The hook names the last two places by command; the check names the file each is.
        named = {"okl": shutil.which("okl"), "python3 -m okl": f"{shutil.which('python3')} -m okl"}.get(picked, picked)
        assert warm.hooks_okl(pin) == named, (okl_bin, pin, path.name, picked)
        return picked

    assert same(f"{no_okl} -m okl", good, bare) == good, "an OKL_BIN whose Python lost okl: the pin"
    assert same(None, f"{no_okl} -m okl", with_okl) == "okl", "a pin whose Python lost okl: PATH"
    assert same(None, str(unreadable), with_okl) == str(unreadable), "a pin the hooks run, whatever its first line"
    assert same(f"{has} -m okl", good, with_okl) == f"{has} -m okl"
    assert same(None, good, with_okl) == good
    assert same(None, "/no/such/okl", with_okl) == "okl"
    same(None, None, bare)      # the last place, or none: whichever this machine gives, the two agree
    # The hooks take a command that is there and go on when it cannot start (#152): its Python gone.
    dead = _okl_script(folder, "okl-dead", "#!/no/such/python\n")
    monkeypatch.setenv("PATH", str(with_okl))
    assert warm.hooks_okl(dead) == on_path
    assert warm.installed_for(str(unreadable)) is None, "and what that okl can load cannot be told"


def test_the_docs_the_hooks_and_the_check_name_one_lookup_order():
    """docs/COSTS-AND-KNOBS.md and the changelog say where the okl the hooks run is looked for,
    in order. That order is the prompt hook's own (`resolve_okl`: its four layers), and the check
    follows it (the test above). Read from the hook script here, so a hook that changes its order
    fails this until the check and both sentences change with it."""
    import re
    repo = Path(__file__).resolve().parents[1]
    hook = (repo / "src" / "okl" / "scaffold" / "hooks" / "userpromptsubmit-okl-check.sh").read_text()
    body = hook[hook.index("resolve_okl() {"):]
    body = body[:body.index("\n}\n")]
    layers = [m.start() for m in (re.search(pattern, body) for pattern in (
        r'-le 1 \]\] && \[\[ -n "\$\{OKL_BIN:-\}"', r"-le 2 \]\] && cfg=\$\(okl_config\)",
        r"-le 3 \]\] && command -v okl", r'-le 4 \]\] && python3 -c "import okl"')) if m]
    assert len(layers) == 4 and layers == sorted(layers), "the hook no longer looks in OKL_BIN, the pin, PATH, python3 -m okl"
    said = "`OKL_BIN`, the pinned okl, `okl` on PATH, then `python3 -m okl`"
    for doc in ("docs/COSTS-AND-KNOBS.md", "CHANGELOG.md"):
        assert said in " ".join((repo / doc).read_text().split()), f"{doc} no longer states the order"


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
