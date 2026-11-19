"""The review after writing: `okl check --change` (REPORT §4at).

After the agent writes a change, okl lists the files it touched, committed or not, and every
lesson in scope one line each, with the steps: explain the change, pick the lessons it most
likely breaks, read and check each, fix. okl calls no model. The Stop hook asks for it only
where the repo turns it on.
"""
import json
import os
import re
import shlex
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


def test_touched_from_a_subdirectory_lists_the_whole_repo_from_its_root(repo, monkeypatch):
    """git ls-files lists only the current subtree, relative to it, unless told otherwise: run from
    a subdirectory, an untracked file outside it went missing (found by review)."""
    (repo / "sub").mkdir(); (repo / "sub" / "inner.py").write_text("z = 3\n")
    monkeypatch.chdir(repo / "sub")
    assert changes.touched(None)[1] == ["committed.py", "notes.md", "sub/inner.py", "untracked.py"]


def test_touched_without_a_branch_to_compare_names_the_flag(tmp_path, monkeypatch):
    """No remote default branch, main or master: say how to name one, in this command's words."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "solo"; r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(r)], check=True)
    (r / "a.py").write_text("a\n"); _git(r, "add", "-A"); _git(r, "commit", "-qm", "a")
    monkeypatch.chdir(r)
    with pytest.raises(changes.ChangesError, match="okl check --change main") as e:
        changes.touched(None)
    assert str(e.value).count("found no branch") == 1 and "--base" not in str(e.value)
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
    """The steps, the merge base, every file, the list's size, and each lesson's line, those
    governing a changed file first."""
    menu = core.review_menu([_n("b-org"), _n("c-gov")], "r", None)
    text = core.render_review({"repo": "r", "base": None, "merge_base": "abc1234def", "files": ["a.py", "b.py"],
                               "governing": ["c-gov"], "lessons": menu})
    assert "2 file(s) changed since the default branch (merge base abc1234)" in text
    assert "This review lists 2 lesson(s) in about 1 KB. Read all of it" in text
    assert all(step in text for step in core.REVIEW_STEPS)
    assert "Changed: a.py, b.py" in text
    assert "- [b-org] title b-org" in text and "— do b-org." in text
    assert text.index("govern a file this change touched (1)") < text.index("[c-gov]") \
        < text.index("Every other lesson in scope (1)") < text.index("[b-org]")
    many = core.render_review({"repo": "r", "files": [f"f{i}.py" for i in range(35)], "lessons": []})
    assert "f34.py" in many and "nothing to check against" in many
    assert "nothing to review" in core.render_review({"repo": "r", "base": "main", "files": [], "lessons": []})


def _store(repo, *nodes):
    """Lessons in the repo's own store, as `okl init` would place it."""
    s = Client()._local_store()
    for n in nodes:
        s.add_node(n)


def test_check_change_prints_the_review(repo, capsys):
    """The review lists this change's files and the lessons this repo may see, in text and JSON."""
    _store(repo, _n("b-org"), _n("z-own", scope="repo:r"), _n("a-other", scope="repo:other"),
           _n("g-notes", files="notes.md"))
    assert main(["check", "--change"]) == 0
    out = capsys.readouterr().out
    assert "3 file(s) changed" in out and "committed.py, notes.md, untracked.py" in out
    assert "[b-org]" in out and "[z-own]" in out and "[a-other]" not in out
    assert main(["check", "--change", "main", "--format", "json"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["files"] == ["committed.py", "notes.md", "untracked.py"] and got["base"] == "main"
    assert [e["id"] for e in got["lessons"]] == ["b-org", "g-notes", "z-own"]
    assert got["governing"] == ["g-notes"]


def test_check_change_refuses_with_exit_2_and_nothing_on_stdout(repo, capsys, monkeypatch):
    """Exit codes are this CLI's API: a range git cannot read is refused, never an empty review."""
    assert main(["check", "--change", "no-such-ref"]) == 2
    got = capsys.readouterr()
    assert got.out == "" and "okl check --change:" in got.err
    monkeypatch.chdir(repo.parent)   # no config here or above
    assert main(["check", "--change"]) == 2
    got = capsys.readouterr()
    assert got.out == "" and "NOT CONFIGURED" in got.err


def test_flags_that_shape_a_briefing_are_refused_with_change(repo, capsys):
    """--limit, --compact and --format actions would be ignored silently; the review lists everything."""
    for extra in (["--limit", "5"], ["--compact"], ["--format", "actions"]):
        assert main(["check", "--change", *extra]) == 2, extra
        got = capsys.readouterr()
        assert got.out == "" and "do not apply" in got.err


def test_the_hook_note_says_when_it_is_on_and_cannot_run(tmp_path, monkeypatch, capsys):
    """The hook discards stderr, so a review that is on and cannot list the change says so on
    stdout; off, it makes no git call at all."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "solo"; r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "trunk", str(r)], check=True)
    (r / "a.py").write_text("a\n"); _git(r, "add", "-A"); _git(r, "commit", "-qm", "a")
    (r / ".okl").mkdir(); (r / ".okl" / "config.json").write_text(json.dumps({"repo": "solo", "review_after_writing": True}))
    monkeypatch.chdir(r)
    assert main(["check", "--change", "--format", "hook"]) == 0
    out = capsys.readouterr().out
    assert "on in this repo, but okl could not list the changes" in out and "okl check --change <" in out
    (r / ".okl" / "config.json").write_text(json.dumps({"repo": "solo", "review_after_writing": False}))

    def no_git(*a, **k):
        raise AssertionError("git was asked although the review is off")
    monkeypatch.setattr(changes, "touched", no_git)
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out == ""


def test_the_hook_note_follows_the_setting(repo, capsys, monkeypatch):
    """On unless the config turns it off (the default since 0.17.0); the environment overrides the
    config either way."""
    monkeypatch.delenv("OKL_REVIEW_AFTER_WRITING", raising=False)
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out.strip() == core.REVIEW_NOTE
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "review_after_writing": False}))
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out == ""
    monkeypatch.setenv("OKL_REVIEW_AFTER_WRITING", "1")
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out.strip() == core.REVIEW_NOTE
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    monkeypatch.setenv("OKL_REVIEW_AFTER_WRITING", "0")
    assert main(["check", "--change", "--format", "hook"]) == 0
    assert capsys.readouterr().out == ""


def test_a_setting_okl_cannot_read_is_refused_not_ignored(repo, capsys, monkeypatch):
    """A mistyped value that left the review off would look exactly like off."""
    from okl.client import review_setting
    assert review_setting(None, "on") is True and review_setting("0", True) is False and review_setting("", None) is True
    assert review_setting(None, False) is False and review_setting("off", None) is False
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
    install._say_review_after_writing({})   # on by default: init says so, what it costs, and how to turn it off
    said = capsys.readouterr().out
    assert "review after writing: on" in said and "--no-review-after-writing" in said and "session per lesson" in said
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
    """The note comes before the encode question; a repo that turned it off sees the question alone,
    and an unset one gets the note, the default since 0.17.0."""
    hook = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "hooks" / "stop-okl-encode.sh"
    markers = tmp_path / "markers"; markers.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(markers),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "OKL_BIN": f"{sys.executable} -m okl",
           "CLAUDE_PROJECT_DIR": str(repo)}

    def stop(session):
        return subprocess.run(["bash", str(hook)], cwd=repo, text=True, capture_output=True, env=env,
                              input=json.dumps({"session_id": session, "stop_hook_active": False}))

    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r", "review_after_writing": False}))
    r = stop("off")
    assert r.returncode == 2 and "ENCODING LOOP" in r.stderr and "REVIEW AFTER WRITING" not in r.stderr
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
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


def test_the_review_asks_each_lesson_on_its_own_in_a_fresh_context():
    """REPORT §4ay: ten lessons asked one at a time caught what the same ten given as a list did
    not (§4ax). The steps ask for one sub-agent per lesson, one after another, and say what to do,
    and to say so, where an agent cannot start one."""
    steps = " ".join(" ".join(core.REVIEW_STEPS).split())
    assert "start a sub-agent for it" in steps and "one lesson each and one after another" in steps
    assert "does this change break this lesson?" in steps
    # REPORT §4bl: listing every path the rule covers before answering found more of the right lessons
    assert "to list every path the lesson's rule covers" in steps and "§4bl" in steps
    assert "If you cannot start a sub-agent" in steps and "say the review ran without fresh contexts" in steps
    assert "§4ay" in core.render_review({"repo": "r", "files": ["a.py"], "lessons": []})


def test_on_by_default_only_where_the_repo_was_set_up_for_okl(tmp_path, monkeypatch):
    """A session with a store URL exported, in a directory that never ran `okl init`, did not opt in: the
    review stays off there unless OKL_REVIEW_AFTER_WRITING=1 asks for it. With a .okl/config.json found, it
    is on by default (review of 0.17.0)."""
    from okl.client import Client, review_setting
    assert review_setting(None, None, set_up=False) is False and review_setting("1", None, set_up=False) is True
    bare = tmp_path / "bare"; bare.mkdir()
    monkeypatch.chdir(bare)
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{tmp_path / 'store.db'}")   # this test's own, restored after
    monkeypatch.delenv("OKL_REVIEW_AFTER_WRITING", raising=False)
    assert Client().configured and Client().review_after_writing is False
    monkeypatch.setenv("OKL_REVIEW_AFTER_WRITING", "1")
    assert Client().review_after_writing is True
    monkeypatch.delenv("OKL_REVIEW_AFTER_WRITING")
    (bare / ".okl").mkdir(); (bare / ".okl" / "config.json").write_text(json.dumps({"repo": "bare"}))
    assert Client().review_after_writing is True


def test_the_review_runs_each_check_on_the_model_it_was_measured_with():
    """§4ay and §4az measured the review with Sonnet sub-agents. Unnamed, a sub-agent runs on the session's
    model: ten of a larger one cost more than measured, and a smaller one was never measured. The step names
    Sonnet, labelled as Claude Code's, and says why."""
    steps = " ".join(" ".join(core.REVIEW_STEPS).split())
    assert "In Claude Code, run each on Sonnet (the Agent tool's model: sonnet)" in steps
    assert "the model the review was measured with (REPORT §4ay, §4az)" in steps



def _long_review(n=400, base=None, files=("a.py",), repo="r"):
    lessons = [{"id": f"n_{i:04d}", "title": f"lesson {i} title, about as long as a real one in this store",
                "fix": "the fix line, with enough words to look like a real one in this repository's store"}
               for i in range(n)]
    return {"repo": repo, "base": base, "merge_base": "abc1234", "files": list(files), "governing": ["n_0003"],
            "lessons": lessons}


def _lesson_lines(pages):
    return [line for p in pages for line in p.splitlines() if line.startswith("- [")]


def test_a_long_review_comes_in_pages_that_each_arrive_whole():
    """REPORT §4bk: a list past Claude Code's ~30,000-character cap came back as a 2 KB preview, and in 7 of
    the 49 sessions that never handed the right lesson on, its line never reached the agent; all 7 failed.
    Each page stays under the cap, every lesson of render_review is on exactly one page in its order, and
    page 1 has the steps and names every further page with the review's fingerprint."""
    result = _long_review()
    pages = core.review_pages(result)
    whole = core.render_review(result)
    assert len(pages) > 1 and all(len(p) <= core.REVIEW_PAGE_CHARS < 30_000 for p in pages)
    assert _lesson_lines(pages) == [line for line in whole.splitlines() if line.startswith("- [")]
    assert "1. Say what the changed code does" in pages[0] and all("1. Say what" not in p for p in pages[1:])
    fp = core.review_fingerprint(result)
    assert (f"on {len(pages)} pages" in pages[0] and f"`okl check --change --page 2 --of {fp}` through "
            f"`okl check --change --page {len(pages)} --of {fp}`" in pages[0])
    assert all(_lesson_lines([p]) for p in pages[1:])
    for n, p in enumerate(pages[:-1], 1):
        assert p.rstrip().endswith(f"End of page {n} of {len(pages)}. Next: `okl check --change --page {n + 1} "
                                   f"--of {fp}`.")
    assert pages[-1].rstrip().endswith("that is every lesson. Now pick, and check each one.")


def test_a_review_that_fits_is_render_review_unchanged():
    """A short list keeps its one output, byte for byte, and has no page 2."""
    result = _long_review(20)
    assert core.review_pages(result) == [core.render_review(result)]
    with pytest.raises(core.ReviewPageError, match="has 1 page$"):
        core.review_page(result, 2)


def test_render_review_still_lists_every_lesson_for_the_evals():
    """The eval harnesses write REVIEW.md from render_review: paging is the CLI's, so they keep every lesson."""
    result = _long_review()
    assert len(_lesson_lines([core.render_review(result)])) == 400


def test_pages_stay_under_the_cap_with_huge_changes_and_long_names():
    """A thousand changed files, a 300-character base and a 255-character repo: the Changed line is cut to
    'and N more' with the count in the title, and every page still fits."""
    files = [f"src/pkg/module_{i:04d}/some_reasonably_long_name.py" for i in range(1000)]
    base = "feature/" + "b" * 292
    result = _long_review(base=base, files=files, repo="r" * 255)
    pages = core.review_pages(result, shlex.join(["okl", "check", "--change", base, "--repo", "r" * 255]))
    assert all(len(p) <= core.REVIEW_PAGE_CHARS for p in pages)
    assert "1000 file(s) changed" in pages[0] and re.search(r", and \d+ more\n", pages[0])
    assert all(_lesson_lines([p]) for p in pages[1:])
    assert _lesson_lines(pages) == [line for line in core.render_review(result).splitlines() if line.startswith("- [")]


def test_a_review_paged_only_by_its_changed_line_fits_one_page_and_names_no_other():
    """600 changed files and 20 lessons: past the cap only by the Changed line, which is cut; the page says
    every lesson is on it and names no page that does not exist."""
    files = [f"src/pkg/module_{i:04d}/some_reasonably_long_name.py" for i in range(600)]
    pages = core.review_pages(_long_review(20, files=files))
    assert len(pages) == 1 and "--page" not in pages[0] and "all on this page" in pages[0]
    assert len(_lesson_lines(pages)) == 20 and len(pages[0]) <= core.REVIEW_PAGE_CHARS


def test_a_page_of_a_review_that_changed_since_page_1_is_refused():
    """Page breaks follow the lessons and which govern a changed file: a page asked of a different review
    could leave a lesson on no page read, so the fingerprint page 1 hands out must match. A new file that
    governs nothing, such as a page saved into the repo, moves no break and is no change."""
    result = _long_review()
    fp = core.review_fingerprint(result)
    assert core.review_page(result, 2, of=fp) == core.review_pages(result)[1]
    saved = {**result, "files": [*result["files"], *[f"page{i}_saved_from_the_review.md" for i in range(60)]]}
    assert core.review_page(saved, 2, of=fp) == core.review_pages(result)[1]
    for changed in ({**result, "governing": ["n_0003", "n_0200"]}, {**result, "lessons": result["lessons"][1:]}):
        with pytest.raises(core.ReviewPageError, match="changed since page 1.*`okl check --change` again"):
            core.review_page(changed, 2, of=fp)
    with pytest.raises(core.ReviewPageError, match=f"has {len(core.review_pages(result))} pages"):
        core.review_page(result, 9)


def test_a_backtick_in_a_branch_name_keeps_the_command_one_code_span():
    """A legal branch name can hold a backtick; the shell side is quoted, and the span gets a longer fence."""
    pages = core.review_pages(_long_review(), shlex.join(["okl", "check", "--change", "x`y"]))
    assert "`` okl check --change 'x`y' --page 2 --of " in pages[0]


def _many(repo, n=300):
    long = "a lesson title long enough that three hundred of them make a list past the page cap " * 2
    _store(repo, *[_n(f"l{i:03d}", fix=f"{long}{i}") for i in range(n)])


def test_check_change_pages_through_the_cli(repo, capsys):
    """Paged from the CLI: page 1 names the commands, the base and --repo carried and quoted; page 2 holds
    lessons page 1 does not; a page of a changed review, page 0, a page past the last, --page or --of with
    --task, json or hook, and nothing changed with --page 2 each exit 2 with nothing on stdout."""
    _many(repo)
    assert main(["check", "--change", "main", "--repo", "r"]) == 0
    one = capsys.readouterr().out
    fp = re.search(r"--page 2 --of (\w+)", one).group(1)
    assert "`okl check --change main --repo r --page 2 --of " in one and len(one) <= core.REVIEW_PAGE_CHARS
    assert main(["check", "--change", "main", "--repo", "r", "--page", "2", "--of", fp]) == 0
    two = capsys.readouterr().out
    assert set(_lesson_lines([two])) and not set(_lesson_lines([two])) & set(_lesson_lines([one]))
    (repo / "page2.md").write_text(two)   # a page saved into the repo changes no break
    assert main(["check", "--change", "main", "--repo", "r", "--page", "2", "--of", fp]) == 0
    assert capsys.readouterr().out == two
    _store(repo, _n("l999"))
    for argv in (["check", "--change", "main", "--repo", "r", "--page", "2", "--of", fp],
                 ["check", "--change", "--page", "0"], ["check", "--change", "--page", "99"],
                 ["check", "--task", "x", "--page", "2"], ["check", "--task", "x", "--of", fp],
                 ["check", "--change", "--page", "2", "--format", "json"],
                 ["check", "--change", "--page", "2", "--format", "hook"]):
        assert main(argv) == 2, argv
        got = capsys.readouterr()
        assert got.out == "" and got.err.strip(), argv


def test_the_docs_give_the_page_size_the_code_uses():
    """'about 24,000 characters' in the docs is the constant, not a copy that can fall behind it."""
    figure = f"{core.REVIEW_PAGE_CHARS:,}"
    for doc in ("docs/COSTS-AND-KNOBS.md", "docs/COMMANDS.md", "CHANGELOG.md"):
        assert figure in " ".join((Path(__file__).resolve().parent.parent / doc).read_text().split()), doc


OLD = {"GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z", "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z"}


def _git_at(r: Path, env: dict, *a: str) -> str:
    return subprocess.run(["git", "-C", str(r), *GIT, *a], capture_output=True, text=True, check=True,
                          env={**os.environ, **env}).stdout


@pytest.fixture
def worktrees(tmp_path):
    """main, clean, its commits months old; `my wt` (a space in its path), a worktree with a commit made
    now; `stale`, one whose commit and files are months old; `idle`, one with nothing changed."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    r = tmp_path / "main"; r.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(r)], check=True)
    (r / "app.py").write_text("print('hi')\n"); (r / ".gitignore").write_text(".okl/\n")
    _git_at(r, OLD, "add", "-A"); _git_at(r, OLD, "commit", "-qm", "base")
    (r / ".okl").mkdir(); (r / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    fresh, stale, idle = tmp_path / "my wt", tmp_path / "stale", tmp_path / "idle"
    _git(r, "worktree", "add", "-q", "-b", "fresh", str(fresh))
    (fresh / "feature.py").write_text("x = 1\n"); _git(fresh, "add", "-A"); _git(fresh, "commit", "-qm", "now")
    _git(r, "worktree", "add", "-q", "-b", "stale", str(stale))
    (stale / "old.py").write_text("y = 2\n"); _git_at(stale, OLD, "add", "-A"); _git_at(stale, OLD, "commit", "-qm", "old")
    months_ago = 1767225600   # 2026-01-01
    for f in stale.rglob("*"):
        if ".git" not in f.parts:
            os.utime(f, (months_ago, months_ago))
    _git(r, "worktree", "add", "-q", "-b", "idle", str(idle))
    return r, fresh


def test_worktrees_with_recent_work_finds_the_work_this_checkout_cannot_see(worktrees):
    """Work done in a worktree leaves the session's own checkout untouched, and the Stop hook looks only
    there: on okl's own repo a week of pull requests made in worktrees logged one review. A worktree with
    a commit in the last hour is named with its files; one whose commit and files are old, one with nothing
    changed, and the checkout it is asked from are not."""
    main_dir, fresh = worktrees
    found = changes.worktrees_with_recent_work(None, repo_dir=str(main_dir))
    assert [(os.path.realpath(p), files) for p, files in found] == [(os.path.realpath(fresh), ["feature.py"])]
    # Asked from the worktree itself, it is not listed: its own changes are `touched`'s to report.
    assert changes.worktrees_with_recent_work(None, repo_dir=str(fresh)) == []
    # An uncommitted file edited just now counts, in a worktree whose commit is old.
    stale = fresh.parent / "stale"
    (stale / "old.py").write_text("y = 3\n")
    assert {os.path.realpath(p) for p, _ in changes.worktrees_with_recent_work(None, repo_dir=str(main_dir))} \
        == {os.path.realpath(fresh), os.path.realpath(stale)}
    # A worktree whose folder is gone is skipped, not an error.
    shutil.rmtree(stale)
    assert len(changes.worktrees_with_recent_work(None, repo_dir=str(main_dir))) == 1


def test_the_hook_note_names_a_worktree_with_recent_work_and_quotes_its_path(worktrees, capsys, monkeypatch):
    """The note names the worktree with the command that reviews it there, the path quoted for a shell:
    the agent pastes it, and a path is the user's text (lesson n_adea7f2c7373)."""
    main_dir, fresh = worktrees
    monkeypatch.chdir(main_dir)
    monkeypatch.delenv("OKL_REVIEW_AFTER_WRITING", raising=False)
    assert main(["check", "--change", "--format", "hook"]) == 0
    out = capsys.readouterr().out
    assert out.startswith(core.REVIEW_NOTE) and "Other worktrees of this repo had work in the last hour" in out
    line = next(x for x in out.splitlines() if "feature.py" in x or "1 file(s)" in x)
    command = re.search(r"`(cd .* && okl check --change)`", line).group(1)
    assert shlex.split(command)[1] == str(fresh) and "'" in command, command
    assert "stale" not in out and "idle" not in out


def test_the_stop_hook_asks_when_only_another_worktree_has_new_work(worktrees, tmp_path):
    """A clean checkout whose last commit is old asked nothing; a commit made now in another worktree of
    the repo now holds the first stop, and okl's note names that worktree."""
    main_dir, fresh = worktrees
    hook = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "hooks" / "stop-okl-encode.sh"
    markers = tmp_path / "markers"; markers.mkdir()
    env = {"PATH": os.environ["PATH"], "HOME": str(tmp_path), "TMPDIR": str(markers),
           "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src"), "OKL_BIN": f"{sys.executable} -m okl",
           "CLAUDE_PROJECT_DIR": str(main_dir)}

    def stop(session):
        return subprocess.run(["bash", str(hook)], cwd=main_dir, text=True, capture_output=True, env=env,
                              input=json.dumps({"session_id": session, "stop_hook_active": False}))

    r = stop("with-worktree")
    assert r.returncode == 2 and "ENCODING LOOP" in r.stderr, r.stderr
    assert "REVIEW AFTER WRITING" in r.stderr and "feature.py" not in r.stderr and str(fresh) in r.stderr
    _git(main_dir, "worktree", "remove", "--force", str(fresh))
    r = stop("without")
    assert r.returncode == 0 and r.stderr == "", "no work anywhere: nothing is asked, as before"
