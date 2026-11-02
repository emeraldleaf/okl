"""Owner-approved paths: the CODEOWNERS lines `okl init --owner` writes (#329).

A thesis an agent keeps updating needs a person's approval on each change, and only the
forge can enforce that. okl names the person as code owner of the paths that need them, here
`docs/THESIS.md` and the CODEOWNERS file itself, so that a branch rule requiring code-owner
review makes GitHub refuse the merge without them. Whether that rule is on, and binds the
identity the agent runs as, is `okl doctor`'s question (okl.protection), not this module's.

okl's lines sit in one marked block, at the end of the file: CODEOWNERS applies the last
matching line, so a broader team rule above (`* @team`) does not override them. A path the
team already owns on a line of its own is left to that line and reported, never rewritten.
This module imports nothing from okl.
"""
from __future__ import annotations

import re
from pathlib import Path

# Where GitHub looks, in its order; the first that exists is the one it reads.
LOCATIONS = (Path(".github/CODEOWNERS"), Path("CODEOWNERS"), Path("docs/CODEOWNERS"))
BEGIN = "# okl: owner-approved paths, written by `okl init --owner` (#329). okl rewrites this block."
END = "# okl: end of owner-approved paths"
DEFAULT_PATHS = ("docs/THESIS.md",)
# A GitHub user (@name), team (@org/team) or email address, as CODEOWNERS accepts them.
OWNER = re.compile(r"@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:/[A-Za-z0-9._-]+)?|[^@\s]+@[^@\s]+\.[^@\s]+")


def location(root: Path) -> Path:
    """The CODEOWNERS file GitHub reads here, or where okl creates one (relative to root)."""
    return next((p for p in LOCATIONS if (root / p).is_file()), LOCATIONS[0])


def normalise_owner(owner: str) -> str | None:
    """`name` -> `@name`; an owner CODEOWNERS would not accept -> None."""
    owner = owner.strip()
    if owner and "@" not in owner:
        owner = "@" + owner
    return owner if OWNER.fullmatch(owner) else None


def _split(text: str) -> tuple[list[str], list[str]]:
    """The file's lines outside okl's block, and the lines inside it."""
    outside, inside, in_block = [], [], False
    for line in text.splitlines():
        if line.strip() == BEGIN:
            in_block = True
        elif line.strip() == END:
            in_block = False
        elif in_block:
            inside.append(line)
        else:
            outside.append(line)
    return outside, inside


def _entries(lines: list[str]) -> dict[str, list[str]]:
    """pattern -> owners, for each rule line (comments and blanks skipped; a later line wins)."""
    found: dict[str, list[str]] = {}
    for line in lines:
        words = line.split("#", 1)[0].split()
        if words:
            found[words[0].lstrip("/")] = words[1:]
    return found


def owned(text: str) -> dict[str, list[str]]:
    """The paths okl's block names, with their owners."""
    return _entries(_split(text)[1])


def merge(text: str, owner: str, paths: list[str]) -> tuple[str, list[str]]:
    """The file with okl's block naming `owner` for each path, and notes on what was left alone.

    A path a line outside the block already names is the team's: okl leaves it to that line,
    and says whose it is."""
    outside, _ = _split(text)
    theirs = _entries(outside)
    notes, mine = [], []
    for path in dict.fromkeys(p.lstrip("/") for p in paths):
        if path in theirs:
            notes.append(f"{path} is already owned by {' '.join(theirs[path]) or 'no one'} on a line of "
                         "its own; okl leaves it")
        else:
            mine.append(f"{path} {owner}")
    body = "\n".join(outside).rstrip("\n")
    block = "\n".join([BEGIN, *mine, END]) if mine else ""
    return (body + ("\n\n" if body and block else "") + block).strip("\n") + "\n", notes


def remove(text: str) -> str:
    """The file without okl's block; everything else exactly as it was."""
    outside, _ = _split(text)
    return "\n".join(outside).rstrip("\n") + "\n" if any(line.strip() for line in outside) else ""
