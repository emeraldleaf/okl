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
import subprocess
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


def _baseline_hits(receipts: list[Path]) -> Counter[str]:
    """Baseline reproductions per task across the given A/B receipts."""
    hits = Counter[str]()
    for receipt in receipts:
        for row in json.loads(receipt.read_text()).get("results", []):
            if row.get("arm") == "baseline":
                hits[row["task"]] += bool(row.get("reproduced"))
    return hits


def _listing(path: str, opening: str) -> str:
    """The sentence of a doc that starts with `opening`."""
    text = _flat(path)
    start = text.index(opening)
    return text[start:text.index(". ", start)]


# The words each bait task goes by in prose, specific enough not to match a neighbour.
_PROSE = {"idor_endpoint": "IDOR", "react_fetch": "React fetch", "rate_limiter": "rate limit"}


def test_the_defects_named_as_reproduced_all_reproduced_in_a_receipt():
    """A defect the docs list as reproduced must have reproduced at baseline in a receipt.

    For weeks README.md, evals/REPORT.md and the site listed "an IDOR" among the defects
    the A/B reproduced, and idor_endpoint read 0 at baseline in every one of the 13
    receipts (found 2026-10-10 by a review). The list is the claim readers repeat, so it
    is held to the receipts here, the same way the figures above are.
    """
    # ARRANGE — README's list speaks for every receipt; REPORT's sentence describes the
    # first sonnet run (ab-20260830-0003) only, so it is held to that run's rows.
    results = ROOT / "evals" / "results"
    every = _baseline_hits(sorted(results.glob("ab-*.json")))
    first = _baseline_hits([results / "ab-20260830-0003.json"])
    never_any = {task for task, hits in every.items() if hits == 0}
    never_first = {task for task, hits in first.items() if hits == 0}
    assert never_any | never_first <= set(_PROSE), \
        f"give the newly unreproduced task(s) a prose name in _PROSE: {(never_any | never_first) - set(_PROSE)}"

    # ACT — the one sentence in each doc that lists what reproduced.
    claims = {"README.md": (_listing("README.md", 'Every "reproduced" is'), never_any),
              "evals/REPORT.md": (_listing("evals/REPORT.md", 'So "baseline 33%" means'), never_first)}

    # ASSERT — neither names a task that did not reproduce in the runs it describes.
    for doc, (sentence, never) in claims.items():
        named = sorted(_PROSE[task] for task in never if _PROSE[task].lower() in sentence.lower())
        assert not named, f"{doc} lists {named} as reproduced, but no receipt it describes reproduced it: {sentence!r}"


def test_the_spa_tokens_figures_report_quotes_match_the_receipts():
    """REPORT's 2026-10-10 notes quote pooled spa_tokens figures; a new receipt must update them."""
    # ARRANGE — pool spa_tokens over every receipt, and over the documented instrument.
    pooled = {"all": [0, 0, 0, 0], "documented": [0, 0, 0, 0]}  # base hits, base n, briefed hits, briefed n
    for receipt in sorted((ROOT / "evals" / "results").glob("ab-*.json")):
        data = json.loads(receipt.read_text())
        documented = "sonnet" in data.get("generator", "") and "haiku" in data.get("judge", "")
        for row in data.get("results", []):
            if row.get("task") != "spa_tokens":
                continue
            i = 0 if row["arm"] == "baseline" else 2
            for key in ("all", "documented") if documented else ("all",):
                pooled[key][i] += bool(row["reproduced"]); pooled[key][i + 1] += 1
    report = _flat("evals/REPORT.md")

    # ASSERT — each quoted pair is the pooled one.
    for key, (bh, bn, rh, rn) in pooled.items():
        quoted = f"{bh}/{bn} → {rh}/{rn}"
        assert quoted in report, f"REPORT should quote spa_tokens {key} as {quoted!r}; update its 2026-10-10 notes"


def test_the_quarantined_july_figures_appear_nowhere_they_ship():
    """The 2026-07-17 A/B has no committed receipt (REPORT §7), so its figures are not quoted.

    Its "50% → 6%" and "75% → 8%" sat for weeks in a shipped seed record stated as
    "Measured" (seed/dotnet-canon.json, dec_sixth_surface), briefed to agents, while the
    diagram check that exists for exactly these figures scanned only docs/*.excalidraw.
    """
    pattern = re.compile(r"(50|75)\s?%\s?(→|->)\s?(6|8)\s?%")
    tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files", "seed", "src/okl", "docs", "README.md"],
                             capture_output=True, text=True, check=True).stdout.split()
    hits = [f for f in tracked if f.endswith((".json", ".md", ".py")) and pattern.search((ROOT / f).read_text())]
    assert not hits, f"quarantined 2026-07-17 figures quoted in {hits}; cite the committed series instead (REPORT)"
