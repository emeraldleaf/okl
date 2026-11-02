#!/usr/bin/env python3
"""Every `okl init` flag the README and the guides document exists in the CLI.

The check behind the `doc-init-flags` rule. It reads every sentence of README.md,
docs/GETTING-STARTED.md and docs/FROM-SCRATCH.md (#330) that mentions init and collects the init flags written there: those
inside an `okl init ...` command, and those written as a backticked flag of their own, the way
prose names one (`--no-claude`). A flag inside another command quoted in the same sentence
(`okl record --files ...`, `git push --no-verify`) is that command's, not init's, and a
bare flag counts only in a sentence where init is the sole okl command named. It fails
naming any flag `okl init --help` does not know. An earlier version read only text that began
with "okl init", so the guide's prose flags were never checked (review on #269).
"""
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
# Digits included, so a documented `--no-claude1` reads whole and fails rather than
# passing as `--no-claude` (review on #284).
FLAG = re.compile(r"--[a-z][a-z0-9-]+")
help_text = subprocess.run([sys.executable, "-m", "okl", "init", "--help"],
                           capture_output=True, text=True, cwd=REPO, check=True).stdout
flags: set[str] = set()
for doc in ("README.md", "docs/GETTING-STARTED.md", "docs/FROM-SCRATCH.md"):
    for unit in re.split(r"(?<=[.!?])\s+|\n\s*\n", (REPO / doc).read_text()):
        if not re.search(r"\binit\b", unit):
            continue
        for command in re.findall(r"okl init[^\n`]*", unit):
            flags.update(FLAG.findall(command))
        # A flag written on its own belongs to init only when init is the sole okl command
        # the sentence names; beside `okl verify`, a bare `--files` is verify's.
        if not re.search(r"`okl (?!init\b)\w+", unit):
            # The code spans, as backticks pair from the left: every odd piece between two
            # backticks, so a flag outside a span never counts and never shifts the pairing
            # (review on #284). Split, not matched as one pattern, which backtracked on an
            # unclosed backtick (SonarQube Cloud python:S8786).
            for span in unit.split("`")[1:-1:2]:
                if flag := FLAG.match(span):
                    flags.add(flag.group())
# Whole flag names, so a typo that is a prefix of a real flag (`--no-clau`) is caught.
known = set(FLAG.findall(help_text))
missing = sorted(flags - known)
if missing or not flags:
    sys.exit(f"documented but missing from `okl init --help`: {missing}")
print("INIT FLAGS EXIST", sorted(flags))  # noqa: T201 - a check script reports on stdout
