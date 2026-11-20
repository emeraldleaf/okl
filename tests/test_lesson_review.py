"""ci/lesson-review.sh: the review after writing, run on a pull request with any model's CLI.

A stand-in reviewer records each prompt it is given and the folder it ran in, and answers as the
test tells it: a pick, then a verdict per lesson, or a failure."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from okl.scaffold_cmd import scaffold

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ci" / "lesson-review.sh"

FAKE = r'''
import json, os, sys, tempfile
prompt = sys.stdin.read()
fd, path = tempfile.mkstemp(dir=os.environ["CALLS_DIR"], prefix="call-", suffix=".txt")
with os.fdopen(fd, "w") as f:
    f.write(os.getcwd() + "\n" + prompt)
if "--- THE LESSONS, ONE LINE EACH ---" in prompt:
    print(os.environ.get("PICK_REPLY") or json.dumps({"explanation": ["it adds a line to a.py"],
                                                      "picked": json.loads(os.environ["PICKED"])}))
    sys.exit(0)
lesson = prompt.split("--- END OF THE LESSON ---")[0]
for lid, verdict in json.loads(os.environ.get("VERDICTS", "{}")).items():
    if "[%s]" % lid in lesson:
        if verdict == "FAIL":
            sys.stderr.write("Error: rate limited\n")
            sys.exit(3)
        print("My answer:\n```json\n" + json.dumps({"paths": [{"path": "a.py", "holds": verdict != "breaks", "why": "w"}],
              "verdict": verdict, "file": "a.py", "line": 2,
              "finding": "finding for %s | cc @someone" % lid}) + "\n```")
        sys.exit(0)
print("I could not decide.")
'''


def _git(repo: Path, *args: str) -> str:
    # The identity per command, never `git config`, and always run in `repo` (lesson
    # probe-cd-fails-into-real-repo: a probe's git writes once landed in the real checkout).
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def setup(tmp_path):
    """A repository with one committed change, a store of three lessons, okl on PATH as this checkout's
    code, and the stand-in reviewer as REVIEW_CMD."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    (repo / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "ci" / "lesson-review.sh")
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\n")
    _git(repo, "commit", "-qam", "change")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "okl"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m okl "$@"\n')
    shim.chmod(0o755)
    fake = tmp_path / "fake_reviewer.py"
    fake.write_text(FAKE)
    calls = tmp_path / "calls"
    calls.mkdir()
    env = {"PATH": f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path),
           "PYTHONPATH": str(ROOT / "src"), "OKL_DATABASE_URL": f"sqlite:///{tmp_path / 'store.db'}",
           "OKL_BRIEFING_LOG": "0", "CALLS_DIR": str(calls), "REVIEW_BASE_REF": base,
           "REVIEW_CMD": f"{sys.executable} {fake}", "LESSON_REVIEW_PARALLEL": "1"}
    for lid, title in (("l-alpha", "ALPHA-TITLE: retries need a deadline"),
                       ("l-beta", "BETA-TITLE: a cache key names every input"),
                       ("l-gamma", "GAMMA-TITLE: exit codes are public API")):
        subprocess.run([sys.executable, "-m", "okl", "record", "--type", "Rule", "--scope", "org", "--tags", "method",
                        "--id", lid, "--title", title, "--fix", f"the fix for {lid}", "--body", "cause: c"],
                       cwd=repo, env=env, check=True, capture_output=True, text=True)

    def run(**extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(repo / "ci" / "lesson-review.sh")], cwd=repo,
                              env={**env, **extra}, capture_output=True, text=True)

    def prompts() -> list[tuple[str, str]]:
        out = []
        for f in sorted(calls.glob("call-*.txt")):
            cwd, _, prompt = f.read_text().partition("\n")
            out.append((cwd, prompt))
        return out

    return {"repo": repo, "run": run, "prompts": prompts, "tmp": tmp_path}


def test_the_lesson_review_ships_with_the_kit_and_soft_passes_until_it_is_configured(tmp_path):
    """Installing the kit calls nobody's model: with no REVIEW_CMD, with one not installed, or with no
    okl to read the lessons, the step passes and says why."""
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    script = tmp_path / "ci" / "lesson-review.sh"
    assert script.read_bytes() == SCRIPT.read_bytes(), "the kit must ship the script this repo runs"

    def run(extra: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(script)], capture_output=True, text=True, cwd=str(tmp_path),
                              env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), **extra})

    r = run({})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "soft pass" in r.stdout
    assert "REVIEW_CMD" in r.stdout
    r = run({"REVIEW_CMD": "definitely-not-installed -p"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "not on PATH" in r.stderr
    r = run({"REVIEW_CMD": "cat"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "okl is not on PATH" in r.stderr


def test_one_call_picks_and_one_fresh_call_checks_each_picked_lesson(setup):
    """The steps `okl check --change` prints, as a script makes them: the pick sees every lesson and
    the change; each check sees one lesson's full text and the path question, from an empty folder;
    an id the pick invented is left out and named."""
    r = setup["run"](PICKED=json.dumps(["l-alpha", "[l-beta]", "n_invented", "l-alpha"]),
                     VERDICTS=json.dumps({"l-alpha": "breaks", "l-beta": "holds"}),
                     REVIEW_PR_TITLE="TITLE-MARKER", GITHUB_ACTIONS="true",
                     LESSON_REVIEW_REPORT=str(setup["tmp"] / "report.md"))
    assert r.returncode == 0, r.stdout + r.stderr
    calls = setup["prompts"]()
    assert len(calls) == 3, [p[:80] for _c, p in calls]           # one pick, two checks
    pick = [p for _c, p in calls if "--- THE LESSONS, ONE LINE EACH ---" in p]
    assert len(pick) == 1
    for marker in ("[l-alpha]", "[l-beta]", "[l-gamma]", "CHANGE-MARKER", "TITLE-MARKER", "a.py"):
        assert marker in pick[0], marker
    checks = [p for _c, p in calls if "--- THE LESSON ---" in p]
    assert len(checks) == 2
    for p in checks:
        lesson = p.split("--- END OF THE LESSON ---")[0]
        assert sum(t in lesson for t in ("ALPHA-TITLE", "BETA-TITLE", "GAMMA-TITLE")) == 1, lesson
        assert "list every path the lesson's rule covers" in p
        assert "CHANGE-MARKER" in p
    for cwd, _p in calls:
        assert not Path(cwd).resolve().is_relative_to(setup["repo"].resolve()), cwd
    report = (setup["tmp"] / "report.md").read_text()
    assert report.startswith("<!-- okl-lesson-review -->")
    assert "2 of the 2 lessons picked from 3 in scope were checked" in report
    assert "| `l-alpha` ALPHA-TITLE: retries need a deadline | **breaks** |" in report
    assert "finding for l-alpha \\| cc @\u200bsomeone (`a.py:2`)" in report     # no column break, no mention
    assert "| `l-beta` BETA-TITLE: a cache key names every input | holds |" in report
    assert "`n_invented`" in report
    assert "GAMMA" not in report.split("<details>")[0]
    assert "::warning file=a.py,line=2,title=lesson review%3A l-alpha::finding for l-alpha" in r.stdout


def test_a_broken_lesson_fails_the_job_only_when_told_to_block(setup):
    """A check in CI has no measured false-alarm rate, so a broken lesson blocks only with
    LESSON_REVIEW_BLOCKING=1, and a lesson with no bearing never does."""
    picks = {"PICKED": json.dumps(["l-alpha"]), "VERDICTS": json.dumps({"l-alpha": "breaks"}), "GITHUB_ACTIONS": "true"}
    r = setup["run"](**picks, LESSON_REVIEW_BLOCKING="1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::error file=a.py,line=2,title=lesson review%3A l-alpha::" in r.stdout
    r = setup["run"](**{**picks, "VERDICTS": json.dumps({"l-alpha": "no bearing"})}, LESSON_REVIEW_BLOCKING="1")
    assert r.returncode == 0, r.stdout + r.stderr


def test_a_check_that_fails_is_named_with_why_and_the_rest_still_report(setup):
    """A failed call and a reply with no verdict each leave a lesson unchecked, named with why: the
    failed call's exit status and last error line, as ci/review-agent.sh keeps them."""
    r = setup["run"](PICKED=json.dumps(["l-alpha", "l-beta", "l-gamma"]),
                     VERDICTS=json.dumps({"l-alpha": "FAIL", "l-beta": "holds"}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 of the 3 lessons picked from 3 in scope were checked" in r.stdout
    assert "- `l-alpha`: it exited 3: Error: rate limited" in r.stdout
    assert "- `l-gamma`: its reply held no verdict" in r.stdout
    assert "| `l-beta`" in r.stdout


@pytest.mark.parametrize("extra,says", [
    ({"PICK_REPLY": "I could not pick."}, "gave no pick"),
    ({"PICKED": json.dumps(["n_invented"])}, "named no lesson in scope"),
])
def test_no_pick_is_no_review_and_says_so(setup, extra, says):
    """A run with no pick has checked nothing: the report and an annotation say so, rather than an
    empty report a reader takes for a clean one."""
    r = setup["run"](**extra, GITHUB_ACTIONS="true")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "No review" in r.stdout
    assert says in r.stdout
    assert "::warning title=lesson review::no lesson review" in r.stdout
    assert len(setup["prompts"]()) == 1


def test_it_reviews_uncommitted_work_as_okl_lists_it_and_nothing_when_nothing_changed(setup):
    """Run on a machine, the change is what okl lists, committed or not; with nothing changed no
    model is called."""
    head = _git(setup["repo"], "rev-parse", "HEAD")
    (setup["repo"] / "a.py").write_text("x = 1\ny = 2\nz = 3  # UNCOMMITTED-MARKER\n")
    (setup["repo"] / "new.py").write_text("NEW-FILE-MARKER = 1\n")          # not added to git yet
    (setup["repo"] / "deps.lock").write_text("LOCKFILE-MARKER\n")          # data: left out
    r = setup["run"](PICKED=json.dumps(["l-gamma"]), VERDICTS=json.dumps({"l-gamma": "holds"}))
    assert r.returncode == 0, r.stdout + r.stderr
    for _c, p in setup["prompts"]():
        assert "UNCOMMITTED-MARKER" in p
        assert "+NEW-FILE-MARKER = 1" in p
        assert "LOCKFILE-MARKER" not in p
    _git(setup["repo"], "checkout", "--", "a.py")
    (setup["repo"] / "new.py").unlink()
    (setup["repo"] / "deps.lock").unlink()
    for f in (setup["tmp"] / "calls").glob("call-*"):
        f.unlink()
    r = setup["run"](REVIEW_BASE_REF=head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "nothing changed" in r.stdout
    assert setup["prompts"]() == []


def test_a_store_okl_cannot_read_is_a_warning_and_no_call(setup):
    """With no store okl can read, nothing is reviewed and the run says so, with no model call."""
    r = setup["run"](OKL_DATABASE_URL="", GITHUB_ACTIONS="true")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "okl could not list the change and its lessons" in r.stderr
    assert "::warning title=lesson review::okl could not list" in r.stdout
    assert setup["prompts"]() == []
