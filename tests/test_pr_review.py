"""ci/review-before-pr.sh: the review the developer guide asks for before a pull request, and the
record that it ran. Twelve pull requests in a row were opened without it, since nothing looked
(#500 to #511); `--check`, run at a push, says so, and in Claude Code a committed hook stops
`gh pr create` until it has run. The proof of lesson cli-review-before-the-pr."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ci" / "review-before-pr.sh"
HOOK = ROOT / ".claude" / "hooks" / "pretooluse-review-before-pr.py"

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


def test_the_check_can_be_asked_about_a_branch_that_is_not_checked_out(branch):
    """`--check <branch>` reads a named local branch at its own tip: a pull request can be opened
    for a branch from another folder. A name that is no branch here cannot be told (2)."""
    repo, run = branch
    _git(repo, "checkout", "-q", "main")
    assert run("--check").returncode == 0, "main itself has nothing to review"
    named = run("--check", "feature")
    assert named.returncode == 1 and "NO REVIEW RECORDED for branch 'feature'" in named.stderr and named.stdout == ""
    for args in (("--check", "no-such-branch"), ("--check", "feature", "more")):
        r = run(*args)
        assert r.returncode == 2 and r.stdout == "" and "review-before-pr:" in r.stderr, (args, r.stderr)
    _git(repo, "checkout", "-q", "feature")
    assert run().returncode == 0
    _git(repo, "checkout", "-q", "main")
    assert run("--check", "feature").returncode == 0


def _asked(repo: Path, command: str, cwd: Path | None = None, payload: str | None = None) -> subprocess.CompletedProcess:
    """What the agent hook answers when Claude Code is about to run `command` in `cwd`."""
    hook = repo / ".claude" / "hooks" / HOOK.name
    hook.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(HOOK, hook)
    sent = payload if payload is not None else json.dumps({
        "hook_event_name": "PreToolUse", "tool_name": "Bash", "cwd": str(cwd or repo), "tool_input": {"command": command}})
    env = {"PATH": f"{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(repo.parent)}
    return subprocess.run([sys.executable, str(hook)], input=sent, env=env, capture_output=True, text=True)


def test_the_agent_hook_stops_a_pull_request_until_the_branch_has_a_recorded_review(branch):
    """In Claude Code the hook exits 2 on `gh pr create` for a branch with no recorded review, and
    stderr (what the agent is given) names the branch, how to run the review and how a waiver is
    said. Once a review is recorded the same command goes through, with nothing printed."""
    repo, run = branch
    stopped = _asked(repo, "gh pr create --title x --body y")
    assert stopped.returncode == 2 and stopped.stdout == "", stopped.stdout + stopped.stderr
    for said in ("NO REVIEW RECORDED for branch 'feature'", "PULL REQUEST NOT OPENED", "ci/review-before-pr.sh", "PR_REVIEW_WAIVED=docs-only"):
        assert said in stopped.stderr, stopped.stderr
    assert run().returncode == 0
    through = _asked(repo, "gh pr create --title x --body y")
    assert (through.returncode, through.stdout, through.stderr) == (0, "", "")


BODY = """gh pr create --title "it's ready" --body "$(cat <<'EOF'
Don't read this as a flag: --head nope
gh pr create --head nope
EOF
)" """


@pytest.mark.parametrize("command, checked_out", [
    ("cd {repo} && gh pr create --fill", "feature"),
    ('cd "{repo}" && git push -q && PAGER=cat gh pr create --fill', "feature"),
    ("gh pr create --head feature --title x", "main"),
    ("cd {repo}; gh pr create -H someone:feature", "main"),
    ("gh pr create \\\n  --head=feature", "main"),
    ("if gh pr create --fill; then echo opened; fi", "feature"),
    (BODY, "feature"),
], ids=["cd", "cd-quoted-then-push", "head", "head-with-owner", "head-on-the-next-line", "inside-if", "body-with-quotes"])
def test_the_agent_hook_finds_the_branch_the_pull_request_is_for(branch, command, checked_out):
    """The agent opens pull requests from another folder (`cd <worktree> && gh pr create`) or for a
    named branch (`--head`): the hook reads the branch from the command, not from where the session
    is, and a body's own words (quotes, a heredoc that mentions --head) do not mislead it."""
    repo, _ = branch
    _git(repo, "checkout", "-q", checked_out)
    elsewhere = repo.parent if command.startswith("cd") else repo
    r = _asked(repo, command.replace("{repo}", str(repo)), cwd=elsewhere)
    assert r.returncode == 2 and "NO REVIEW RECORDED for branch 'feature'" in r.stderr and r.stdout == "", r.stderr


@pytest.mark.parametrize("command", [
    'git commit -m "Stop gh pr create for a branch nobody reviewed"',
    "grep -rn 'gh pr create' docs/",
    "echo run gh pr create when the review is done",
    "cat > note.md <<'EOF'\ngh pr create --fill\nEOF",
    "gh pr view 12 && gh pr list && gh issue create --title x && gh pr created",
    "PR_REVIEW_WAIVED=docs-only gh pr create --fill",
    'PR_REVIEW_WAIVED="docs only" gh pr create --fill',
    "gh pr create --repo someone/elsewhere --fill",
    "cd {other} && gh pr create --fill",
    "cd {nowhere} && gh pr create --fill",
], ids=["commit-message", "grep", "an-argument", "heredoc", "other-gh-commands", "waived", "waived-quoted", "another-repo-named",
        "another-repository", "no-repository"])
def test_the_agent_hook_lets_through_what_is_not_a_pull_request_for_this_repository(branch, tmp_path, command):
    """On a branch with no review the hook still says nothing (exit 0, no output) to a command that
    only mentions `gh pr create`, to one that says its waiver, and to a pull request for another
    repository: the rule is this repository's own."""
    repo, _ = branch
    _git(repo, "remote", "add", "origin", "https://example.invalid/me/okl.git")
    other = tmp_path / "other"
    other.mkdir()
    _git(other, "init", "-q")
    _git(other, "commit", "-q", "--allow-empty", "-m", "another repository's base")
    _git(other, "branch", "-M", "main")
    _git(other, "update-ref", "refs/remotes/origin/main", "HEAD")
    _git(other, "checkout", "-q", "-b", "feature")
    _git(other, "commit", "-q", "--allow-empty", "-m", "its own unreviewed work: let through only because it is another repository")
    nowhere = tmp_path / "plain-folder"
    nowhere.mkdir()
    r = _asked(repo, command.replace("{other}", str(other)).replace("{nowhere}", str(nowhere)))
    assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), r.stderr


@pytest.mark.parametrize("command, says", [
    ("PR_REVIEW_WAIVED= gh pr create --fill", "NO REVIEW RECORDED"),
    ("echo PR_REVIEW_WAIVED=yes; gh pr create --fill", "NO REVIEW RECORDED"),
    ('gh pr create --title x --body "PR_REVIEW_WAIVED=yes"', "NO REVIEW RECORDED"),
    ("gh pr create --repo me/okl --fill", "NO REVIEW RECORDED"),
    ("cd /no/such/folder && gh pr create --fill", "cannot tell which folder"),
    ("gh pr create --head no-such-branch", "no local branch 'no-such-branch'"),
], ids=["empty-waiver", "waiver-on-another-command", "waiver-in-the-body", "this-repo-named", "folder-missing", "branch-missing"])
def test_the_agent_hook_stops_what_it_cannot_tell_and_a_waiver_that_was_not_said(branch, command, says):
    """A waiver counts only as a non-empty assignment on the `gh pr create` command itself. Where
    the hook cannot tell which branch is meant, it stops the command and says why: silence there
    would read as reviewed."""
    repo, _ = branch
    _git(repo, "remote", "add", "origin", "https://example.invalid/me/okl.git")
    r = _asked(repo, command)
    assert r.returncode == 2 and says in r.stderr and "PULL REQUEST NOT OPENED" in r.stderr and r.stdout == "", r.stderr


def test_the_agent_hook_lets_through_input_it_cannot_read(branch):
    """Anything that is not a Bash call's payload is let through, silently: the hook never holds a
    tool call it could not read."""
    repo, _ = branch
    for payload in ("", "not json", "[]", json.dumps({"tool_input": {"file_path": "gh pr create"}}), json.dumps({"tool_input": {"command": 7}})):
        r = _asked(repo, "", payload=payload)
        assert (r.returncode, r.stdout, r.stderr) == (0, "", ""), (payload, r.stderr)


def test_the_agent_hook_is_registered_for_every_bash_call_and_can_run():
    """A check nobody runs is a paragraph. The committed Claude Code settings run the hook before
    every Bash call, with no `if` filter (Claude Code calls that filter best-effort, and a command
    it missed would open the pull request unseen); the file is there and executable."""
    entries = json.loads((ROOT / ".claude" / "settings.json").read_text())["hooks"]["PreToolUse"]
    ours = [h for e in entries if e.get("matcher") == "Bash" for h in e["hooks"]
            if h["command"].endswith(f"/.claude/hooks/{HOOK.name}")]
    assert len(ours) == 1 and ours[0]["type"] == "command" and "if" not in ours[0], entries
    assert ours[0]["command"].startswith('"$CLAUDE_PROJECT_DIR"/'), "anchored to the project, not to where a cd left the session"
    assert HOOK.is_file() and os.access(HOOK, os.X_OK)
