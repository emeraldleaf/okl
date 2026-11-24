#!/usr/bin/env python3
"""PreToolUse hook on Bash, in Claude Code: stop `gh pr create` for a branch of this repository
that has no recorded review (docs/DEVELOPING.md, "Review before the PR").

Why it exists. The rule was a paragraph in the developer guide, and the agent opened twelve pull
requests in a row without the review (#500 to #511). The push-time line
(`bash ci/review-before-pr.sh --check || true`) lives in each developer's own git hook and only
reports, so the rule was still something nobody ran. This hook is committed
(.claude/settings.json), and it holds the agent at the step the rule names.

It is okl's own rule for its own repository: `okl init` installs no copy of it.

What it reads. The command as text, with heredoc bodies and quoted strings set aside, so a commit
message or a pull request body that mentions `gh pr create` is not one. The branch is the one
`--head` names, else the one checked out in the folder the `cd`s earlier in the same command lead
to, else the one checked out where the command runs. Each `gh pr create` in the call is read, with
its own waiver. A `gh pr create` inside `bash -c '...'` or behind a variable is not seen.

What it stops because it cannot tell. The hook runs before the command, so a branch the command
itself checks out first (`git checkout x && gh pr create`) is not the one it would read: that is
stopped unless `--head` names the branch. So is `--head owner:branch` for another owner, since
the reviews on record are of this repository's own branches.

A waiver is said in the command itself, where whoever approves the command reads it:

    PR_REVIEW_WAIVED=docs-only gh pr create ...

Exit: 0 lets the command through (not a `gh pr create`, another repository, reviewed, nothing to
review, or waived). 2 stops it, and stderr is the reason Claude Code gives the agent: no review is
recorded, or the hook could not tell. Input it cannot read as a Bash call is let through.
"""
import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn

CHECK = Path(__file__).resolve().parents[2] / "ci" / "review-before-pr.sh"
WORD = r"([^\s;&|()<>]+)"
START = r"(?:^|[;&|({\n])\s*(?:(?:if|then|else|do|!|time|command|exec)\s+)*"
CREATE = re.compile(START + r"((?:[A-Za-z_]\w*=\S*\s+)*)gh\s+pr\s+(?:(?:-R|--repo)(?:=|\s+)\S+\s+)?create(?![\w-])")
CD = re.compile(START + r"cd\s+(?:--\s+)?" + WORD)
HEAD = re.compile(r"\s(?:--head|-H)(?:=|\s+)" + WORD)
REPO = re.compile(r"\s(?:--repo|-R)(?:=|\s+)" + WORD)
WAIVED = re.compile(r"(?:^|\s)PR_REVIEW_WAIVED=(\S*)")
CHANGES_BRANCH = re.compile(r"(?<![\w-])git\s[^;&|\n]*?(?<![\w-])(?:checkout|switch)(?![\w-])|(?<![\w-])gh\s+pr\s+checkout(?![\w-])")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1([^\n]*)\n(?:.*?\n)?[ \t]*\2[ \t]*(?=\n|$)", re.S)
MARK = re.compile("\x00(\\d+)\x00")


def skeleton(command: str) -> tuple[str, list[str]]:
    """The command with each heredoc body dropped and each quoted string replaced by a numbered
    mark, and the strings the marks stand for. What is left is the words the shell runs."""
    command = HEREDOC.sub(lambda m: " " + m.group(3), command)
    out: list[str] = []
    words: list[str] = []
    i = 0
    while i < len(command):
        c = command[i]
        if c == "\\" and i + 1 < len(command):
            out.append(" " if command[i + 1] == "\n" else command[i:i + 2])
            i += 2
        elif c in "'\"":
            j = i + 1
            while j < len(command) and command[j] != c:
                j += 2 if c == '"' and command[j] == "\\" else 1
            words.append(command[i + 1:j])
            out.append(f"\x00{len(words) - 1}\x00")
            i = j + 1
        else:
            out.append(c)
            i += 1
    return "".join(out), words


def git(folder: Path, *args: str) -> str | None:
    """What a git command run in a folder printed, or None when it failed."""
    try:
        p = subprocess.run(["git", "-C", str(folder), *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def repository(folder: Path) -> Path | None:
    """The git directory a folder's repository keeps, shared by its worktrees."""
    common = git(folder, "rev-parse", "--git-common-dir")
    return (folder / common).resolve() if common else None


def stop(reason: str) -> NoReturn:
    """Stop the command: the reason goes to stderr, which Claude Code gives the agent with exit 2."""
    sys.stderr.write(
        f"{reason.rstrip()}\n"
        "PULL REQUEST NOT OPENED (docs/DEVELOPING.md, \"Review before the PR\"). Run the review in that\n"
        f"  branch's folder first: bash {CHECK}\n"
        "  It takes about ten minutes. Fix what it finds in one push, then open the pull request.\n"
        "  A docs-only change says so in the command: PR_REVIEW_WAIVED=docs-only gh pr create ...\n"
        "  Any other waiver is the user's to give.\n")
    sys.exit(2)


def main() -> None:
    """Read one PreToolUse payload from stdin and let the command through or stop it."""
    try:
        payload = json.load(sys.stdin)
        command = payload["tool_input"]["command"]
    except (ValueError, TypeError, KeyError):
        return
    if not isinstance(command, str) or "create" not in command:
        return
    text, words = skeleton(command)

    def said(word: str) -> str:
        return MARK.sub(lambda m: words[int(m.group(1))], word)

    # Every `gh pr create` in the call, each with its own waiver: one waived command does not
    # cover the next.
    start = Path(payload.get("cwd") or Path.cwd())
    for create in CREATE.finditer(text):
        reason = reason_to_stop(create, text, said, start)
        if reason:
            stop(reason)


def reason_to_stop(create: re.Match[str], text: str, said: Callable[[str], str], start: Path) -> str | None:
    """Why one `gh pr create` in the command must not run, or None when it may."""
    waived = WAIVED.search(" " + create.group(1))
    if waived and said(waived.group(1)).strip():
        return None
    before = text[:create.start()]
    folder = folder_of(before, said, start)
    branch = folder if isinstance(folder, str) else branch_of(create, text, said, folder)
    if not isinstance(branch, list) or isinstance(folder, str):
        return branch   # a reason it cannot tell, or None: not this repository's pull request
    try:
        check = subprocess.run(["bash", str(CHECK), "--check", *branch], cwd=folder, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return f"review-before-pr: the check did not run ({type(e).__name__}), so it cannot tell whether the branch was reviewed."
    said_nothing = f"review-before-pr: the check exited {check.returncode} and said nothing."
    return (check.stderr or said_nothing) if check.returncode != 0 else None


def folder_of(before: str, said: Callable[[str], str], start: Path) -> Path | str:
    """Where the command will be when it reaches `gh pr create`, or why that cannot be told."""
    folder = start
    for move in CD.findall(before):   # each cd starts where the last one ended
        folder = folder / Path(os.path.expandvars(said(move))).expanduser()
        if not folder.is_dir():
            return f"review-before-pr: cannot tell which folder `cd {said(move)}` is, so not which branch the pull request is for."
    return folder


def branch_of(create: re.Match[str], text: str, said: Callable[[str], str], folder: Path) -> list[str] | str | None:
    """The branch to ask the check about: [name] when `--head` names it, [] for the one checked
    out in `folder`. A string is why it cannot be told; None is another repository's pull request."""
    theirs, ours = repository(folder), repository(CHECK.parents[1])
    if theirs is None or theirs != ours:
        return None   # another repository, or none: not this repository's rule
    rest = re.split(r"[;&|)\n]", text[create.end():], maxsplit=1)[0]
    # Owner and name, however each is written: git@host:owner/name.git, https://host/owner/name,
    # owner/name, host/owner/name.
    origin = [p for p in re.split(r"[/:]", (git(folder, "remote", "get-url", "origin") or "").lower().removesuffix(".git")) if p][-2:]
    named = REPO.search(" " + create.group(0) + rest)
    if named and len(origin) == 2 and said(named.group(1)).lower().removesuffix(".git").split("/")[-2:] != origin:
        return None   # a pull request in another repository
    head = HEAD.search(rest)
    if head:
        owner, _, name = said(head.group(1)).rpartition(":")
        if owner and (len(origin) != 2 or owner.lower() != origin[0]):
            return (f"review-before-pr: cannot tell which branch `--head {owner}:{name}` is. The reviews on record are of "
                    "this repository's own branches, and that names another owner's.")
        return [name]
    if CHANGES_BRANCH.search(text[:create.start()]):
        return ("review-before-pr: a branch is checked out earlier in this command, so it cannot tell which branch the "
                "pull request is for. Open it in a call of its own, or name the branch with --head.")
    return []


if __name__ == "__main__":
    main()
