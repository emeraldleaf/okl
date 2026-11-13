"""okl never writes or deletes through a symlink, at every place it could (CWE-59, #50).

okl writes into repositories it did not create, and a cloned repo can hold a symlink where okl
writes: following it would write okl's file wherever the link points. install.py guards each of
those places, and `ci/check-guard-mutations.py` switches each guard off in turn: these tests are
the ones it expects to fail, one or more per guard, and they come first so that run stays fast.
Each plants a link to a file outside the repo and checks that okl says it refused or kept it,
and that the file outside keeps every byte.
"""
import json
import subprocess
from pathlib import Path

import pytest

from okl.cli import install

HOOK = install.Path(install.__file__).parent.parent / "scaffold" / "hooks" / "stop-okl-encode.sh"


@pytest.fixture
def repo(tmp_path, monkeypatch, capsys):
    """An empty git repo as cwd with its own home; `okl(*args)` runs in-process: (exit, output).
    `outside(name, text)` writes a file outside the repo and returns it."""
    from okl.cli import main
    root = tmp_path / "r"; root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    monkeypatch.chdir(root)
    monkeypatch.setenv("HOME", str(tmp_path)); monkeypatch.setenv("USERPROFILE", str(tmp_path))
    away = tmp_path / "outside"; away.mkdir()

    def okl(*args):
        code = main(list(args))
        return code, capsys.readouterr().out

    def outside(name, text):
        f = away / name; f.write_text(text)
        return f

    def link(path, target):
        p = root / path; p.parent.mkdir(parents=True, exist_ok=True); p.symlink_to(target)
        return p
    return root, okl, outside, link


def test_settings_json_is_not_written_through_a_link(repo):
    """_merge_hook_settings refuses .claude/settings.json as a link (and _refuse_symlink's own check)."""
    root, okl, outside, link = repo
    target = outside("settings.json", "{}\n")
    link(".claude/settings.json", target)

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude")

    assert "! refused .claude/settings.json" in out, out
    assert target.read_text() == "{}\n"


def test_a_hook_script_is_not_written_through_a_link(repo):
    """_place_owned refuses a hook script that is a link."""
    root, okl, outside, link = repo
    target = outside("planted.sh", "#!/bin/sh\necho mine\n")
    link(".claude/hooks/stop-okl-encode.sh", target)

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude")

    assert "! refused .claude/hooks/stop-okl-encode.sh" in out, out
    assert target.read_text() == "#!/bin/sh\necho mine\n"


def test_a_linked_claude_dir_is_not_wired(repo):
    """_wire_claude_code refuses a .claude that is a link, and the dry run says so."""
    root, okl, outside, link = repo
    elsewhere = outside("ignored", "x").parent / "claude-dir"; elsewhere.mkdir()
    link(".claude", elsewhere)

    _, dry = okl("init", "--repo", "r", "--claude", "--dry-run")
    code, out = okl("init", "--repo", "r", "--no-seed", "--claude")

    assert "is a symlink, which init refuses to write through" in dry, dry
    assert "! refused .claude" in out, out
    assert list(elsewhere.iterdir()) == []


def test_mcp_json_is_not_written_through_a_link(repo):
    """_install_claude_wiring refuses .mcp.json as a link (only reached with the [mcp] extra)."""
    pytest.importorskip("mcp")
    root, okl, outside, link = repo
    target = outside("mcp.json", "{}\n")
    link(".mcp.json", target)

    code, out = okl("init", "--repo", "r", "--no-seed", "--claude")

    assert "! refused .mcp.json" in out, out
    assert target.read_text() == "{}\n"


def test_the_ci_pin_is_not_written_through_a_link(repo, monkeypatch):
    """_pin_okl_version refuses .github/okl-version as a link."""
    root, okl, outside, link = repo
    monkeypatch.setattr(install, "_pinnable_version", lambda: "0.11.0")
    target = outside("okl-version", "0.10.0\n")
    link(".github/okl-version", target)

    code, out = okl("init", "--repo", "r", "--no-seed", "--no-claude", "--ci")

    assert "! refused .github/okl-version" in out, out
    assert target.read_text() == "0.10.0\n"


def test_a_linked_workflow_gets_no_pin_in_the_run_or_the_dry_run(repo, monkeypatch):
    """_install_ci_verifier and _dry_run_pin: a workflow path that links to okl's own workflow is
    still not okl's to pin beside."""
    root, okl, outside, link = repo
    monkeypatch.setattr(install, "_pinnable_version", lambda: "0.11.0")
    link(".github/workflows/okl-verify.yml", outside("okl-verify.yml", install.WORKFLOW_SRC.read_text()))

    _, dry = okl("init", "--repo", "r", "--no-claude", "--ci", "--dry-run")
    code, out = okl("init", "--repo", "r", "--no-seed", "--no-claude", "--ci")

    assert "(no CI pin: .github/workflows/okl-verify.yml is not okl's workflow, and is kept)" in dry, dry
    assert "no CI pin written" in out and not (root / ".github" / "okl-version").exists(), out


def test_the_pre_push_hook_is_not_written_through_a_link(repo):
    """_install_git_hook leaves a linked pre-push hook to the refusal, not the 'another hook' note."""
    root, okl, outside, link = repo
    target = outside("pre-push", "#!/bin/sh\nexit 0\n")
    link(".git/hooks/pre-push", target)

    code, out = okl("init", "--repo", "r", "--no-seed", "--no-claude", "--git-hook")

    assert "! refused .git/hooks/pre-push" in out, out
    assert target.read_text() == "#!/bin/sh\nexit 0\n"


def test_uninstall_keeps_a_linked_hook_script(repo):
    """_uninstall_files keeps a link even to okl's own hook: deleting it is not okl's call."""
    root, okl, outside, link = repo
    hook = link(".claude/hooks/stop-okl-encode.sh", outside("hook.sh", HOOK.read_text()))

    code, out = okl("init", "--uninstall")

    assert hook.is_symlink() and "a symlink, or under one" in out, out


def test_uninstall_keeps_a_linked_ci_pin(repo, monkeypatch):
    """_uninstall_pin leaves a linked .github/okl-version, even beside okl's workflow."""
    root, okl, outside, link = repo
    monkeypatch.setattr(install, "_pinnable_version", lambda: None)
    assert okl("init", "--repo", "r", "--no-seed", "--no-claude", "--ci")[0] == 0
    pin = link(".github/okl-version", outside("okl-version", "0.11.0\n"))

    code, out = okl("init", "--uninstall")

    assert not (root / ".github" / "workflows" / "okl-verify.yml").exists(), out
    assert pin.is_symlink() and pin.read_text() == "0.11.0\n"


def test_uninstall_leaves_linked_settings_and_mcp_json_alone(repo):
    """_uninstall_hook_registrations and _uninstall_mcp do not rewrite a file through a link."""
    root, okl, outside, link = repo
    groups: dict[str, list] = {}
    for event, _matcher, command, _timeout in install.HOOKS:
        groups.setdefault(event, []).append({"hooks": [{"type": "command", "command": command}]})
    settings = json.dumps({"hooks": groups}) + "\n"
    mcp = json.dumps({"mcpServers": {"okl": install.MCP_ENTRY}}) + "\n"
    s = outside("settings.json", settings); m = outside("mcp.json", mcp)
    link(".claude/settings.json", s); link(".mcp.json", m)

    code, out = okl("init", "--uninstall")

    assert "okl's hook entries not removed" in out and "the okl server entry not removed" in out, out
    assert (s.read_text(), m.read_text()) == (settings, mcp)
    assert Path(root / ".mcp.json").is_symlink()


def test_the_mutation_check_finds_every_guard_call_and_switches_off_only_that_one():
    """ci/check-guard-mutations.py reads the guard calls from the code: if it found none, it would
    pass by checking nothing. Each stand-in replaces exactly its own call."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_guard_mutations",
                                                  Path(__file__).resolve().parents[1] / "ci" / "check-guard-mutations.py")
    check = importlib.util.module_from_spec(spec); spec.loader.exec_module(check)
    path, guards = next(iter(check.GUARD_CALLS.items()))
    source = (Path(__file__).resolve().parents[1] / path).read_text()

    sites = check.call_sites(path, guards)

    assert len(sites) >= 14, sites
    for site in sites:
        mutated = check.replace_span(source, site)
        assert mutated.count(site[4]) == source.count(site[4]) - 1
        assert len(mutated) == len(source) - len(site[4]) + len(site[5])
