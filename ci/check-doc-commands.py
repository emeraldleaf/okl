#!/usr/bin/env python3
"""Every `okl` command the docs write exists, with every flag it is given (#314).

`ci/check-init-flags.py` held `okl init`'s flags to the CLI in three docs; nothing held the
rest. This reads every `okl ...` command in the README, `docs/` and the overview sheets (in
code spans, fenced blocks and `<code>`) and walks argparse itself: each subcommand, nested ones
too (`okl warm stop`), must exist, and each `--flag` must be one that command takes. Dated
records are left out because an old flag there is history, not a claim: `docs/posts/`, the
decision records, receipts, the CHANGELOG and the REPORT.

A command the docs name as not built yet is listed in PLANNED with its issue; a placeholder
(`okl <command>`, `okl ...`) names no command and is skipped.
"""
from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from okl.cli.parser import build_parser  # noqa: E402 - the path above makes this checkout's okl importable

# Commands the docs name as not built yet, with the issue that tracks them.
PLANNED = {"okl log": "#129", "okl explain": "#129"}
# What may run okl as a command: a wrapper before it is dropped (`python3 -m okl`, `uv run okl`).
WRAPPERS = (("python", "-m"), ("python3", "-m"), ("uv", "run"), ("exec",), ("time",), ("sudo",))


def docs() -> dict[str, str]:
    """The committed docs a reader is told things in (CLAUDE.md: audits read the repo)."""
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "README.md", "docs"],
                         capture_output=True, text=True, check=True).stdout.split()
    keep = [f for f in out if f.endswith((".md", ".html"))
            and not f.startswith(("docs/posts/", "docs/decisions/")) and "RECEIPT" not in f]
    return {f: (REPO / f).read_text() for f in keep}


def code_in(text: str) -> list[str]:
    """The code a doc shows: fenced blocks, inline spans outside them, and HTML <code>."""
    fenced = re.findall(r"```[^\n]*\n(.*?)```", text, re.S)
    outside = re.sub(r"```.*?```", "", text, flags=re.S)
    spans = re.findall(r"`([^`\n]+)`", outside)
    html = [re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<code>(.*?)</code>", text, re.S)]
    return fenced + spans + html


def commands(code: str) -> list[list[str]]:
    """Each okl command in a piece of code, as its words after `okl`."""
    found = []
    for line in code.replace("\\\n", " ").splitlines():
        line = re.sub(r"(^|\s)#.*", "", line)          # a shell comment is prose
        try:
            # Operators split commands only outside quotes: a `--run "a && b | c"` is one word.
            lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
            lexer.whitespace_split = True
            tokens = list(lexer)
        except ValueError:                               # an unclosed quote: split plainly
            tokens = line.split()
        segments, current = [], []
        for token in tokens:
            if token and set(token) <= set("&|;()$"):
                segments.append(current); current = []
            else:
                current.append(token)
        for words in [*segments, current]:
            while words and (words[0] in ("$", ">") or re.fullmatch(r"[A-Z_][A-Z0-9_]*=.*", words[0])):
                words = words[1:]                        # a prompt, or an environment setting
            for wrapper in WRAPPERS:
                if tuple(words[:len(wrapper)]) == wrapper:
                    words = words[len(wrapper):]
            if words and (words[0] == "okl" or words[0].endswith("/okl")):
                found.append(words[1:])
    return found


def _subparsers(p: argparse.ArgumentParser) -> argparse._SubParsersAction | None:
    return next((a for a in p._actions if isinstance(a, argparse._SubParsersAction)), None)


def problems(files: dict[str, str]) -> tuple[list[str], int]:
    """Every command or flag the docs write that the CLI does not have, and how many commands
    were checked."""
    root, bad, checked = build_parser(), [], 0
    for name, text in files.items():
        for code in code_in(text):
            for words in commands(code):
                parser, path = root, ["okl"]
                while words and (sub := _subparsers(parser)) and not words[0].startswith("-"):
                    word = words[0]
                    if word in sub.choices:
                        parser = sub.choices[word]; path.append(words.pop(0))
                        continue
                    if re.fullmatch(r"[a-z][a-z0-9-]*", word) and " ".join([*path, word]) not in PLANNED:
                        bad.append(f"{name}: `{' '.join([*path, word])}` is not a command")
                    words = []                           # a placeholder or a planned command
                    break
                else:
                    checked += 1
                known = {o for a in parser._actions for o in a.option_strings}
                for word in words:
                    flag = word.strip("[]().,:`").split("=")[0]
                    if flag.startswith("--") and len(flag) > 2 and flag not in known:
                        bad.append(f"{name}: `{' '.join(path)}` has no {flag}")
    return sorted(set(bad)), checked


if __name__ == "__main__":
    found, checked = problems(docs())
    if found or not checked:
        sys.exit("DOC COMMANDS THE CLI DOES NOT HAVE:\n  " + "\n  ".join(found or ["(no command found)"]))
    print("DOC COMMANDS EXIST", checked, "commands")  # noqa: T201 - a check script reports on stdout
