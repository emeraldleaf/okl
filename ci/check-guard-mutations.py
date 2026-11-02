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
MUTATIONS: list[tuple[str, str, str, str]] = [
    # okl doctor's owner check (#329): each condition it must read before it says "enforced".
    ("src/okl/protection.py", '        if [x.lower() for x in who] != [owner.lower()]:',
     '        if False:', "a line in okl's block that does not name the owner alone"),
    ("src/okl/protection.py", '    if after := codeowners.rules(text[span[1]:]):', '    if after := []:',
     "a rule after okl's block"),
    ("src/okl/protection.py", '    if odd := sorted({repr(c) for c in text if c in ODD_SPACE}):', '    if odd := []:',
     "a character Python and GitHub may split differently"),
    ("src/okl/protection.py", '        elif can != "never":', '        elif can not in ("never", "exempt"):',
     "a bypass value other than never"),
    ("src/okl/protection.py", '        elif actors:', '        elif False:', "a ruleset's bypass list"),
    ("src/okl/protection.py", '    if stale_dismissed is not True:', '    if not stale_dismissed:',
     "dismissing stale approvals, as true itself"),
    ("src/okl/protection.py", '    if count == 0:', '    if False:', "a rule requiring 0 approvals"),
    ("src/okl/protection.py", '    if viewer not in SAFE_ROLES:', '    if False:', "the allow-list of roles"),
    ("src/okl/protection.py", '    if not owner.startswith("@"):\n        return None',
     '    if not owner.startswith("@"):\n        return False', "an email owner, not tied to this identity"),
    ("src/okl/protection.py", '    if status == 404:\n        return False\n    state',
     '    if True:\n        return False\n    state', "a team owner's membership"),
    ("src/okl/protection.py", '        if status != 200 or not isinstance(content, str):',
     '        if not isinstance(content, str):', "the status of the CODEOWNERS read"),
    ("src/okl/protection.py", '    unread = [what for gap, what in ((rules_unread, f"the rulesets on {branch}"),',
     '    unread = [what for gap, what in ((False, f"the rulesets on {branch}"),', "unread rulesets as unread"),
    ("src/okl/protection.py", '        if not glob and candidate == core:\n            return "yes"',
     '        if False:\n            return "yes"', "a plain CODEOWNERS name matching at any depth"),
    # okl init --owner: what it writes, and refuses.
    ("src/okl/codeowners.py", '    if len(begins) != 1 or len(ends) != 1 or ends[0] < begins[0]:', '    if False:',
     "unpaired block markers"),
    ("src/okl/codeowners.py", '        if foreign or rules(text[span[1]:]):', '        if foreign:',
     "moving okl's block back last"),
    ("src/okl/codeowners.py", '            left.append(f"{NOTE}{path}")', '            pass',
     "noting a path left to a team's line"),
    ("src/okl/cli/install.py", '    if bad:\n        print(f"! --owned', '    if False:\n        print(f"! --owned',
     "validating --owned"),
    ("src/okl/cli/health.py", '    for ref in ("HEAD", "refs/remotes/origin/HEAD"):', '    for ref in ("HEAD",):',
     "doctor reading the default branch's CODEOWNERS"),
]
# The tests that cover these files, fastest catchers first; -x stops at the first failure.
TESTS = ["tests/test_symlink_guards.py", "tests/test_owner_paths.py", "tests/test_scaffold.py", "tests/test_okl.py"]


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


def caught(path: str, mutated: str, tests: list[str]) -> int:
    """pytest's exit with `path` holding `mutated` (1: a test failed), or -1 when the mutated
    module does not import, which is a broken mutation and no evidence of a test. The import is
    tried first because pytest's exit cannot tell them apart: a test that runs okl in a
    subprocess fails, exit 1, on an import error too. The file is restored either way."""
    target = REPO / path
    original = target.read_bytes()
    target.write_text(mutated)
    try:
        env = {**os.environ, "PYTHONPATH": str(REPO / "src")}
        module = path.removeprefix("src/").removesuffix(".py").replace("/", ".")
        if subprocess.run([sys.executable, "-c", f"import {module}"], cwd=REPO, env=env,
                          capture_output=True).returncode != 0:
            return -1
        r = subprocess.run([sys.executable, "-m", "pytest", "-x", "-q", "-p", "no:cacheprovider", *tests],
                           cwd=REPO, env=env, capture_output=True, text=True)
        return r.returncode
    finally:
        target.write_bytes(original)


def _why(code: int) -> str:
    """Why a mutation counts as missed: no test failed, or the mutated code did not run."""
    if code == -1:
        return " (the mutated module does not import: fix the mutation)"
    return "" if code == 0 else f" (pytest exit {code}: the tests did not run)"


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
            code = caught(path, replace_span(source, site), TESTS)
            if code != 1:
                missed.append(f"{path}:{site[0]} `{site[4]}` -> {site[5]}" + _why(code))
    for path, text, replacement, label in MUTATIONS:
        source = (REPO / path).read_text()
        total += 1
        if source.count(text) != 1:
            missed.append(f"{path}: the guard for '{label}' is not found once; update MUTATIONS")
        elif (code := caught(path, source.replace(text, replacement), TESTS)) != 1:
            missed.append(f"{path}: {label}" + _why(code))
    if missed:
        print(f"GUARD MUTATIONS MISSED {len(missed)} of {total}: no test fails with each of these off")  # noqa: T201
        print("\n".join(f"  {m}" for m in missed))  # noqa: T201
        return 1
    print(f"GUARD MUTATIONS CAUGHT {total} of {total}")  # noqa: T201 - a check script reports on stdout
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
