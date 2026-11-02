#!/usr/bin/env python3
"""Every guard okl relies on is held by a test: switch each one off, and a test must fail.

Reviews kept finding the same thing: a guard (a symlink refusal, a validation, a check that
something was read) that could be deleted with every test still passing, so nothing stopped the
next change from deleting it (the findings log's "covered only by a vacuous assertion", three
times; #329 part A had six such guards in one change). This switches each one off, one at a
time, runs the tests that cover it, and fails naming each guard no test caught.

Two kinds are switched off:
- every call to a guard function in the files GUARD_CALLS names, found by reading the code, so
  a guard added later is covered without anyone listing it: `_refuse_symlink(...)` becomes
  `False` and `_symlinked(...)` becomes `None`, which is what each returns when it lets the
  write through;
- each hand-written MUTATIONS entry, for a guard that is not a call (a branch, an allow-list).

Run from the repo root: `python3 ci/check-guard-mutations.py`. It edits each file in place and
restores it byte for byte before the next; it refuses to start on a file with uncommitted edits.
"""
from __future__ import annotations

import ast
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# file -> {guard function: the value its call is replaced with, which lets the write through}
GUARD_CALLS = {"src/okl/cli/install.py": {"_refuse_symlink": "False", "_symlinked": "None"}}
# (file, text, replacement, what switching it off means): guards that are not one call.
MUTATIONS: list[tuple[str, str, str, str]] = []
# The tests that cover these files, fastest catchers first; -x stops at the first failure.
TESTS = ["tests/test_symlink_guards.py", "tests/test_scaffold.py", "tests/test_okl.py"]


def call_sites(path: str, guards: dict[str, str]) -> list[tuple[int, int, int, int, str, str]]:
    """Each guard call in `path`: (start line, col, end line, end col, its source, its stand-in)."""
    tree = ast.parse((REPO / path).read_text())
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in guards:
            text = ast.get_source_segment((REPO / path).read_text(), node) or node.func.id
            sites.append((node.lineno, node.col_offset, node.end_lineno or node.lineno,
                          node.end_col_offset or 0, text, guards[node.func.id]))
    return sorted(sites)


def replace_span(source: str, site: tuple[int, int, int, int, str, str]) -> str:
    """`source` with one call (by line and column) replaced by its stand-in."""
    lines = source.splitlines(keepends=True)
    start = sum(map(len, lines[:site[0] - 1])) + len(lines[site[0] - 1].encode()[:site[1]].decode())
    end = sum(map(len, lines[:site[2] - 1])) + len(lines[site[2] - 1].encode()[:site[3]].decode())
    return source[:start] + site[5] + source[end:]


def caught(path: str, mutated: str, tests: list[str]) -> bool:
    """Whether a test fails with `path` holding `mutated`; the file is restored either way."""
    target = REPO / path
    original = target.read_bytes()
    target.write_text(mutated)
    try:
        env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests],
                           cwd=REPO, env=env, capture_output=True, text=True)
        return r.returncode != 0
    finally:
        target.write_bytes(original)


def main() -> int:
    """Switch each guard off in turn; exit 1 naming every one no test caught."""
    files = sorted({*GUARD_CALLS, *(m[0] for m in MUTATIONS)})
    dirty = subprocess.run(["git", "-C", str(REPO), "status", "--porcelain", "--", *files],
                           capture_output=True, text=True, check=True).stdout.strip()
    if dirty:
        sys.exit(f"GUARD MUTATIONS NOT RUN: commit or stash these first, they are edited in place:\n{dirty}")
    missed, total = [], 0
    for path, guards in GUARD_CALLS.items():
        source = (REPO / path).read_text()
        for site in call_sites(path, guards):
            total += 1
            if not caught(path, replace_span(source, site), TESTS):
                missed.append(f"{path}:{site[0]} `{site[4]}` -> {site[5]}")
    for path, text, replacement, label in MUTATIONS:
        source = (REPO / path).read_text()
        total += 1
        if source.count(text) != 1:
            missed.append(f"{path}: the guard for '{label}' is not found once; update MUTATIONS")
        elif not caught(path, source.replace(text, replacement), TESTS):
            missed.append(f"{path}: {label}")
    if missed:
        print(f"GUARD MUTATIONS MISSED {len(missed)} of {total}: no test fails with each of these off")  # noqa: T201
        print("\n".join(f"  {m}" for m in missed))  # noqa: T201
        return 1
    print(f"GUARD MUTATIONS CAUGHT {total} of {total}")  # noqa: T201 - a check script reports on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
