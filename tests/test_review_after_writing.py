"""The review after writing: `okl check --change` (REPORT §4at).

After the agent writes a change, okl lists the files it touched, committed or not, and every
lesson in scope one line each, with the steps: explain the change, pick the lessons it most
likely breaks, read and check each, fix. okl calls no model. The Stop hook asks for it only
where the repo turns it on.
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from okl import changes, core
from okl.cli import main
from okl.client import Client
from okl.store import Node

GIT = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false"]


def _git(r: Path, *a: str) -> str:
    return subprocess.run(["git", "-C", str(r), *GIT, *a], capture_output=True, text=True, check=True).stdout


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """main with one file; a branch `work` that commits one change, then edits another file
    and adds an untracked one without committing."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "r"; r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / "app.py").write_text("print('hi')\n"); (r / "notes.md").write_text("notes\n")
    (r / ".gitignore").write_text(".okl/\n")
    _git(r, "add", "-A"); _git(r, "commit", "-qm", "base")
    _git(r, "switch", "-qc", "work")
    (r / "committed.py").write_text("x = 1\n"); _git(r, "add", "-A"); _git(r, "commit", "-qm", "work")
    (r / "notes.md").write_text("notes, edited\n")      # tracked, not committed
    (r / "untracked.py").write_text("y = 2\n")          # never added
    (r / ".okl").mkdir(); (r / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.chdir(r)
    return r


def test_touched_lists_committed_uncommitted_and_untracked_work(repo):
    """The agent's work in progress counts: it often has not committed when the review runs."""
    base, files = changes.touched(None)
    assert files == ["committed.py", "notes.md", "untracked.py"]
    assert base == _git(repo, "rev-parse", "main").strip()


def test_touched_without_a_branch_to_compare_names_the_flag(tmp_path, monkeypatch):
    """No remote default branch, main or master: say how to name one, in this command's words."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "solo"; r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(r)], check=True)
    (r / "a.py").write_text("a\n"); _git(r, "add", "-A"); _git(r, "commit", "-qm", "a")
    monkeypatch.chdir(r)
    with pytest.raises(changes.ChangesError, match="okl check --change main"):
        changes.touched(None)
    assert changes.touched("trunk")[1] == []


def test_a_base_that_looks_like_an_option_never_reaches_git(repo, capsys):
    """git reads `--output=<file>` as an option and writes the file; a ref never starts with '-'."""
    target = repo.parent / "written-by-git"
    with pytest.raises(changes.ChangesError, match="cannot start with '-'"):
        changes.touched(f"--output={target}")
    assert main(["check", f"--change=--output={target}"]) == 2
    assert capsys.readouterr().out == "" and not target.exists()


def _n(id, **kw):
    return Node(id=id, type=kw.pop("type", "Rule"), title=f"title {id}", fix=kw.pop("fix", f"do {id}. Then more."),
                scope=kw.pop("scope", "org"), **kw)


def test_the_list_is_every_live_lesson_in_scope_in_id_order():
    """In id order, which says nothing about relevance; no vocabulary, nothing retired, nothing
    another repo owns, nothing whose applies_to excludes this repo's interests."""
    nodes = [_n("z-own", scope="repo:r"), _n("b-org"), _n("a-other", scope="repo:other"),
             _n("c-vocab", type="Vocabulary"), _n("d-retired", status="obsolete"),
             _n("d-replaced", status="superseded"), _n("e-dotnet", applies_to="dotnet")]
    menu = core.review_menu(nodes, "r", ["python"])
    assert [e["id"] for e in menu] == ["b-org", "z-own"]
    assert menu[0]["fix"] == "do b-org."   # the first sentence of the fix, as the second tier cuts it
    assert [e["id"] for e in core.review_menu(nodes, "r", None)] == ["b-org", "e-dotnet", "z-own"]


def test_a_retracted_lesson_stays_in_the_list_as_what_to_avoid():
    """The set a briefing can show (report-commands-use-briefable-set): a change can restate a
    withdrawn claim, so the review must still name it, as something to avoid."""
    menu = core.review_menu([_n("f-withdrawn", status="retracted")], "r", None)
    assert menu[0]["avoid"] == "retracted"
    assert "- [f-withdrawn] AVOID (retracted): title f-withdrawn" in core.render_review(
        {"repo": "r", "files": ["a.py"], "lessons": menu})


def test_the_rendering_carries_the_steps_the_files_and_each_lesson():
    """The steps, the merge base, the files (cut at thirty) and each lesson's line."""
    text = core.render_review({"repo": "r", "base": None, "merge_base": "abc1234def", "files": ["a.py", "b.py"],
                               "lessons": core.review_menu([_n("b-org")], "r", None)})
    assert "2 file(s) changed since the default branch (merge base abc1234)" in text
    assert all(step in text for step in core.REVIEW_STEPS)
    assert "Changed: a.py, b.py" in text
    assert "- [b-org] title b-org" in text and "— do b-org." in text
    many = core.render_review({"repo": "r", "files": [f"f{i}.py" for i in range(35)], "lessons": []})
    assert "and 5 more" in many and "nothing to check against" in many
    assert "nothing to review" in core.render_review({"repo": "r", "base": "main", "files": [], "lessons": []})


def _store(repo, *nodes):
    """Lessons in the repo's own store, as `okl init` would place it."""
    s = Client()._local_store()
    for n in nodes:
        s.add_node(n)


def test_check_change_prints_the_review(repo, capsys):
    """The review lists this change's files and the lessons this repo may see, in text and JSON."""
    _store(repo, _n("b-org"), _n("z-own", scope="repo:r"), _n("a-other", scope="repo:other"))
    assert main(["check", "--change"]) == 0
    out = capsys.readouterr().out
    assert "3 file(s) changed" in out and "committed.py, notes.md, untracked.py" in out
    assert "[b-org]" in out and "[z-own]" in out and "[a-other]" not in out
    assert main(["check", "--change", "main", "--format", "json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["files"] == ["committed.py", "notes.md", "untracked.py"] and got["base"] == "main"
    assert [e["id"] for e in got["lessons"]] == ["b-org", "z-own"]


def test_check_change_refuses_with_exit_2_and_nothing_on_stdout(repo, capsys, monkeypatch):
    """Exit codes are this CLI's API: a range git cannot read is refused, never an empty review."""
    assert main(["check", "--change", "no-such-ref"]) == 2
    got = capsys.readouterr()
    assert got.out == "" and "okl check --change:" in got.err
    monkeypatch.chdir(repo.parent)   # no config here or above
    assert main(["check", "--change"]) == 2
    got = capsys.readouterr()
    assert got.out == "" and "NOT CONFIGURED" in got.err


def test_the_hook_note_follows_the_setting(repo, capsys, monkeypatch):
    """Off unless the config turns it on; the environment overrides the config either way."""
    monkeypatch.delenv("OKL_REVIEW_AFTER_WRITING", raising=False)
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out == ""
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "review_after_writing": True}))
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out.strip() == core.REVIEW_NOTE
    monkeypatch.setenv("OKL_REVIEW_AFTER_WRITING", "0")
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out == ""
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.setenv("OKL_REVIEW_AFTER_WRITING", "1")
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out.strip() == core.REVIEW_NOTE


def test_a_setting_okl_cannot_read_is_refused_not_ignored(repo, capsys, monkeypatch):
    """A mistyped value that left the review off would look exactly like off."""
    from okl.client import review_setting
    assert review_setting(None, "on") is True and review_setting("0", True) is False and review_setting("", None) is False
    with pytest.raises(ValueError, match="must be on or off"):
        review_setting(None, "ture")
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "review_after_writing": "ture"}))
    assert main(["check", "--change", "--format", "hook"]) == 2
    got = capsys.readouterr()
    assert got.out == "" and "review_after_writing must be on or off" in got.err


def test_init_says_when_the_stop_hook_on_disk_cannot_ask_for_the_review(tmp_path, monkeypatch, capsys):
    """An edited Stop hook from before the review is kept by init, so turning the review on
    there would do nothing (owned-file-features-check-the-kept-copy): init says so."""
    from okl.cli import install
    monkeypatch.chdir(tmp_path)
    hooks = tmp_path / ".claude" / "hooks"; hooks.mkdir(parents=True)
    install._say_review_after_writing({"review_after_writing": False})
    assert capsys.readouterr().out == ""
    (hooks / "stop-okl-encode.sh").write_text("# okl check --change appears only in a comment\nexit 2\n")
    install._say_review_after_writing({"review_after_writing": True})
    out = capsys.readouterr().out
    assert "review after writing: on" in out and "okl init --force" in out
    shipped = Path(install.__file__).resolve().parents[1] / "scaffold" / "hooks" / "stop-okl-encode.sh"
    shutil.copy(shipped, hooks / "stop-okl-encode.sh")
    install._say_review_after_writing({"review_after_writing": True})
    assert "--force" not in capsys.readouterr().out


def test_the_hook_note_is_silent_when_nothing_changed(repo, capsys, monkeypatch):
    """Turned on, but with nothing changed since the default branch, the Stop hook gets no note."""
    monkeypatch.setenv("OKL_REVIEW_AFTER_WRITING", "1")
    _git(repo, "add", "-A"); _git(repo, "commit", "-qm", "all")
    _git(repo, "switch", "-q", "main"); _git(repo, "merge", "-q", "--ff-only", "work")
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out == ""


def test_the_stop_hook_asks_for_the_review_only_where_it_is_on(repo, tmp_path):
    """The note comes before the encode question, and an unset repo sees the question alone."""
    hook = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "hooks" / "stop-okl-encode.sh"
    markers = tmp_path / "markers"; markers.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(markers),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "OKL_BIN": f"{sys.executable} -m okl",
           "CLAUDE_PROJECT_DIR": str(repo)}

    def stop(session):
        return subprocess.run(["bash", str(hook)], cwd=repo, text=True, capture_output=True, env=env,
                              input=json.dumps({"session_id": session, "stop_hook_active": False}))

    r = stop("off")
    assert r.returncode == 2 and "ENCODING LOOP" in r.stderr and "REVIEW AFTER WRITING" not in r.stderr
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "review_after_writing": True}))
    r = stop("on")
    assert r.returncode == 2 and "okl check --change" in r.stderr
    assert r.stderr.index("REVIEW AFTER WRITING") < r.stderr.index("ENCODING LOOP")
    # An okl older than --change refuses it (hook-cli-version-skew): the question stands as it
    # was, and the refusal never reaches the agent.
    stub = tmp_path / "old-okl"
    stub.write_text("#!/bin/sh\necho 'okl: error: unrecognized arguments: --change' >&2\nexit 2\n")
    stub.chmod(0o755)
    env["OKL_BIN"] = str(stub)
    r = stop("old")
    assert r.returncode == 2 and "ENCODING LOOP" in r.stderr
    assert "REVIEW AFTER WRITING" not in r.stderr and "unrecognized" not in r.stderr
