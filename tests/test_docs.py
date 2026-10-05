"""The figures the docs quote are held to what they describe.

The corpus counts must match seed/, and the briefing sizes must match the briefing-size
receipt the README cites. On 2026-10-04 the README and the MCP `okl_check` description
had disagreed for weeks about the full briefing (~1,650 tokens against ~2,300), and the
corpus counts in README.md and CLAUDE.md had to be edited by hand three times in one day.
Nothing failed. These tests make each of those a CI failure that names its fix.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _flat(path: str) -> str:
    """A doc's text with every run of whitespace collapsed, so a wrapped line still matches."""
    return " ".join((ROOT / path).read_text().split())


def _seed_counts() -> tuple[int, Counter[str]]:
    """How many records the bundled seed packs hold, in total and by type."""
    total, types = 0, Counter[str]()
    for pack in sorted((ROOT / "seed").glob("*.json")):
        data = json.loads(pack.read_text())
        nodes = data["nodes"] if isinstance(data, dict) else data
        total += len(nodes)
        types.update(n["type"] for n in nodes)
    return total, types


def test_readme_and_claude_md_count_the_seed_corpus_as_it_is():
    """README.md and CLAUDE.md state the corpus size; adding a lesson must update both."""
    # ARRANGE — the corpus as it is now.
    total, types = _seed_counts()

    # ACT — the counts the docs state.
    readme = re.search(r"In the (\d+)-record corpus in \[seed/\]\(seed/\) it is mostly not that: "
                       r"\*\*(\d+) Rules, (\d+) Decisions and (\d+) Gates against (\d+) Defects\*\*",
                       _flat("README.md"))
    claude = re.search(r"curated (\d+)-node corpus", _flat("CLAUDE.md"))

    # ASSERT — (1) both sentences still exist, or this test is checking nothing;
    # (2) they match seed/. AGENTS.md is held to CLAUDE.md by the mirror test.
    assert readme and claude, "a corpus sentence moved; move this test's pattern with it"
    stated = tuple(int(g) for g in readme.groups())
    actual = (total, types["Rule"], types["Decision"], types["Gate"], types["Defect"])
    assert stated == actual, f"README.md says {stated}, seed/ holds {actual} (records, Rules, Decisions, Gates, Defects)"
    assert int(claude.group(1)) == total, f"CLAUDE.md says {claude.group(1)} records, seed/ holds {total}"


def test_quoted_briefing_sizes_match_the_receipt_the_readme_cites():
    """Every briefing size the README, the MCP description and the diagram quote comes
    from one receipt, and that receipt measured the corpus as it is now."""
    # ARRANGE — the one receipt the README cites, and what it measured.
    readme = _flat("README.md")
    cited = set(re.findall(r"evals/results/(briefing-size-\d{8}-\d{4}\.json)", readme))
    assert len(cited) == 1, f"the README should cite exactly one briefing-size receipt, found {sorted(cited)}"
    receipt = json.loads((ROOT / "evals" / "results" / cited.pop()).read_text())
    tokens = {name: size["tokens"] for name, size in receipt["briefings"].items()}
    full = tokens["full (agent format, default --limit 12)"]
    actions = {n: tokens[f"--format actions --limit {n}"] for n in (3, 5, 8, 12)}
    compact5 = tokens["compact, --limit 5"]
    measured = int(re.search(r"(\d+) records", receipt["store"]).group(1))
    total, _ = _seed_counts()

    # ASSERT — (1) the receipt measured today's corpus. A lesson added since makes the
    # README's "every bundled seed pack" untrue until the sizes are measured again.
    assert measured == total, (f"the receipt measured {measured} records and seed/ now holds {total}: "
                               "run python3 evals/briefing_size.py and cite the new receipt in README.md")
    # (2) the README quotes that receipt's figures, wherever it states one.
    for claim in (
        f"every bundled seed pack, {measured} records",
        f"**~{full:,} tokens** at the default `--limit 12`, down to **~{actions[3]}** for only the action list",
        f"~{actions[3]}-token version",
        f"A full briefing costs roughly **{full:,} tokens**",
        f"every bundled seed pack ({measured} records)",
        f"~{actions[3]} tokens at `--limit 3`, ~{actions[5]} at `--limit 5`, ~{actions[8]} at "
        f"`--limit 8` and ~{actions[12]} at `--limit 12`, against ~{full:,} for the full briefing",
        f"Together that is ~{compact5} tokens instead of ~{full:,}",
    ):
        assert claim in readme, f"README.md no longer says: {claim}"
    # (3) so does the MCP tool description an agent reads.
    mcp = f"roughly {actions[3]} tokens at limit=3 and {actions[12]} at the default limit of 12, versus ~{full:,}"
    assert mcp in _flat("src/okl/mcp_server.py"), f"the okl_check description no longer says: {mcp}"
    # (4) and so do the diagram's source and its render.
    for doc in ("docs/okl-how-it-works.excalidraw", "docs/okl-how-it-works.svg"):
        line = f"roughly {actions[3]} tokens at limit=3, against ~{full:,} for the"
        assert line in (ROOT / doc).read_text(), f"{doc} no longer says: {line}"
