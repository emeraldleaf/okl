"""Owner-approved paths: the CODEOWNERS lines `okl init --owner` writes (#329).

A thesis an agent keeps updating needs a person's approval on each change, and only the
forge can enforce that. okl names the person as code owner of the paths that need them, here
`docs/THESIS.md` and every place GitHub looks for CODEOWNERS (so a new CODEOWNERS earlier in
GitHub's order cannot take over unowned), and a branch rule requiring code-owner review then
makes GitHub refuse the merge without them. Whether that rule is on, and binds the identity the
agent runs as, is `okl doctor`'s question (okl.protection), not this module's.

okl's lines sit in one marked block at the end of the file, moved back there on every run:
CODEOWNERS applies the last matching line, so a team rule above it (`* @team`) does not override
them, and `okl doctor` counts any rule after it as able to. The block is
spliced into the file's own text, in its own line endings, so every other byte stays as it was;
a path the team already owns on a line of its own is left to that line. Markers that do not
pair are refused, never guessed at. This module imports nothing from okl.
"""
from __future__ import annotations

import re
from pathlib import Path

# Where GitHub looks, in its order; the first that exists on the branch is the one it reads.
LOCATIONS = (Path(".github/CODEOWNERS"), Path("CODEOWNERS"), Path("docs/CODEOWNERS"))
BEGIN = "# okl: owner-approved paths, written by `okl init --owner` (#329). okl rewrites this block."
END = "# okl: end of owner-approved paths"
DEFAULT_PATHS = ("docs/THESIS.md",)
# A GitHub user (@name; an Enterprise Managed User's has an underscore, name_shortcode), team
# (@org/team) or email address, as CODEOWNERS accepts them.
OWNER = re.compile(r"@[A-Za-z0-9](?:[A-Za-z0-9_-]*[A-Za-z0-9])?(?:/[A-Za-z0-9._-]+)?|[^@\s]+@[^@\s]+\.[^@\s]+")
# A path okl will write as a CODEOWNERS pattern: one word, no comment, no negation (CODEOWNERS
# has none), so nothing a user passes can become a second line or an owner.
PATH = re.compile(r"[^\s#!\\][^\s#\\]*")


class MalformedBlockError(ValueError):
    """okl's markers in CODEOWNERS do not pair: okl will not guess where its block ends."""


def location(root: Path) -> Path:
    """The CODEOWNERS file GitHub reads here, or where okl creates one (relative to root)."""
    return next((p for p in LOCATIONS if (root / p).is_file()), LOCATIONS[0])


def owner_paths(owned: list[str]) -> list[str]:
    """What the owner approves: the thesis, every CODEOWNERS location, and the --owned paths."""
    return list(dict.fromkeys([*DEFAULT_PATHS, *(p.as_posix() for p in LOCATIONS), *owned]))


def normalise_owner(owner: str) -> str | None:
    """`name` -> `@name`; an owner CODEOWNERS would not accept -> None."""
    owner = owner.strip()
    if owner and "@" not in owner:
        owner = "@" + owner
    return owner if OWNER.fullmatch(owner) else None


def valid_path(path: str) -> bool:
    """Whether `path` can be written as one CODEOWNERS pattern and nothing else."""
    return bool(PATH.fullmatch(path))


def _newline(text: str) -> str:
    return "\r\n" if "\r\n" in text else "\n"


def block_span(text: str) -> tuple[int, int] | None:
    """Where okl's block is in `text` (from its first marker to the end of its last line), or
    None; MalformedBlockError when the markers are unmatched, repeated or out of order."""
    lines = text.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.strip() == BEGIN]
    ends = [i for i, line in enumerate(lines) if line.strip() == END]
    if not begins and not ends:
        return None
    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:
        raise MalformedBlockError("okl's markers in CODEOWNERS are unmatched or repeated")
    return sum(map(len, lines[:begins[0]])), sum(map(len, lines[:ends[0] + 1]))


def rules(text: str) -> list[tuple[str, list[str]]]:
    """Each rule line, in order, as (pattern, owners): comments stripped, as GitHub reads them."""
    found = []
    for line in text.splitlines():
        words = line.split("#", 1)[0].split()
        if words:
            found.append((words[0], words[1:]))
    return found


NOTE = "# okl checks: "     # a path okl left to a team's own line, noted so a clone without .okl/ checks it


def checked(text: str) -> list[str]:
    """Every path okl's block covers: its rules, and the paths it notes it left to a team's line."""
    span = block_span(text)
    if span is None:
        return []
    noted = [line.strip()[len(NOTE):].split()[0] for line in text[span[0]:span[1]].splitlines()
             if line.strip().startswith(NOTE) and line.strip()[len(NOTE):].split()]
    return list(dict.fromkeys([*owned(text), *noted]))


def owned(text: str) -> dict[str, list[str]]:
    """The paths okl's block names, with their owners (MalformedBlockError if its markers do not pair)."""
    span = block_span(text)
    return {} if span is None else {p.lstrip("/"): o for p, o in rules(text[span[0]:span[1]])}


def merge(text: str, owner: str, paths: list[str]) -> tuple[str, list[str]]:
    """The file with okl's block naming `owner` for each path, and notes on what was left alone.

    A path a line outside the block already names is the team's: okl leaves it to that line,
    and says whose it is. Raises MalformedBlockError rather than rewriting around unpaired markers."""
    wanted = list(dict.fromkeys(p.lstrip("/") for p in paths))
    span = block_span(text)
    nl = _newline(text)
    notes: list[str] = []
    if span is not None:
        # A line in okl's block that okl did not write (not one of its paths, or naming more than
        # one owner) is someone's: it is kept, moved just above the block, and said, never dropped.
        foreign = [line for line in text[span[0]:span[1]].splitlines()
                   if (words := line.split("#", 1)[0].split()) and (words[0].lstrip("/") not in wanted
                                                                    or len(words) != 2)]
        rest = remove(text)
        if foreign or rules(text[span[1]:]):
            # A rule after the block would win over it (CODEOWNERS applies the last match): the
            # block goes back at the end, every other byte as it was.
            body = rest if not rest or rest.endswith(("\n", "\r")) else rest + nl
            text, span = body + "".join(line + nl for line in foreign), None
            notes += [f"kept `{line.strip()}`, which was in okl's block, just above it" for line in foreign]
    outside = text if span is None else text[:span[0]] + text[span[1]:]
    theirs = {p.lstrip("/"): o for p, o in rules(outside)}
    mine, left = [], []
    for path in wanted:
        if path in theirs:
            notes.append(f"{path} is already owned by {' '.join(theirs[path]) or 'no one'} on a line of "
                         "its own; okl leaves it")
            left.append(f"{NOTE}{path}")
        else:
            mine.append(f"{path} {owner}")
    block = nl.join([BEGIN, *mine, *left, END]) + nl if mine or left else ""
    if span is not None:
        return (text[:span[0]] + block + text[span[1]:]) if block else remove(text), notes
    if not block:
        return text, notes
    body = text if not text or text.endswith(("\n", "\r")) else text + nl
    return body + (nl if body else "") + block, notes


def remove(text: str) -> str:
    """The file without okl's block and the blank line merge put before it; every other byte as
    it was (a file okl gave a final newline keeps it). MalformedBlockError on unpaired markers."""
    span = block_span(text)
    if span is None:
        return text
    before, after = text[:span[0]], text[span[1]:]
    nl = _newline(text)
    if before.endswith(nl + nl):
        before = before[:-len(nl)]
    elif before == nl:
        before = ""
    return before + after
