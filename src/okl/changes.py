"""What a change did to the files lessons name: `okl changes` (#398).

A lesson governs files through the paths in its `files` field. When a change adds a file, the
lessons that cover it are worth knowing before review. When it deletes or renames one, or moves
code out of it, an entry can go dead or keep pointing at the old place, and drift does not follow
renames. This step reads the change with git and nothing else: no model, and no writes. It lists
each event and, for the lessons this repo owns, proposes the `okl update` a person would confirm.

git's rename detection finds whole files that moved. Across this repository's merged pull requests
it found none, while code moved between files showed up only as matching blocks (#316 moved path
matching from drift.py to store.py). So a run of removed lines that reappears among another file's
added lines is reported as moved code too. It compares lines, not syntax, so it works in any
language.
"""
from __future__ import annotations

import json
import shlex
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from typing import Any

from .core import governing
from .store import RETIRED_STATUSES, Node, path_matches

WINDOW = 3            # consecutive lines that must match for a block to count as moved
MIN_MOVED = 5         # lines a block needs before it is reported as moved code
MIN_CHARS = 4         # letters or digits a line needs to count; a lone brace or `end` never does
NAMED_SHOWN = 10      # places still naming a removed path, listed before the count


class ChangesError(Exception):
    """git could not read the range asked for."""


@dataclass
class Renamed:
    """A file git paired with its new name, and how alike the two are (percent)."""
    old: str
    new: str
    similarity: int


@dataclass
class Moved:
    """Lines removed from `source` that reappear among the lines added to `dest`."""
    source: str
    dest: str
    lines: int


@dataclass
class Changes:
    """What git says a change did, before any lesson is read."""
    base: str
    head: str
    new: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    renamed: list[Renamed] = field(default_factory=list)
    moved: list[Moved] = field(default_factory=list)
    modified: int = 0
    head_files: list[str] = field(default_factory=list)
    named_in: dict[str, list[str]] = field(default_factory=dict)   # a removed path -> "file:line" still naming it


@dataclass
class Proposal:
    """A change to one lesson's files for a person to confirm. `files` is None when the only
    finding is an entry left with nothing to govern, which only the person can re-point."""
    id: str
    title: str
    was: str
    reasons: list[str]
    files: str | None


def _git(repo_dir: str, *args: str, ok: tuple[int, ...] = (0,)) -> str:
    try:
        p = subprocess.run(["git", "-C", repo_dir, "-c", "core.quotePath=false", *args],
                           capture_output=True, timeout=120)
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        raise ChangesError(f"git could not run: {e}") from e
    if p.returncode not in ok:
        raise ChangesError(p.stderr.decode("utf-8", "replace").strip() or f"git {args[0]} failed")
    return p.stdout.decode("utf-8", "surrogateescape")


def _default_bases(repo_dir: str) -> list[str]:
    """The remote's default branch, then main, then master."""
    try:
        found = [_git(repo_dir, "symbolic-ref", "--quiet", "refs/remotes/origin/HEAD").strip().removeprefix("refs/remotes/")]
    except ChangesError:
        found = []
    return found + ["origin/main", "main", "master"]


def resolve(base: str | None, head: str, repo_dir: str = ".") -> tuple[str, str]:
    """The two commits compared: the merge base of `base` and `head`, as a pull request's diff
    is, and `head`."""
    head_sha = _git(repo_dir, "rev-parse", "--verify", "--quiet", f"{head}^{{commit}}").strip()
    for candidate in [base] if base else _default_bases(repo_dir):
        try:
            return _git(repo_dir, "merge-base", candidate, head_sha).strip(), head_sha
        except ChangesError:
            if base:
                raise
    raise ChangesError("found no branch to compare with: pass --base <ref>")


def _name_status(base: str, head: str, repo_dir: str) -> tuple[list[str], list[str], list[Renamed], int]:
    """New, deleted and renamed files, and how many others changed. A copy counts as new."""
    raw = _git(repo_dir, "diff", "--name-status", "-z", "-M", "--no-ext-diff", base, head).split("\0")
    new: list[str] = []
    deleted: list[str] = []
    renamed: list[Renamed] = []
    modified, i = 0, 0
    while i < len(raw) and raw[i]:
        status = raw[i]
        if status[0] in "RC":
            old, path, i = raw[i + 1], raw[i + 2], i + 3
            if status[0] == "R":
                renamed.append(Renamed(old, path, int(status[1:] or 0)))
            else:
                new.append(path)
            continue
        path, i = raw[i + 1], i + 2
        if status[0] == "A":
            new.append(path)
        elif status[0] == "D":
            deleted.append(path)
        else:
            modified += 1
    return new, deleted, renamed, modified


def _unquote(name: str) -> str:
    """A path as git prints it in a diff header, quoted C-style when it holds special bytes."""
    if not (len(name) >= 2 and name[0] == name[-1] == '"'):
        return name
    body, out, i = name[1:-1], bytearray(), 0
    escapes = {"n": 10, "t": 9, '"': 34, "\\": 92, "a": 7, "b": 8, "f": 12, "r": 13, "v": 11}
    while i < len(body):
        if body[i] == "\\" and i + 1 < len(body):
            if body[i + 1] in "01234567":
                out.append(int(body[i + 1:i + 4], 8))
                i += 4
            else:
                out.append(escapes.get(body[i + 1], ord(body[i + 1])))
                i += 2
            continue
        out += body[i].encode("utf-8", "surrogateescape")
        i += 1
    return out.decode("utf-8", "surrogateescape")


def _side(header: str, prefix: str) -> str | None:
    """The path on one side of a `---`/`+++` line, or None for /dev/null. git ends a name that
    holds a space with a tab."""
    name = _unquote(header.rstrip("\t"))
    return None if name == "/dev/null" else name.removeprefix(prefix)


def _runs(diff: str) -> tuple[dict[str, list[list[str]]], dict[str, list[list[str]]]]:
    """Each file's runs of removed lines and of added lines, from a diff with no context."""
    removed: dict[str, list[list[str]]] = defaultdict(list)
    added: dict[str, list[list[str]]] = defaultdict(list)
    src: str | None = None
    dst: str | None = None
    sign: str | None = None
    run: list[str] = []
    in_header = False

    def flush() -> None:
        nonlocal run, sign
        if run and sign == "-" and src:
            removed[src].append(run)
        elif run and sign == "+" and dst:
            added[dst].append(run)
        run, sign = [], None

    for line in diff.split("\n"):
        if line.startswith("diff --git "):
            flush()
            src = dst = None
            in_header = True
        elif in_header:       # a removed line can start with "-- ", so headers are read only here
            if line.startswith("--- "):
                src = _side(line[4:], "a/")
            elif line.startswith("+++ "):
                dst = _side(line[4:], "b/")
            elif line.startswith("@@"):
                in_header = False
        elif line[:1] in ("+", "-"):
            if line[0] != sign:
                flush()
                sign = line[0]
            run.append(line[1:])
        else:                 # a new hunk, or git's "\ No newline at end of file"
            flush()
    flush()
    return removed, added


def _key(line: str) -> str | None:
    """A line as moves are compared, or None for one too slight to tell anything."""
    text = " ".join(line.split())
    return text if sum(ch.isalnum() for ch in text) >= MIN_CHARS else None


def _moves(removed: dict[str, list[list[str]]], added: dict[str, list[list[str]]], renamed: list[Renamed]) -> list[Moved]:
    """Runs of removed lines that reappear among another file's added lines. A renamed file's own
    edits are not moves."""
    within = {(r.old, r.new) for r in renamed}
    where: dict[tuple[str, ...], set[str]] = defaultdict(set)
    for dest, runs in added.items():
        for run in runs:
            keys = [k for k in map(_key, run) if k]
            for j in range(len(keys) - WINDOW + 1):
                where[tuple(keys[j:j + WINDOW])].add(dest)
    lines: dict[tuple[str, str], set[tuple[int, int]]] = defaultdict(set)
    for source, runs in removed.items():
        for r, run in enumerate(runs):
            keys = [k for k in map(_key, run) if k]
            for j in range(len(keys) - WINDOW + 1):
                for dest in where.get(tuple(keys[j:j + WINDOW]), ()):
                    if dest != source and (source, dest) not in within:
                        lines[(source, dest)].update((r, j + k) for k in range(WINDOW))
    found = [Moved(s, d, len(n)) for (s, d), n in lines.items() if len(n) >= MIN_MOVED]
    return sorted(found, key=lambda m: (-m.lines, m.source, m.dest))


def _named_in(paths: list[str], head: str, repo_dir: str) -> dict[str, list[str]]:
    """Where the committed tree at `head` still names each path, as file:line."""
    out = {}
    for path in paths:
        raw = _git(repo_dir, "grep", "-I", "-n", "-F", "--null", "-e", path, head, "--", ok=(0, 1))
        places = []
        for line in raw.splitlines():
            parts = line.split("\0")
            if len(parts) >= 3:
                places.append(f"{parts[0].removeprefix(head + ':')}:{parts[1]}")
        if places:
            out[path] = places
    return out


def read(base: str | None, head: str = "HEAD", repo_dir: str = ".") -> Changes:
    """What the change from the merge base of `base` and `head` to `head` did, read from git."""
    base_sha, head_sha = resolve(base, head, repo_dir)
    new, deleted, renamed, modified = _name_status(base_sha, head_sha, repo_dir)
    diff = _git(repo_dir, "diff", "-U0", "-M", "--no-color", "--no-ext-diff", "--src-prefix=a/",
                "--dst-prefix=b/", base_sha, head_sha)
    removed, added = _runs(diff)
    head_files = [p for p in _git(repo_dir, "ls-tree", "-r", "--name-only", "-z", head_sha).split("\0") if p]
    gone = deleted + [r.old for r in renamed]
    return Changes(base_sha, head_sha, new, deleted, renamed, _moves(removed, added, renamed), modified,
                   head_files, _named_in(gone, head_sha, repo_dir) if gone else {})


def _owned(n: Node, repo: str) -> bool:
    """A live lesson this repo owns that names files: an org lesson recorded elsewhere may name
    files in another repo, so only these get proposals (as drift.governs_nothing judges)."""
    return bool(n.files) and n.status not in RETIRED_STATUSES and (n.scope == f"repo:{repo}" or n.repo == repo)


def _proposal(n: Node, found: Changes) -> Proposal | None:
    """What this change suggests for one lesson's files, or None."""
    was = [e.strip() for e in (n.files or "").split(",") if e.strip()]

    def alive(entry: str) -> bool:
        return any(path_matches(entry, p) for p in found.head_files)

    files, reasons = list(was), []
    for r in found.renamed:
        for entry in [e for e in was if path_matches(e, r.old) and not path_matches(e, r.new)]:
            if alive(entry):
                reasons.append(f"`{r.old}` was renamed to `{r.new}`, which `{entry}` does not cover")
            else:
                files = [x for x in files if x != entry]
                reasons.append(f"`{r.old}` was renamed to `{r.new}`, and `{entry}` now matches nothing")
            files += [] if any(path_matches(e, r.new) for e in files) else [r.new]
    for m in found.moved:
        if any(path_matches(e, m.source) for e in was) and not any(path_matches(e, m.dest) for e in files):
            files.append(m.dest)
            reasons.append(f"{m.lines} lines moved from `{m.source}` to `{m.dest}`, which its files do not cover")
    for d in found.deleted:
        reasons.extend(f"`{d}` was deleted, and `{entry}` now matches nothing: re-point it, drop it, or retire the lesson"
                       for entry in was if path_matches(entry, d) and not alive(entry) and entry in files)
    if not reasons:
        return None
    return Proposal(n.id, n.title, n.files or "", reasons, ",".join(files) if files != was else None)


def report(found: Changes, nodes: list[Node], repo: str) -> dict[str, Any]:
    """The events with the lessons each touches: who governs each new file, and a proposal for
    each of this repo's lessons the change leaves pointing at the wrong place."""
    governs = {p: [f"[{n.id}] {n.title}" for n in sorted(governing(nodes, repo, {p}), key=lambda n: n.id)] for p in found.new}
    proposals = [p for p in (_proposal(n, found) for n in sorted(nodes, key=lambda n: n.id) if _owned(n, repo)) if p]
    return {"base": found.base, "head": found.head, "modified": found.modified,
            "new": [{"path": p, "governed_by": governs[p]} for p in found.new],
            "deleted": [{"path": p, "still_named_in": found.named_in.get(p, [])} for p in found.deleted],
            "renamed": [{**asdict(r), "still_named_in": found.named_in.get(r.old, [])} for r in found.renamed],
            "moved": [asdict(m) for m in found.moved],
            "proposals": [asdict(p) for p in proposals]}


def as_json(rep: dict[str, Any]) -> str:
    """The report for an agent."""
    return json.dumps(rep, indent=2) + "\n"


def _places(places: list[str]) -> str:
    more = f", and {len(places) - NAMED_SHOWN} more" if len(places) > NAMED_SHOWN else ""
    return f"still named in {', '.join(places[:NAMED_SHOWN])}{more}"


def render(rep: dict[str, Any]) -> str:
    """The report for a person."""
    head = f"(base {rep['base'][:7]}, head {rep['head'][:7]})"
    counts = [f"{len(rep[k])} {w}" for k, w in (("new", "new"), ("deleted", "deleted"), ("renamed", "renamed")) if rep[k]]
    counts += [f"{len(rep['moved'])} block(s) of moved code"] if rep["moved"] else []
    if not counts:
        return f"okl changes · nothing structural: {rep['modified']} file(s) edited in place, none new, deleted, renamed or moved {head}\n"
    lines = [f"okl changes · {', '.join(counts)}, {rep['modified']} edited in place {head}"]
    if rep["new"]:
        lines += ["", "New files"]
        for f in rep["new"]:
            lines.append(f"  {f['path']}")
            lines += [f"    governed by {g}" for g in f["governed_by"]]
    if rep["deleted"]:
        lines += ["", "Deleted"]
        lines += [f"  {f['path']}" + (f"   {_places(f['still_named_in'])}" if f["still_named_in"] else "") for f in rep["deleted"]]
    if rep["renamed"]:
        lines += ["", "Renamed"]
        lines += [f"  {r['old']} → {r['new']} ({r['similarity']}% alike)" + (f"   {_places(r['still_named_in'])}" if r["still_named_in"] else "")
                  for r in rep["renamed"]]
    if rep["moved"]:
        lines += ["", "Moved code"]
        lines += [f"  {m['lines']} lines from {m['source']} to {m['dest']}" for m in rep["moved"]]
    if rep["proposals"]:
        lines += ["", "Proposals for this repo's lessons: each is yours to confirm, and nothing has been written"]
        for p in rep["proposals"]:
            lines.append(f"  [{p['id']}] {p['title']}")
            lines += [f"    - {r}" for r in p["reasons"]]
            if p["files"] is not None:
                lines.append(f"    → okl update {shlex.quote(p['id'])} --files {shlex.quote(p['files'])}")
        lines.append("  Changing a lesson's files clears its proof: run its check again with okl verify.")
    return "\n".join(lines) + "\n"
