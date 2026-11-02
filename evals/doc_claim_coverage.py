#!/usr/bin/env python3
"""How many of the docs a reader is told things in have a claim check reading them (#314).

A doc counts as covered when at least one check reads a claim in it: a watched lesson that
governs it (okl-drift.json), `ci/check-init-flags.py` (its three docs), the figures test in
tests/test_docs.py (a doc with a size or latency figure), or `ci/check-doc-commands.py` (a doc
with an okl command it checked). "Before" is without the command gate, "after" with it. A link
or orphan gate is not a claim check: it reads that a link resolves, not that a claim is true.

Two lessons govern every doc (agent-neutral wording, positioning), so by docs alone the share
was whole before the gate and says little. The claim-level line counts what the gate adds: the
okl commands whose subcommand and flags a check reads, before (`okl init` in check-init-flags'
three docs) and after (every command the gate reads).

    python3 evals/doc_claim_coverage.py > evals/results/doc-claim-coverage-YYYYMMDD.txt
"""
from __future__ import annotations

import fnmatch
import importlib.util
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("check_doc_commands", REPO / "ci" / "check-doc-commands.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)

INIT_FLAG_DOCS = {"README.md", "docs/GETTING-STARTED.md", "docs/FROM-SCRATCH.md"}
FIGURE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s?(ms|MB|GB)\b")   # tests/test_docs.py's
FIGURE_DOCS = re.compile(r"README\.md|docs/(?!posts/).*\.md|docs/overview/.*\.html")


def governs(pattern: str, doc: str) -> bool:
    """Whether a lesson's `files` entry covers a doc: the path, a directory, or a glob."""
    pattern = pattern.strip()
    return doc == pattern or (pattern.endswith("/") and doc.startswith(pattern)) or fnmatch.fnmatch(doc, pattern)


def main() -> None:
    """Print the coverage, then each doc with the checks that read it."""
    docs = gate.docs()
    rules = json.loads((REPO / "okl-drift.json").read_text())["rules"]
    rows, before, after, init_before, all_after = [], 0, 0, 0, 0
    for name, text in sorted(docs.items()):
        checks = [f"lesson {r['id']}" for r in rules
                  if any(governs(p, name) for p in (r.get("files") or "").split(","))]
        if name in INIT_FLAG_DOCS:
            checks.append("check-init-flags")
        if FIGURE_DOCS.fullmatch(name) and FIGURE.search(text):
            checks.append("figures test")
        commands = gate.problems({name: text})[1]           # the commands the gate checked here
        all_after += commands
        if name in INIT_FLAG_DOCS:
            init_before += sum(1 for code in gate.code_in(text) for words in gate.commands(code)
                               if words[:1] == ["init"])
        before += bool(checks)
        if commands:
            checks.append(f"command gate ({commands})")
        after += bool(checks)
        rows.append(f"{name:<58} {', '.join(checks) or '-'}")
    total = len(docs)
    print(f"docs read: {total} (README, docs/ and the overview sheets; dated records left out)")
    print(f"covered before the command gate: {before} of {total} ({before / total:.0%})")
    print(f"covered after:                   {after} of {total} ({after / total:.0%})")
    print(f"okl commands whose flags a check reads: before {init_before} (okl init, three docs), "
          f"after {all_after} (every command, every doc read)")
    print()
    print("\n".join(rows))


if __name__ == "__main__":
    main()
