"""ci/review-before-pr.sh: the review the developer guide asks for before a pull request, and the
record that it ran. Twelve pull requests in a row were opened without it, since nothing looked
(#500 to #511); `--check`, run at a push, says so. The proof of lesson cli-review-before-the-pr."""
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ci" / "review-before-pr.sh"

FAKE = r'''
import subprocess, sys
mode = sys.argv[1]
print("Connecting...")
if mode == "commits":      # a commit lands on the branch while the review runs
    subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "commit", "-q",
                    "--allow-empty", "-m", "made while the review ran"], check=True)
if mode == "limit":
    print("Review limit reached. Try again in 43 minutes.")
    sys.exit(0)
if mode == "cut":
    sys.exit(3)
print("Review completed\n2 findings")
sys.exit(3 if mode == "fails" else 0)
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def branch(tmp_path):
    """A repository on branch `feature`, one commit ahead of origin/main, and a stand-in for the review CLI."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    (repo / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "ci" / SCRIPT.name)
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "-M", "main")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "-q", "-b", "feature")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "the change")
    fake = tmp_path / "fake_review.py"
    fake.write_text(FAKE)

    def run(*args: str, mode: str = "completes", **extra: str) -> subprocess.CompletedProcess:
        env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path),
               "PR_REVIEW_CMD": f"{sys.executable} {fake} {mode}", **extra}
        return subprocess.run(["bash", "ci/review-before-pr.sh", *args], cwd=repo, env=env, capture_output=True, text=True)

    return repo, run


def _records(repo: Path) -> list[Path]:
    return sorted((repo / ".git" / "okl-pr-review").glob("*")) if (repo / ".git" / "okl-pr-review").is_dir() else []


def test_a_branch_with_no_recorded_review_is_named_and_one_that_has_it_passes(branch):
    """`--check` exits 1 and names the branch while no review of it is recorded, and says how to run
    one. A finished review records the commit it read; the check then passes, silently, and still
    passes with the fixes committed on top. Nothing is printed to stdout either way."""
    repo, run = branch
    missing = run("--check")
    assert missing.returncode == 1 and missing.stdout == "", missing.stdout + missing.stderr
    assert "NO REVIEW RECORDED for branch 'feature'" in missing.stderr and "bash ci/review-before-pr.sh" in missing.stderr
    typo = run("--chek")
    assert typo.returncode == 2 and "unknown argument '--chek'" in typo.stderr and _records(repo) == [], "a typo starts no review"
    reviewed = _git(repo, "rev-parse", "HEAD")
    ran = run()
    assert ran.returncode == 0 and ran.stdout == "", ran.stdout + ran.stderr
    assert "2 findings" in ran.stderr and f"recorded a finished review of 'feature' at {reviewed[:12]}" in ran.stderr
    (record,) = _records(repo)
    assert record.read_text().splitlines()[:2] == [reviewed, "feature"]
    assert _git(repo, "status", "--porcelain") == "", "the record is in the git directory, never the work tree"
    passed = run("--check")
    assert (passed.returncode, passed.stdout, passed.stderr) == (0, "", "")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "fix what it found")
    assert run("--check").returncode == 0, "the fixes it asked for come after the review"
    # Rewritten, the branch no longer holds the commit that was reviewed.
    _git(repo, "reset", "-q", "--hard", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "the change, written again")
    assert run("--check").returncode == 1
    # Another branch is another change.
    _git(repo, "checkout", "-q", "-b", "other", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "another change")
    other = run("--check")
    assert other.returncode == 1 and "branch 'other'" in other.stderr


@pytest.mark.parametrize("mode, says", [("limit", "did not print"), ("cut", "exited 3"), ("fails", "exited 3")])
def test_a_review_that_did_not_finish_records_nothing(branch, mode, says):
    """The review CLI exits 0 when the allowance refused the review, so its exit alone proves nothing
    (DEVELOPING.md: "Check that a requested PR review actually ran"). Only a run that exited 0 and
    printed its completed line is recorded; anything else is "did not run" (2) and the check stays 1."""
    repo, run = branch
    r = run(mode=mode)
    assert r.returncode == 2 and r.stdout == "" and "REVIEW NOT RECORDED" in r.stderr and says in r.stderr, r.stderr
    assert _records(repo) == [] and run("--check").returncode == 1


def test_the_recorded_commit_is_the_one_read_before_the_review_began(branch):
    """A review runs for minutes. A commit made meanwhile was not reviewed, so it is not the one recorded."""
    repo, run = branch
    before = _git(repo, "rev-parse", "HEAD")
    assert run(mode="commits").returncode == 0
    assert _git(repo, "rev-parse", "HEAD") != before and _records(repo)[0].read_text().splitlines()[0] == before


def test_where_there_is_nothing_to_review_the_check_passes_and_a_run_refuses(branch):
    """The default branch, a detached commit and a branch with no commit of its own have nothing to
    review: the check passes, and a run refuses (2) and starts no review. With no base to compare
    with, neither can tell."""
    repo, run = branch
    _git(repo, "checkout", "-q", "main")
    assert run("--check").returncode == 0
    nothing = run()
    _git(repo, "commit", "-q", "--allow-empty", "-m", "a commit on main that origin lacks")
    assert run("--check").returncode == 0, "a push of the default branch is no pull request"
    _git(repo, "reset", "-q", "--hard", "origin/main")
    assert nothing.returncode == 2 and "nothing to review" in nothing.stderr and "Connecting" not in nothing.stderr
    _git(repo, "checkout", "-q", "-b", "empty-branch")
    assert run("--check").returncode == 0 and run().returncode == 2
    _git(repo, "checkout", "-q", "--detach", "feature")
    assert run("--check").returncode == 0 and run().returncode == 2
    _git(repo, "checkout", "-q", "feature")
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")
    for args in (["--check"], []):
        r = run(*args)
        assert r.returncode == 2 and "is not here to compare with" in r.stderr and r.stdout == "", r.stderr


def test_a_record_from_before_the_branch_was_merged_and_started_again_does_not_count(branch):
    """A branch name is used again. The old record's commit is in main by then, so it is under every
    new commit of that name, and counted as a review of work it never read."""
    repo, run = branch
    assert run().returncode == 0 and run("--check").returncode == 0
    _git(repo, "checkout", "-q", "main")
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge feature", "feature")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(repo, "checkout", "-q", "-B", "feature", "main")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "new work under the old name")
    again = run("--check")
    assert again.returncode == 1 and "NO REVIEW RECORDED" in again.stderr


def test_the_record_is_never_written_or_read_through_a_link(branch, tmp_path):
    """The record is a file okl's script writes in the git directory. A link there is refused both
    ways: nothing is written where it points, and what it points at is not a record."""
    repo, run = branch
    assert run().returncode == 0
    (record,) = _records(repo)
    kept = record.read_text()
    outside = tmp_path / "outside.txt"
    outside.write_text(kept)
    record.unlink()
    record.symlink_to(outside)
    assert run("--check").returncode == 1, "a link is not a record"
    _git(repo, "commit", "-q", "--allow-empty", "-m", "more")
    refused = run()
    assert refused.returncode == 2 and "is a symlink" in refused.stderr and outside.read_text() == kept
