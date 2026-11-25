"""The figures the docs quote are held to what they describe.

The corpus counts must match seed/, and the briefing sizes must match the briefing-size
receipt the README cites. On 2026-10-04 the README and the MCP `okl_check` description
had disagreed for weeks about the full briefing (~1,650 tokens against ~2,300), and the
corpus counts in README.md and CLAUDE.md had to be edited by hand three times in one day.
Nothing failed. These tests make each of those a CI failure that names its fix.
"""
from __future__ import annotations

import ast
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
    """Every briefing size the README, the MCP description and the anatomy sheet quote comes
    from one receipt, and that receipt measured the corpus as it is now."""
    # ARRANGE — the one receipt the README cites, and what it measured.
    readme = _flat("README.md")
    cited = set(re.findall(r"evals/results/(briefing-size-\d{8}-\d{4}\.json)", readme))
    assert len(cited) == 1, f"the README should cite exactly one briefing-size receipt, found {sorted(cited)}"
    receipt = json.loads((ROOT / "evals" / "results" / cited.pop()).read_text())
    tokens = {name: size["tokens"] for name, size in receipt["briefings"].items()}
    full = tokens["full (agent format, default decision: tiered, at most 5 in full)"]
    calibrated = tokens["full (agent format, --decision calibrated, at most 5)"]
    floor = tokens["full (agent format, --decision floor, --limit 12)"]
    actions = {n: tokens[f"--format actions --limit {n}"] for n in (3, 5, 8, 12)}
    compact3 = tokens["compact, --limit 3"]
    measured = int(re.search(r"(\d+) records", receipt["store"]).group(1))
    total, _ = _seed_counts()

    # ASSERT — (1) the receipt measured today's corpus. A lesson added since makes the
    # README's "every bundled seed pack" untrue until the sizes are measured again.
    assert measured == total, (f"the receipt measured {measured} records and seed/ now holds {total}: "
                               "run python3 evals/briefing_size.py and cite the new receipt in README.md")
    # (2) the README quotes that receipt's figures, wherever it states one.
    for claim in (
        f"every bundled seed pack, {measured} records",
        f"**~{full:,} tokens** by default on one representative task (five lessons in full, twelve named in a "
        f"line; ~{calibrated:,} under `--decision calibrated`, ~{floor:,} under `--decision floor`)",
        f"Down to **~{actions[3]}** for only the action list",
        f"~{actions[3]}-token version",
        f"A full briefing costs roughly **{full:,} tokens** on the measurement above (~{calibrated:,} for the line "
        f"alone, ~{floor:,} under the floor's",
        f"every bundled seed pack ({measured} records)",
        f"the action list alone is ~{actions[3]} tokens at `--limit 3`, ~{actions[5]} at `--limit 5` and "
        f"~{actions[12]:,} at `--limit 12` (its one-line entries follow the limit), against ~{full:,} for the "
        "full briefing",
        f"Together that is ~{compact3} tokens instead of ~{full:,}",
    ):
        assert claim in readme, f"README.md no longer says: {claim}"
    # (3) so does the MCP tool description an agent reads.
    mcp = f"roughly {actions[3]} tokens at limit=3 and {actions[5]} at limit=5, versus ~{full:,} for the full briefing"
    assert mcp in _flat("src/okl/mcp_server.py"), f"the okl_check description no longer says: {mcp}"
    # (4) and so does the anatomy sheet's "Under the hood" panel.
    sheet = "docs/overview/okl-anatomy.html"
    assert f"about {full:,} tokens" in (ROOT / sheet).read_text(), f"{sheet} no longer says: about {full:,} tokens"
    # (5) The median on real prompts both quote is the tiered row of the held-out size receipt
    # (REPORT §4y), rounded to ten.
    sized = (ROOT / "evals" / "results" / "real-20261102-heldout-size.txt").read_text()
    median = int(re.search(r"task prompts.*?\n.*?\n\s+floor.*?\n.*?\n\s+tiered\s+(\d+)", sized, re.S).group(1))
    assert f"the median is **~{round(median, -1)}**" in readme, f"README.md no longer quotes the median {median}"
    assert f"a median of about {round(median, -1)} on real prompts" in (ROOT / sheet).read_text()


def _authored_tasks() -> set[str]:
    """The eight authored task ids. Receipts on other instruments (REPORT §4r's held-out
    rephrasings, ids like "idor_endpoint/ticket") are not the series the docs describe."""
    return {json.loads(line)["id"] for line in (ROOT / "evals" / "tasks.jsonl").read_text().splitlines() if line.strip()}


def _series_receipts() -> list[Path]:
    """The A/B receipts of the series the docs describe: no briefing against the live briefing.
    A receipt whose arms are anything else measures another treatment (§4r's indexed arm, §4aa's
    full and line arms) and is pooled with nothing here; counting its arms as "briefed" would
    move the published figures for a reason they do not describe."""
    out = []
    for receipt in sorted((ROOT / "evals" / "results").glob("ab-*.json")):
        arms = {row["arm"] for row in json.loads(receipt.read_text()).get("results", [])}
        if arms <= {"baseline", "briefed"}:
            out.append(receipt)
    return out


def _baseline_hits(receipts: list[Path]) -> Counter[str]:
    """Baseline reproductions per authored task across the given A/B receipts."""
    hits = Counter[str]()
    authored = _authored_tasks()
    for receipt in receipts:
        for row in json.loads(receipt.read_text()).get("results", []):
            if row.get("arm") == "baseline" and row["task"] in authored:
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
    every = _baseline_hits(_series_receipts())
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
    for receipt in _series_receipts():
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


POOLED_RECEIPTS = ["ab-20260830-0003", "ab-20260901-0133", "ab-20260901-1238", "ab-20260902-0538",
                   "ab-20260903-0157", "ab-20260903-1214", "ab-20260903-1323"]
# The launch posts of 2026-10-12 quoted the pool with §4i's run added; §4i pre-registered its
# layout change as a new series, so finding 7 reports that figure beside the pool (#265).
LAUNCH_POST_RECEIPTS = [*POOLED_RECEIPTS, "ab-20260926-0528"]


# REPORT §4j counts this sample as unevaluable: the generator returned a plan, not code, and
# the receipt, written before the harness could say so (#164), scores it clean.
PLAN_ONLY = {("ab-20261010-2314", "idor_endpoint", "briefed", 1)}


def _pool(names):
    """Unbriefed hits/n and briefed hits/n over the named receipts' judged samples."""
    out = [0, 0, 0, 0]
    for name in names:
        for row in json.loads((ROOT / "evals" / "results" / f"{name}.json").read_text())["results"]:
            if row.get("unevaluable") or (name, row["task"], row["arm"], row.get("sample")) in PLAN_ONLY:
                continue
            i = 0 if row["arm"] == "baseline" else 2
            out[i] += bool(row["reproduced"]); out[i + 1] += 1
    return out


def test_the_pooled_launch_figure_is_recomputed_from_its_receipts():
    """The launch posts quote 42% against 7% and send readers to the repo for it; REPORT §5
    finding 7 names the seven receipts, and every figure it gives is recomputed here."""
    # ARRANGE — the pool as REPORT defines it, the same without the reverted §4d run, the
    # eight-run figure the launch posts quoted, and every receipt on the documented
    # instrument with eight tasks and three samples.
    documented = []
    for receipt in _series_receipts():
        data = json.loads(receipt.read_text())
        rows = data.get("results", [])
        if ("sonnet" in data.get("generator", "") and "haiku" in data.get("judge", "")
                and len({r["task"] for r in rows}) == 8 and max(r.get("sample", 0) for r in rows) == 2):
            documented.append(receipt.stem)
    report = _flat("evals/REPORT.md")

    # ASSERT — each quoted pair is the recomputed one, and every receipt it names exists.
    assert set(LAUNCH_POST_RECEIPTS) <= set(documented), "a pooled receipt is missing or off-instrument"
    for names in (POOLED_RECEIPTS, [n for n in POOLED_RECEIPTS if n != "ab-20260902-0538"],
                  LAUNCH_POST_RECEIPTS, documented):
        bh, bn, rh, rn = _pool(names)
        quoted = f"{bh} of {bn}"
        assert quoted in report and f"{rh} of {rn}" in report, (
            f"REPORT §5 finding 7 should quote {bh} of {bn} against {rh} of {rn} for {len(names)} receipts")
    # The anatomy sheet quotes the seven-run pool too, and names every receipt in it.
    sheet = (ROOT / "docs" / "overview" / "okl-anatomy.html").read_text()
    bh, bn, rh, rn = _pool(POOLED_RECEIPTS)
    for figure in (f"{bh} of {bn} unbriefed", f"{rh} of {rn} briefed", f"{round(100 * bh / bn)}%", f"{round(100 * rh / rn)}%"):
        assert figure in sheet, f"docs/overview/okl-anatomy.html should say {figure}"
    assert all(name in sheet for name in POOLED_RECEIPTS), "the anatomy sheet must name every pooled receipt"


def _sentence_containing(path: str, phrase: str) -> str:
    """The sentence of a doc that contains `phrase`."""
    text = _flat(path)
    at = text.index(phrase)
    return text[text.rfind(". ", 0, at) + 2:text.index(". ", at)]


def _arm_counts(receipts: list[Path]) -> dict[str, list[int]]:
    """Per task: [unbriefed hits, unbriefed n, briefed hits, briefed n] over the judged samples."""
    counts: dict[str, list[int]] = {}
    authored = _authored_tasks()
    for receipt in receipts:
        for row in json.loads(receipt.read_text()).get("results", []):
            # Only the two arms the sentence describes; an indexed arm (§4r) is another treatment.
            if (row.get("reproduced") is None or row.get("unevaluable") or row["task"] not in authored
                    or row["arm"] not in ("baseline", "briefed")):
                continue
            cell = counts.setdefault(row["task"], [0, 0, 0, 0])
            i = 0 if row["arm"] == "baseline" else 2
            cell[i] += bool(row["reproduced"]); cell[i + 1] += 1
    return counts


def test_the_never_reproduced_sentence_counts_match_the_receipts():
    """README's sentence on the tasks that never reproduced unbriefed is held to every receipt.

    It said three tasks, 27–33 unbriefed samples each, and a rate limiter briefed 2 of 30,
    for eleven days after §4m's receipt had the rate limiter reproduce unbriefed and the
    sample counts had passed 40 (found 2026-10-22 by an independent verification).
    """
    # ARRANGE — every task's arm counts over every receipt, and the sentence that states them.
    counts = _arm_counts(_series_receipts())
    never = {task for task, cell in counts.items() if cell[0] == 0}
    assert never <= set(_PROSE), f"give the task(s) a prose name in _PROSE: {never - set(_PROSE)}"
    sentence = _sentence_containing("README.md", "have never reproduced without the briefing")
    clause, _, rest = sentence.partition(";")

    # ASSERT — the clause names exactly the never-reproduced tasks and their sample range, and
    # the rest quotes the counts of every named task that did reproduce.
    for task, name in _PROSE.items():
        assert (name.lower() in clause.lower()) == (task in never), f"{name!r} in {clause!r} is wrong"
    lo, hi = min(counts[t][1] for t in never), max(counts[t][1] for t in never)
    assert f"({lo}–{hi} unbriefed samples each)" in clause, f"README should say ({lo}–{hi} unbriefed samples each)"
    for task in set(_PROSE) - never:
        bh, bn, rh, rn = counts[task]
        assert f"{bh} of {bn}" in rest and f"{rh} of {rn}" in rest, \
            f"README should quote {_PROSE[task]} as {bh} of {bn} unbriefed and {rh} of {rn} briefed"


# Every size or latency the docs publish, with each receipt line it stands for: the figure is
# every such line's number at the precision the doc quotes. "95 ms" once cited a receipt that
# said 170.7, and "249 MB" and "about 80 MB" were never what okl's loaders fetch (review on
# #300). One string can stand for two measurements, so a figure lists every receipt line it
# quotes, and each is held (CI reviewer on #307). A new figure fails until it is named
# here; a name whose figure left the docs fails too. A third element scales the receipt's number
# to the doc's unit (a receipt in MB, a doc in GB).
_SCALE = "semantic-scale-20261031-0559.txt"
_MODELS = "model-files-20261029-1207.txt"
_WARM_FILES = "warm-model-files-20261029.txt"
DOC_FIGURES = {
    "131 MB": [(_MODELS, r"potion-retrieval-32M.*?([\d.]+) MB")],
    "92 MB": [(_MODELS, r"ms-marco-MiniLM-L-6-v2.*?([\d.]+) MB")],
    "4 ms": [(_SCALE, r"10,000 vectors:.*?search after the read\s+([\d.]+) ms")],
    "15 ms": [(_SCALE, r"10,000 vectors: read\s+([\d.]+) ms")],
    "24 ms": [(_SCALE, r"50,000 vectors:.*?search after the read\s+([\d.]+) ms")],
    "80 ms": [(_SCALE, r"50,000 vectors: read\s+([\d.]+) ms")],
    "6 ms": [(_SCALE, r"300 vectors:.*?without numpy\s+([\d.]+) ms")],
    "214 ms": [(_SCALE, r"10,000 vectors:.*?without numpy\s+([\d.]+) ms")],
    # The warm model (§4z): its int8 and full-precision files, an encode, the hook's added
    # latency (the larger of the two checked runs, as §4z quotes it), and its memory once settled.
    "309.5 MB": [(_WARM_FILES, r"int8\s+model_quantized.*?([\d.]+) MB")],
    "1,235 MB": [(_WARM_FILES, r"full precision\s+model\.onnx.*?([\d.]+) MB")],
    "170.7 ms": [("bench-20261027-sel-dense-embeddinggemma-int8-words.txt", r"encode per prompt median ([\d.]+) ms")],
    "114 ms": [("warm-latency-20261029-0243.txt", r"added by the model, per prompt.*?median ([\d.]+) ms")],
    "1.6 GB": [("warm-memory-20261027-0530.txt", r"default(?:\s+\d+){6}\s+(\d+)", 0.001)],
    # The review log's read (#464): the size of the largest real transcript it was timed on, as a process.
    "569 MB": [("review-log-time-20261115-0848.json", r'"largest_real_megabytes": ([\d.]+)')],
    # The quick hint's cost as okl init works it out (#470): okl's own store and two made-up ones.
    "17 ms": [("quick-hint-time-20261115-1710.json", r'"okl\'s own store": \{[\s\S]*?"median_ms": ([\d.]+)')],
    "48 ms": [("quick-hint-time-20261115-1710.json", r'"made up, 1,000 lessons": \{[\s\S]*?"median_ms": ([\d.]+)')],
    "231 ms": [("quick-hint-time-20261115-1710.json", r'"made up, 5,000 lessons": \{[\s\S]*?"median_ms": ([\d.]+)')],
}
# Not measurements: a bound the docs set, or arithmetic, with why.
THRESHOLDS = {
    "100 ms": "the retrieval ADR's trigger for the next index tier: a search slower than this",
    "200 MB": "100,000 vectors of 512 float32s: arithmetic, the size at which that tier is due",
    "1.1 GB": "warm-memory-20261027-0530.txt: 1,659 MB after the first prompt less 559 after loading",
}
# A number and its unit can sit on two lines: Markdown renders "131\nMB" as "131 MB" (#307).
FIGURE = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s?(ms|MB|GB)\b")
# What each figure measures, as words that must stand near every place it is published. The
# check above holds the set of strings, so a figure moved to another measurement (the hybrid
# model's size written as the reranker's 92 MB) kept a string some doc still used and passed
# (CodeRabbit on #307). Near: 160 characters before the figure and 60 after.
NEAR = {
    "131 MB": r"potion|hybrid|semantic",
    "92 MB": r"rerank|MiniLM|cross-encoder|second stage",
    "4 ms": r"search|product",
    "15 ms": r"read",
    "24 ms": r"search|product",
    "80 ms": r"read",
    "6 ms": r"without numpy|pure-Python|fallback",
    "214 ms": r"without numpy|pure-Python|fallback",
    "309.5 MB": r"int8",
    "1,235 MB": r"full precision|precision's",
    "170.7 ms": r"[Ee]ncod",
    "114 ms": r"prompt",
    "1.6 GB": r"memory|holds|warm",
    "569 MB": r"transcript",
    "17 ms": r"own store|quick",
    "48 ms": r"1,000 lessons|made-up",
    "231 ms": r"5,000|made-up",
}


def _near(text: str, start: int, end: int) -> str:
    """The words around a figure, on one line."""
    return " ".join(text[max(0, start - 160):end + 60].split())


def _published_docs() -> list[Path]:
    """What a reader is told: the README, every doc (decision records too: the CI reviewer
    found the ADR still quoting a retracted figure, #307) and the overview sheets. docs/posts/
    are dated write-ups and the REPORT is the receipts' own narrative, so neither is held here."""
    docs = [p for p in sorted((ROOT / "docs").rglob("*.md")) if "posts" not in p.parts]
    # The package's docstrings and comments too: they cite receipts as the docs do (#307).
    return [ROOT / "README.md", *docs, *sorted((ROOT / "docs" / "overview").glob("*.html")),
            *sorted((ROOT / "src" / "okl").rglob("*.py"))]


def test_every_size_and_latency_the_docs_publish_is_its_receipts_number():
    """The architecture reviewer's most common finding was a published figure no receipt held
    (#300); this is that check, run on every change for free."""
    found: dict[str, str] = {}
    misplaced = []
    for doc in _published_docs():
        text = doc.read_text()
        for m in FIGURE.finditer(text):
            fig = f"{m.group(1)} {m.group(2)}"
            found.setdefault(fig, doc.name)
            if fig in NEAR and not re.search(NEAR[fig], _near(text, m.start(), m.end())):
                misplaced.append(f"{doc.name}: {fig} near {_near(text, m.start(), m.end())!r}")
    assert set(NEAR) == set(DOC_FIGURES), "each figure names what it measures in NEAR"
    assert not misplaced, f"a figure published beside another measurement's words: {misplaced}"
    unnamed = {fig: doc for fig, doc in found.items() if fig not in DOC_FIGURES and fig not in THRESHOLDS}
    assert not unnamed, f"name each figure's receipt line in DOC_FIGURES: {unnamed}"
    assert set(DOC_FIGURES) <= set(found), f"no longer in the docs: {set(DOC_FIGURES) - set(found)}"
    for fig, lines in DOC_FIGURES.items():
        quoted = fig.split()[0].replace(",", "")
        places = len(quoted.split(".")[1]) if "." in quoted else 0
        for receipt, pattern, *scale in lines:
            m = re.search(pattern, (ROOT / "evals" / "results" / receipt).read_text())
            assert m, f"{receipt} has no line for {fig}"
            value = float(m.group(1)) * (scale[0] if scale else 1)
            assert round(value, places) == float(quoted), f"{fig}: {receipt} says {m.group(1)}"


# Verdicts whose own reason says the defect is absent while their boolean says reproduced: the
# judge answers the booleans before it reasons. Each is corrected in the REPORT section named
# here, and the receipt stays as the run wrote it, as §4j's did (review on #303).
CONTRADICTED = {("ab-20261023-1303.json", 67): "4r", ("ab-20261023-1303.json", 184): "4r",
                ("ab-20261029-0318.json", 61): "4aa", ("ab-20261029-0318.json", 70): "4aa"}
NEGATED = re.compile(r"(defect|it) (is|was) not (reproduced|present)|not reproduced|is not present"
                     r"|does not reproduce|defect is absent", re.I)


def test_a_figure_moved_to_another_measurement_fails():
    """The hybrid model's size written as the reranker's: the string is still a named figure,
    and only its surroundings say it is the wrong one (CodeRabbit on #307)."""
    text = "Turning it on costs a\n92 MB model download (`minishlab/potion-retrieval-32M`)"
    m = FIGURE.search(text)
    assert m and f"{m.group(1)} {m.group(2)}" == "92 MB"
    assert not re.search(NEAR["92 MB"], _near(text, m.start(), m.end()))
    assert re.search(NEAR["131 MB"], _near(text, m.start(), m.end()))


def test_every_verdict_its_own_reason_contradicts_is_corrected_in_the_report():
    """A contradicted verdict counted as written moves a figure the wrong way; four sat in two
    receipts, two of them quoted uncorrected, before a reviewer read the reasons (#303)."""
    found = set()
    for receipt in sorted((ROOT / "evals" / "results").glob("ab-*.json")):
        for i, row in enumerate(json.loads(receipt.read_text()).get("results", [])):
            if row.get("reproduced") and NEGATED.search(row.get("reason") or ""):
                found.add((receipt.name, i))
    assert found == set(CONTRADICTED), "name each contradicted verdict and correct it in the REPORT"
    report = (ROOT / "evals" / "REPORT.md").read_text()
    for (receipt, row), section in CONTRADICTED.items():
        start = report.index(f"\n## {section}. ")
        body = report[start:report.index("\n## ", start + 1)]
        assert receipt in body and re.search(rf"\bRow {row}\b", body), f"§{section} does not correct {receipt} row {row}"


def test_the_readme_headline_is_the_thesis_claim():
    """docs/THESIS.md carries the claim the README's headline states, its baseline and its
    history; when one moves without the other, the thesis has drifted (#317)."""
    headline = re.search(r"^\*\*(.+?)\*\*<br>$", (ROOT / "README.md").read_text(), re.M).group(1)
    claim = (ROOT / "docs" / "THESIS.md").read_text().split("## The claim", 1)[1]
    assert re.search(r"^\*\*(.+?)\*\*$", claim, re.M).group(1) == headline


def test_the_from_scratch_guide_states_verifys_default_timeout():
    """docs/FROM-SCRATCH.md tells a reader how long `okl verify` gives a check; when the parser's
    default moves, the guide must move with it (review on #332: it once said 120 for 600)."""
    import argparse

    from okl.cli.parser import build_parser
    sub = next(a for a in build_parser()._actions if isinstance(a, argparse._SubParsersAction))
    default = sub.choices["verify"].get_default("timeout")
    assert f"{default} seconds by default" in _flat("docs/FROM-SCRATCH.md")


# docs/THESIS.md held to its receipts (#319). The page states the claim, what holds today and a
# measured baseline, and is meant to be the most current page in the repo (#317); it was held
# current by hand. Every figure on it is recomputed here from the receipt it names, so changing a
# figure, naming an uncommitted receipt, or adding a figure with no receipt fails, and a newer
# receipt of a measurement the page cites fails until the page cites it.
_WORDS = {4: "four", 7: "seven", 8: "eight", 9: "nine"}
_RECEIPT = re.compile(r"`([\w.-]+\.(?:json|txt))`")
# Numbers on the page that are not measurements: dates, issues, REPORT sections, versions,
# receipt names, and the MCP Registry's description limit.
_NOT_FIGURES = re.compile(r"`[^`]*`|\d{4}-\d{2}-\d{2}|#\d+|§\w+(?: finding \d+)?|\b\d+\.\d+\.\d+\b|100-character")
_NUMBER = re.compile(r"(?<![\w.])\d(?:[\d,]*\d)?(?:\.\d+)?%?")   # commas only between digits
# A status row with no measurement behind it, and why.
NO_EVIDENCE: dict[str, str] = {}   # the Stop hook's row now cites #391, where a long session showed what its tests did not


def _thesis_figures() -> dict[str, str]:
    """Each figure the thesis quotes, as the page words it, recomputed: text -> its receipt."""
    results = ROOT / "evals" / "results"

    def load(name):
        return json.loads((results / name).read_text())

    census = load("lesson-census-20261031-1409.json")
    c, n = census["classes"], census["store"]["recorded"]
    latest = load("lesson-census-20261102-2119.json")
    c2, n2 = latest["classes"], latest["store"]["recorded"]
    ep = load("drift-replay-20261101-0143.json")["summary"]["event_precision"]
    first, rerun = load("drift-mutate-20261031-1522.json"), load("drift-mutate-20261101-1935.json")
    m1, m2 = first["summary"], rerun["summary"]
    k1, k2 = m1["catch"], m2["catch"]
    lo, hi = k1["wilson95"]
    nine = [first["summary"]["per_lesson"][lesson] for lesson in rerun["lessons"]]
    no_verdict = sum(v for key, v in m2["judge"].items() if key.endswith(":invalid"))
    stale = load("stale-lessons-20261031-1527.json")["summary"]["stale_rate"]
    review = load("stale-review-20261102-2133.json")["summary"]
    verdicts, wrong = review["verdicts"], review["rates"]["detail wrong"]
    questioned = sum(verdicts[v] for v in ("detail wrong", "outlived", "stale"))
    wlo, whi = wrong["wilson95"]
    planted, over = review["planted_caught"], review["negatives_over_called"]
    marks = re.search(r"briefed prompts (\d+): (\d+) of the (\d+) lessons the mark could reach are marked "
                      r"unchecked \((\d+) briefed in all\); the marks add (\d+) characters to (\d+) \(([\d.]+)%\)",
                      (results / "briefing-marks-size-20261101-1110.txt").read_text())
    prompts, unchecked, reach, briefed, added, chars, share = marks.groups()
    bh, bn, rh, rn = _pool(POOLED_RECEIPTS)
    missed = (results / "missed-20261108-0000.txt").read_text()
    blocks = re.split(r"^(?=\[)", missed, flags=re.M)[1:]
    reached = sum(1 for b in blocks if re.search(r"\b(full|line)\b", b.split("rank among")[0]))
    ranks = [(int(r), int(t)) for r, t in re.findall(r"(?:lexical|lexical\+potion) (\d+) of (\d+)", missed)]
    lo_rank, hi_rank, live = min(r for r, _ in ranks), max(r for r, _ in ranks), max(t for _, t in ranks)
    # Every text and arm pair, and how many ran: a "?" did not, and the page must not claim it did.
    cells = [c.strip() for line in missed.splitlines()
             if line.startswith("    ") and " | " in line and not line.strip().startswith("tiered")
             for c in line.split(None, 1)[1].split("|")]
    ran = sum(1 for c in cells if c != "?")

    def nth(k: int) -> str:
        return f"{k}{'th' if 10 <= k % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(k % 10, 'th')}"
    return {
        f"{reached} of {len(blocks)} lessons that applied by what the code did "
        f"reached the agent through any arm that ran ({ran} of {len(cells)} text and arm pairs ran), "
        f"ranked {nth(lo_rank)} to {nth(hi_rank)} of {live}":
            "missed-20261108-0000.txt (§4ak)",
        f"{round(100 * bh / bn)}% → {round(100 * rh / rn)}% defects reproduced on {_WORDS[8]} bait tasks, "
        f"pooled over {_WORDS[len(POOLED_RECEIPTS)]} A/B runs": "the pooled A/B receipts (§5 finding 7)",
        f"{c['watched']} of the {n} lessons recorded here were watched at the 2026-10-31 census below, "
        f"{len(rerun['lessons']) + len(rerun['left_out'])} after #318 moved "
        f"{_WORDS[c['watched'] - len(rerun['lessons']) - len(rerun['left_out'])]}": "the census and §4ah",
        f"of {m1['breaking_patches']} patches written to break those lessons, a judge confirmed {m1['breaks']} "
        f"as breaks, and drift caught {k1['caught']} of them": "drift-mutate-20261031-1522.json",
        f"it caught {k2['caught']} of {k2['breaks']} on the {_WORDS[len(rerun['lessons'])]} whose check runs "
        "from the commit": "drift-mutate-20261101-1935.json",
        f"{c2['watched'] + c2['checked']} of {n2} lessons have a check": "lesson-census-20261102-2119.json",
        f"{c2['watched']} / {c2['checked']} / {c2['unchecked']} of {n2}": "lesson-census-20261102-2119.json",
        f"{c['watched']} / {c['checked']} / {c['unchecked']} of {n}; all {census['checks_at_rev']['pass']} "
        f"CI-left checks pass at {census['rev'][:7]}": "lesson-census-20261031-1409.json",
        f"{ep['needed']} of {ep['decided']:,} events ({ep['rate']:.2%})": "drift-replay-20261101-0143.json",
        f"(of {m1['breaking_patches']} patches written to break them) that drift caught | {k1['caught']} of "
        f"{k1['breaks']} ({k1['rate']:.1%}, 95% interval {100 * lo:.1f}–{100 * hi:.1f}%); of the "
        f"{k1['breaks'] - k1['caught']} misses, {m1['coverage_misses']} changed a file the lesson does not "
        f"watch, and {m1['sensitivity_misses']} passed": "drift-mutate-20261031-1522.json",
        f"(of {m2['breaking_patches']} patches written to break them) | {k2['caught']} of {k2['breaks']}, counts "
        f"only: the judge gave no verdict on {no_verdict} of the {sum(m2['judge'].values())} patches, over the "
        # 20%: the registered limit on judge failures (DEVELOPING's evaluation rules), not a measurement.
        f"20% that allows a rate; §4af caught {sum(x['caught'] for x in nine)} of {sum(x['breaks'] for x in nine)} "
        f"on the same {_WORDS[len(nine)]}": "drift-mutate-20261101-1935.json and -1522",
        f"{stale['stale']} of {stale['decided']} that make a claim about this repo": "stale-lessons-20261031-1527.json",
        f"{questioned} of {wrong['decided']} that make a claim about this repo: {verdicts['detail wrong']} with a "
        f"wrong detail ({wrong['rate']:.1%}, 95% interval {100 * wlo:.1f}–{100 * whi:.1f}%), "
        f"{verdicts['outlived']} outlived, {verdicts['stale']} stale; all {questioned} confirmed and corrected. "
        f"The judge caught {planted['caught']} of {planted['of']} planted wrong details and wrongly flagged "
        f"{over['over']} of {over['of']} known-current lessons": "stale-review-20261102-2133.json (§4ai)",
        f"on {prompts} briefed prompts": "briefing-marks-size-20261101-1110.txt",
        f"{unchecked} of the {reach} the mark could reach (all {briefed} briefed could); the marks add "
        f"{int(added):,} characters to {int(chars):,} ({share}%)": "briefing-marks-size-20261101-1110.txt",
        f"{unchecked} of {reach} on the measured prompts": "briefing-marks-size-20261101-1110.txt",
        f"drift watched {c['watched']} of the {n} lessons": "lesson-census-20261031-1409.json",
    }


def _thesis_problems(page: str) -> list[str]:
    """What docs/THESIS.md says that its receipts do not: a figure that is not the recomputed one,
    a number no receipt accounts for, an uncommitted or superseded receipt, a missing section."""
    flat = " ".join(page.split())
    problems = [f"not on the page, recomputed from {where}: {text!r}"
                for text, where in _thesis_figures().items() if text not in flat]
    # Every number is inside a recomputed figure or is not a measurement.
    covered = [False] * len(flat)
    for pattern in [*(re.escape(t) for t in _thesis_figures()), _NOT_FIGURES.pattern]:
        for m in re.finditer(pattern, flat):
            covered[m.start():m.end()] = [True] * (m.end() - m.start())
    problems += [f"a number no receipt accounts for: {flat[max(0, m.start() - 60):m.end() + 20]!r}"
                 for m in _NUMBER.finditer(flat) if not all(covered[m.start():m.end()])]
    # Every receipt is committed, and is the newest of its measurement.
    committed = set(subprocess.run(["git", "-C", str(ROOT), "ls-files", "evals/results"], capture_output=True,
                                   text=True, check=True).stdout.split())
    cited = set(_RECEIPT.findall(page))
    for name in sorted(cited):
        if f"evals/results/{name}" not in committed:
            problems.append(f"names a receipt that is not committed: {name}")
        family = re.match(r"(.+)-\d{8}-\d{4}\.(json|txt)$", name)
        if family:
            same = sorted(Path(f).name for f in committed
                          if re.fullmatch(re.escape(family[1]) + r"-\d{8}-\d{4}\." + family[2], Path(f).name))
            if same and same[-1] not in cited:
                problems.append(f"cites {name}, but {same[-1]} is a newer run of the same measurement")
    # Every REPORT section it names exists.
    headings = set(re.findall(r"^## (\w+)\.", (ROOT / "evals" / "REPORT.md").read_text(), re.M))
    problems += [f"names §{s}, which REPORT has no section for" for s in sorted(set(re.findall(r"§(\w+)", page)))
                 if s not in headings]
    # Every status row names its evidence, or says here why it has none.
    for row in re.findall(r"^\| (it [^|]+|each [^|]+|every [^|]+) \|[^|]+\| (.+) \|$", page, re.M):
        if row[1].strip() in ("—", "-", "") and row[0].strip() not in NO_EVIDENCE:
            problems.append(f"the status row {row[0].strip()!r} names no evidence")
    return problems


def test_every_figure_on_the_thesis_is_recomputed_from_its_receipt():
    """docs/THESIS.md's figures, receipts and sections, held to the receipts (#319)."""
    assert _thesis_problems((ROOT / "docs" / "THESIS.md").read_text()) == []


def test_the_thesis_check_fails_on_a_changed_figure_a_new_one_and_a_stale_receipt():
    """Planted failures: the check goes red on each thing it guards."""
    page = (ROOT / "docs" / "THESIS.md").read_text()

    changed = _thesis_problems(page.replace("4 of 1,865 events", "3 of 1,865 events"))
    assert any("not on the page" in p and "1,865" in p for p in changed), changed
    unaccounted = _thesis_problems(page.replace("## History", "Drift caught 97% of breaks.\n\n## History"))
    assert any("no receipt accounts for" in p and "97%" in p for p in unaccounted), unaccounted
    uncommitted = _thesis_problems(page.replace("`stale-lessons-20261031-1527.json`", "`stale-lessons-20991231-0000.json`"))
    assert any("not committed" in p for p in uncommitted), uncommitted
    superseded = _thesis_problems(page.replace("`briefing-marks-size-20261101-1110.txt`",
                                               "`briefing-marks-size-20261031-1612.txt`"))
    assert any("newer run" in p for p in superseded), superseded


def _doc_commands():
    """ci/check-doc-commands.py, loaded as a module: it is a script, not a package."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("check_doc_commands", ROOT / "ci" / "check-doc-commands.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_every_okl_command_and_flag_the_docs_write_exists():
    """Every `okl <command> --flag` in the README, docs/, the overview sheets and the skills,
    commands and templates okl ships is one the CLI has (#314): only `okl init`'s flags, in three
    docs, were checked before."""
    read = _doc_commands().docs()
    found, checked = _doc_commands().problems(read)

    assert found == []
    assert checked > 400, checked             # the docs write hundreds; none found means a broken reader
    # The files okl ships for an agent to follow are read too (#314), the skill and its mirror.
    assert {"src/okl/scaffold/claude/skills/encoding-loop/SKILL.md",
            ".claude/skills/encoding-loop/SKILL.md", ".claude/commands/record.md"} <= set(read)


def test_the_doc_command_check_names_a_missing_command_or_flag():
    """Red where it should be, and not on a flag inside a quoted argument or a placeholder."""
    check = _doc_commands()
    doc = """Run `okl init --no-sead`, then:

```bash
okl frobnicate --all
okl verify x --run "grep -q -- '--port' README.md && echo OK | cat" --expect OK
okl <command> --anything
okl log
```
"""
    found, _ = check.problems({"a.md": doc})

    assert found == ["a.md: `okl frobnicate` is not a command", "a.md: `okl init` has no --no-sead"]


# The other direction (#455, lesson omission-drift-uncaught): the checks above fail a doc that
# names what the CLI does not have, and nothing failed a doc that left out what it does have.
# docs/COMMANDS.md is titled "Every okl command" and lacked ten; sixteen flags were in no doc.
# The set is read from the parser, so a new command or flag fails here until a doc names it.
REFERENCE = ("docs/COMMANDS.md", "README.md")   # where a command must be named as `okl <path>`


def _living_docs() -> dict[str, str]:
    """README.md and every doc under docs/ that check-doc-commands reads: the dated records
    (posts, decision records, receipts, the CHANGELOG, the REPORT) are left out as it leaves them."""
    return {name: text for name, text in _doc_commands().docs().items()
            if name == "README.md" or (name.startswith("docs/") and name.endswith(".md"))}


def _names(text: str, words: str) -> bool:
    """Whether `text` writes `words` (`okl on-edit list`, `--repo-dir`) whole, spaced by blanks."""
    pattern = r"[ \t]+".join(map(re.escape, words.split()))
    return re.search(rf"(?<![\w./-]){pattern}(?![\w-])", text) is not None


def _coverage_problems(living: dict[str, str], cli: list[tuple[str, bool, list[str]]]) -> list[str]:
    """Each command the REFERENCE docs do not name as `okl <path>`, and each long flag no living
    doc names, with where it must go."""
    problems = []
    for path, runs, flags in cli:
        where = [name for name in REFERENCE if _names(living.get(name, ""), path)]
        if runs and not where:
            problems.append(f"`{path}` is in neither {' nor '.join(REFERENCE)}: add it to docs/COMMANDS.md, "
                            "a command line and its aligned `#` comments")
        problems.extend(f"`{path} {flag}` is in no living doc (README.md, docs/): document it where "
                        f"`{path}` is documented ({', '.join(where) or 'docs/COMMANDS.md'})"
                        for flag in flags if not any(_names(text, flag) for text in living.values()))
    return problems


def test_every_command_and_flag_the_cli_has_is_in_the_docs():
    """Every command and subcommand the parser has is named as `okl <path>` in docs/COMMANDS.md or
    the README, and every long flag in a living doc; what help hides is not held (#455)."""
    cli = list(_doc_commands().every_command())
    problems = _coverage_problems(_living_docs(), cli)

    # A walk that found nothing would pass; okl has over thirty commands and a hundred flags.
    assert len(cli) > 30, cli
    assert sum(len(flags) for _, _, flags in cli) > 100, cli
    assert not problems, "the CLI has what no doc names:\n  " + "\n  ".join(problems)


def test_the_coverage_check_names_a_missing_command_and_flag():
    """Red where it should be: a command's entry cut from docs/COMMANDS.md, a flag's one mention
    removed, and the walk skips what help hides and a command that only groups subcommands."""
    cli = list(_doc_commands().every_command())
    living = _living_docs()
    by_path = {path: (runs, flags) for path, runs, flags in cli}
    assert by_path["okl intake"][0] is False     # it only groups `okl intake pr`
    assert by_path["okl intake pr"][0] is True
    assert "--wait" in by_path["okl warm"][1]
    assert "--spawned" not in by_path["okl warm"][1]   # hidden from help with argparse.SUPPRESS
    assert {"--ci", "--no-ci"} <= set(by_path["okl init"][1])
    assert "--help" not in by_path["okl init"][1]

    # Cut `okl dedup`'s entry: its command line and the comment lines under it.
    entry = re.compile(r"^okl dedup\b.*\n(?: +#.*\n)*", re.M)
    assert len(entry.findall(living["docs/COMMANDS.md"])) == 1, "move this test's entry with the docs"
    cut = {**living, "docs/COMMANDS.md": entry.sub("", living["docs/COMMANDS.md"])}
    assert "`okl dedup` is in neither docs/COMMANDS.md nor README.md: add it to docs/COMMANDS.md, " \
           "a command line and its aligned `#` comments" in _coverage_problems(cut, cli)

    # Drop every mention of `okl review --workers`.
    assert sum(text.count("--workers") for text in living.values()) == 1, "move this test's flag with the docs"
    dropped = {name: text.replace("--workers", "--wrkrs") for name, text in living.items()}
    assert _coverage_problems(dropped, cli) == [
        "`okl review --workers` is in no living doc (README.md, docs/): document it where `okl review` "
        "is documented (docs/COMMANDS.md, README.md)"]


# The same direction for the two sheets (docs/overview/), which summarise what okl does on its own.
# A summary drifts by leaving a new behaviour out, and nothing in it goes false (lesson
# omission-drift-uncaught). It happened twice. On 0.17.0 the review after writing went on by
# default and the overview said nothing of it (#455). Then the review before a push shipped with
# the docs and two diagrams updated and both sheets left as they were (#511); the person who asked
# "did we update the diagrams and docs" found it, and that neither sheet named the briefing at a
# file read. The test added for #455 held commands and flags to the Markdown docs and never read
# the sheets. Both sets below are read from the code: a script okl installs to run on its own, and
# a switch `okl init` has. A new one fails here until a sheet names it, or it is listed with why
# it is not there.
SHEETS = ("docs/overview/okl-overview.html", "docs/overview/okl-anatomy.html")
# Each installed script, and the words every sheet uses for the moment it runs.
MOMENTS = {
    "userpromptsubmit-okl-check.sh": "every prompt",
    "posttooluse-okl-read.sh": "the agent reads",
    "posttooluse-okl-edit.sh": "after each edit",
    "stop-okl-encode.sh": "review after writing",
    "pre-push": "pre-push",
}
NOT_A_MOMENT = {"okl-mcp.sh": "starts the MCP server when the agent asks for it; it runs nothing on its own"}
# `okl init` flags no sheet names, each with why. A flag that turns on something okl then runs by
# itself belongs on a sheet, not here.
NOT_ON_THE_SHEETS = {
    "--claude": "which agent's files init writes; the sheets say what is Claude Code's",
    "--no-claude": "the off switch of --claude",
    "--no-ci": "the off switch of --ci, which the anatomy sheet names",
    "--no-git-hook": "the off switch of --git-hook, which the anatomy sheet names",
    "--review-after-writing": "the review is on by default, and both sheets name it; this switches it back on",
    "--no-review-after-writing": "the off switch of the review after writing",
    "--no-review-before-push": "the off switch of --review-before-push, which the anatomy sheet names",
    "--review-holds-push": "how --review-before-push runs (in the foreground), not another moment",
    "--dry-run": "shows what init would write and runs nothing",
    "--force": "replaces files init wrote before",
    "--uninstall": "removes what init wrote",
    "--no-seed": "skips loading the starter lessons",
    "--interests": "which subjects reach this repo's briefings: a setting of the briefing the sheets describe",
    "--owner": "who must approve changes to okl's own files (docs/AGENT-IDENTITY.md), outside a lesson's life",
    "--owned": "the paths --owner covers",
    "--service": "points the repo at a shared service in place of its local store",
}


def _sheet_words(name: str) -> str:
    """What a sheet says: its body with drawings and tags removed and spaces evened out."""
    html = (ROOT / name).read_text()
    body = re.sub(r"<svg.*?</svg>", " ", html[html.index("<body"):], flags=re.S)
    return " ".join(re.sub(r"<[^>]+>", " ", body).replace("&nbsp;", " ").split())


def _installed_scripts() -> list[str]:
    """Every script okl installs to run on its own: the agent hooks and git's hooks it ships."""
    shipped = ROOT / "src" / "okl" / "scaffold"
    return sorted([p.name for p in (shipped / "hooks").glob("*.sh")] + [p.name for p in (shipped / "git-hooks").iterdir()])


def _sheet_problems(sheets: dict[str, str], scripts: list[str], init_flags: list[str]) -> list[str]:
    """What the sheets leave out of the two sets, and each table entry that names nothing okl has."""
    problems = []
    for script in scripts:
        if script in NOT_A_MOMENT:
            continue
        if script not in MOMENTS:
            problems.append(f"okl installs {script} to run on its own, and no sheet is held to it: add it to MOMENTS "
                            "with the words the sheets use for when it runs, and say so on both sheets")
            continue
        problems.extend(f"{name} does not say \"{MOMENTS[script]}\", when {script} runs"
                        for name, words in sheets.items() if MOMENTS[script] not in words)
    problems.extend(f"`okl init {flag}` is on neither sheet ({', '.join(sheets)}): name it on one, or add it to "
                    "NOT_ON_THE_SHEETS with why it is not there"
                    for flag in init_flags
                    if flag not in NOT_ON_THE_SHEETS and not any(_names(words, flag) for words in sheets.values()))
    problems.extend(f"{name} is in {table} and okl no longer has it: remove the entry"
                    for table, names, have in (("MOMENTS", MOMENTS, scripts), ("NOT_A_MOMENT", NOT_A_MOMENT, scripts),
                                               ("NOT_ON_THE_SHEETS", NOT_ON_THE_SHEETS, init_flags))
                    for name in names if name not in have)
    return problems


def _init_flags() -> list[str]:
    return next(flags for path, _, flags in _doc_commands().every_command() if path == "okl init")


def test_the_sheets_name_every_moment_okl_runs_and_every_switch_init_has():
    """Both sheets say when each installed script runs, and every `okl init` flag is on a sheet or
    listed with why it is not. Nothing was reading the sheets for what they leave out."""
    scripts, flags = _installed_scripts(), _init_flags()
    assert len(scripts) >= 6 and len(flags) >= 20, (scripts, flags)   # a walk that found nothing would pass
    problems = _sheet_problems({name: _sheet_words(name) for name in SHEETS}, scripts, flags)
    assert not problems, "the sheets leave out what okl does:\n  " + "\n  ".join(problems)


def test_the_sheet_coverage_check_names_what_a_sheet_leaves_out():
    """Red where it should be: a sheet as it was before the review before a push was added to it, a
    script and a flag added later, and a table entry for something okl no longer has."""
    scripts, flags = _installed_scripts(), _init_flags()
    sheets = {name: _sheet_words(name) for name in SHEETS}
    overview, anatomy = SHEETS
    # The anatomy sheet as it was on main after #511: no word of the flag that turns the review on.
    assert _names(sheets[anatomy], "--review-before-push"), "move this test's flag with the sheet"
    before = {**sheets, anatomy: sheets[anatomy].replace("--review-before-push", "")}
    assert _sheet_problems(before, scripts, flags) == [
        f"`okl init --review-before-push` is on neither sheet ({overview}, {anatomy}): name it on one, or add it to "
        "NOT_ON_THE_SHEETS with why it is not there"]
    # One sheet that stops saying when the read hook runs.
    silent = {**sheets, overview: sheets[overview].replace("the agent reads", "")}
    assert _sheet_problems(silent, scripts, flags) == [
        f'{overview} does not say "the agent reads", when posttooluse-okl-read.sh runs']
    # A hook and a switch that do not exist yet: each fails until someone decides where it goes.
    later = _sheet_problems(sheets, [*scripts, "posttooluse-okl-plan.sh"], [*flags, "--review-at-commit"])
    assert len(later) == 2 and "okl installs posttooluse-okl-plan.sh" in later[0] and "`okl init --review-at-commit`" in later[1], later
    # An entry for a script okl stopped shipping.
    gone = _sheet_problems(sheets, [s for s in scripts if s != "okl-mcp.sh"], flags)
    assert gone == ["okl-mcp.sh is in NOT_A_MOMENT and okl no longer has it: remove the entry"]


# The same direction for two more sets okl's code defines (#455): the keys of .okl/config.json
# and the environment variables okl reads. Before this, nine of the seventeen keys were named in
# no doc as a key of that file, and twenty of the variables in no doc at all. Each set is read
# from the code, Python by its syntax tree and shell by its expansions, never from the docs, so a
# key or a variable added later fails here until a doc names it.
SHIPPED_SHELL = "src/okl/scaffold"   # the shell okl ships; the repo's hooks/ and gates/ are its mirrors
CONFIG_HOLDERS = ("config", "cfg")   # the names the code gives .okl/config.json's contents
NAME = r"[A-Z_][A-Z0-9_]*"           # an environment variable, as okl and its scripts write them


def _committed(*specs: str) -> dict[str, str]:
    """Each committed file the pathspecs match, with its text (CLAUDE.md: audits read the repo)."""
    names = subprocess.run(["git", "-C", str(ROOT), "ls-files", *specs], capture_output=True,
                           text=True, check=True).stdout.split()
    return {name: (ROOT / name).read_text() for name in names}


def _shell_sources() -> dict[str, str]:
    """The shell okl ships: the agent hooks, the git hook, the gates and the kit's review script."""
    return {name: text for name, text in _committed(SHIPPED_SHELL).items()
            if name.endswith(".sh") or "/git-hooks/" in name}


def _key_uses(tree, holds, methods, stores):
    """Each (line, key expression) where `tree` uses a key of a mapping `holds` accepts:
    `.<method>(key)`, `[key]` (a read only, unless `stores`), and `key in`."""
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in methods \
                and n.args and holds(n.func.value):
            yield n.lineno, n.args[0]
        elif isinstance(n, ast.Subscript) and holds(n.value) and (stores or isinstance(n.ctx, ast.Load)):
            yield n.lineno, n.slice
        elif isinstance(n, ast.Compare) and isinstance(n.ops[0], ast.In | ast.NotIn) and holds(n.comparators[0]):
            yield n.lineno, n.left


def _holds_config(node) -> bool:
    """Whether `node` is .okl/config.json's contents as the code names them: `config` or `cfg`,
    a `.config` attribute (the Client's), load_config(), or json.loads(cfg.read_text())."""
    code = ast.unparse(node)
    holder = "|".join(CONFIG_HOLDERS)
    return (code in CONFIG_HOLDERS or code.endswith((".config", "load_config()"))
            or re.fullmatch(rf"(?:json\.)?loads\((?:{holder})\.read_text\(\)\)", code) is not None)


def _string_constants(tree) -> dict[str, str]:
    """A module's top-level `NAME = "text"` assignments."""
    return {t.id: n.value.value for n in tree.body if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str)
            for t in n.targets if isinstance(t, ast.Name)}


def _config_keys_in(sources: dict[str, str]) -> tuple[dict[str, set[str]], list[str]]:
    """Each .okl/config.json key the Python in `sources` reads or writes, with the files that do,
    and each use whose key is neither a string nor a module's string constant: a key this cannot
    name must fail the test, never pass it unseen."""
    trees = {path: ast.parse(text) for path, text in sources.items()}
    dotted = {path.removeprefix("src/").removesuffix(".py").replace("/", "."): path for path in trees}
    constants = {path: _string_constants(tree) for path, tree in trees.items()}
    keys: dict[str, set[str]] = {}
    unnamed: list[str] = []
    for path, tree in trees.items():
        names = dict(constants[path])
        package = path.removeprefix("src/").removesuffix(".py").split("/")
        for n in ast.walk(tree):   # `from .on_edit import KEY as ON_EDIT_KEY` names on_edit's constant
            if isinstance(n, ast.ImportFrom) and n.level and n.module:
                origin = dotted.get(".".join([*package[:-n.level], *n.module.split(".")]), "")
                names |= {a.asname or a.name: constants[origin][a.name] for a in n.names
                          if a.name in constants.get(origin, {})}
        for line, key in _key_uses(tree, _holds_config, ("get", "pop", "setdefault"), stores=True):
            name = key.value if isinstance(key, ast.Constant) else names.get(getattr(key, "id", ""))
            if isinstance(name, str):
                keys.setdefault(name, set()).add(path)
            else:
                unnamed.append(f"{path}:{line}: {ast.unparse(key)}")
    return keys, unnamed


def _hook_config_keys(sources: dict[str, str]) -> dict[str, set[str]]:
    """Each .okl/config.json key the shell in `sources` reads, in a command that names the file
    (`config.json`, or `$config` holding its path): a `.get("key")` in its Python, a `'"key"'`
    grep pattern or a `"key":` sed pattern."""
    keys: dict[str, set[str]] = {}
    for path, text in sources.items():
        for line in text.replace("\\\n", " ").splitlines():
            if not line.lstrip().startswith("#") and re.search(r"config\.json|\$\{?config\b", line):
                for m in re.finditer(r"""\.get\(\s*["'](\w+)["']|'"(\w+)"'|"(\w+)":""", line):
                    keys.setdefault(m[1] or m[2] or m[3], set()).add(path)
    return keys


def _doc_units(text: str):
    """Each paragraph, list item, table row and fenced command entry of a doc, with what covers
    it: the headings it sits under, its table's header row, or its list's lead-in when that ends
    in a colon, as ci/check-agent-neutral.py reads a doc (here, a blank line may come between)."""
    headings: dict[int, str] = {}
    for i, part in enumerate(re.split(r"^(```.*?^```)", text, flags=re.S | re.M)):
        if i % 2:   # a fenced block: each line that starts an entry, with the comment lines under it
            yield from ((entry, " ".join(headings.values())) for entry in re.split(r"\n(?=[^\s#])", part))
            continue
        lead = ""   # the paragraph the next list follows, when it ends in a colon
        for block in re.split(r"\n\s*\n", part):
            for m in re.finditer(r"^(#+)\s.*$", block, re.M):
                headings = {k: v for k, v in headings.items() if k < len(m[1])} | {len(m[1]): m[0]}
            under = " ".join(headings.values())
            if block.lstrip().startswith("|"):
                rows = block.strip().splitlines()
                yield from ((row, f"{under} {rows[0]}") for row in rows)
                lead = ""
                continue
            items = re.split(r"\n(?=\s*(?:[-*]|\d+\.)\s)", block)
            if not re.match(r"\s*(?:[-*]|\d+\.)\s", items[0]):   # a paragraph first, not a list going on
                lead = items[0] if items[0].rstrip().endswith(":") else ""
            yield from ((item, f"{under} {lead}") for item in items)


def _config_key_problems(living: dict[str, str], keys) -> list[str]:
    """Each key no living doc names as a key of .okl/config.json: written `key` or "key" in a
    unit that names the file, or that a heading, table header or lead-in naming it covers. A bare
    word is not enough: `repo` and `owner` are also lesson fields, and `ci` is a folder."""
    covered = set()
    for text in living.values():
        for unit, over in _doc_units(text):
            if "config.json" in unit or "config.json" in over:
                covered |= {k for k in keys if re.search(rf'`{re.escape(k)}`|"{re.escape(k)}"', unit)}
    return [f'`{k}` is in no living doc (README.md, docs/) as a key of .okl/config.json: write it as `{k}` '
            f'or "{k}" where the doc names .okl/config.json, in docs/WHAT-INIT-WRITES.md for a key a '
            "command writes or docs/COSTS-AND-KNOBS.md for a setting" for k in sorted(set(keys) - covered)]


def _python_env_reads(sources: dict[str, str]) -> tuple[dict[str, set[str]], list[str]]:
    """Each environment variable the Python in `sources` reads, with the files that do:
    `os.environ.get(x)`, `os.getenv(x)`, `os.environ[x]` read, `x in os.environ`. A write
    (`os.environ[x] = `, `.pop`, `.setdefault`) is not a read. Also each read whose name is not a
    string, which must fail the test rather than pass it unseen."""
    found: dict[str, set[str]] = {}
    unnamed: list[str] = []
    for path, text in sources.items():
        tree = ast.parse(text)
        uses = [*_key_uses(tree, lambda n: ast.unparse(n) in ("os.environ", "environ"), ("get",), stores=False),
                *((n.lineno, n.args[0]) for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args
                  and ast.unparse(n.func) in ("os.getenv", "getenv"))]
        for line, key in uses:
            if isinstance(key, ast.Constant) and isinstance(key.value, str):
                found.setdefault(key.value, set()).add(path)
            else:
                unnamed.append(f"{path}:{line}: {ast.unparse(key)}")
    return found, unnamed


# What bash sets itself (its manual's "Bash Variables"): expanding one is not an environment read,
# though no line of the script assigns it.
BASH_SETS = frozenset({"BASH", "BASHPID", "BASH_LINENO", "BASH_REMATCH", "BASH_SOURCE", "BASH_VERSION",
                       "EUID", "HOSTNAME", "IFS", "LINENO", "OLDPWD", "OPTARG", "OPTIND", "OSTYPE",
                       "PIPESTATUS", "PPID", "PWD", "RANDOM", "REPLY", "SECONDS", "UID"})
# A shell script read left to right, one token at a time: what expands and what is assigned.
SHELL_TOKEN = re.compile(rf"""
    <<-?[ \t]*(?P<quote>['"]?)(?P<tag>\w+)(?P=quote)(?P<line>[^\n]*)\n(?P<body>.*?)^[ \t]*(?P=tag)[ \t]*$
  | '[^']*'                                                     # single-quoted: nothing expands
  | (?P<double>"(?:[^"\\]|\\.)*")                               # double-quoted: expansions only
  | (?<![^\s;&|()])\#[^\n]*                                     # a comment
  | \\.                                                         # an escaped character
  | (?<![^\s;&|()])(?:(?:local|export|declare|readonly)[ \t]+(?:-\w+[ \t]+)*)?(?P<assign>{NAME})(?:\[[^\]]*\])?\+?=
  | (?<![^\s;&|()])for[ \t]+(?P<loop>{NAME})[ \t]+in\b
  | \$\{{?\#?(?P<ref>{NAME})
""", re.X | re.S | re.M)
EXPANSION = re.compile(rf"\$\{{?\#?({NAME})")
EMBEDDED_READ = re.compile(rf"""environ(?:\.get\(|\[)\s*["']({NAME})["']|getenv\(\s*["']({NAME})["']""")


def _shell_env_reads(text: str) -> set[str]:
    """The upper-case variables a shell script expands before any line of it assigns them (in
    code, in double quotes, and in a heredoc whose delimiter is unquoted), and those its embedded
    Python reads from os.environ that the script does not set itself, such as a value handed to
    python3 on its own command line."""
    expanded: dict[str, int] = {}
    assigned: dict[str, int] = {}
    for m in SHELL_TOKEN.finditer(text):
        if m["assign"] or m["loop"]:
            assigned.setdefault(m["assign"] or m["loop"], m.start())
            continue
        body = "" if m["quote"] else m["body"] or ""
        for name in EXPANSION.findall(m[0] if m["ref"] else m["double"] or f"{m['line'] or ''}\n{body}"):
            expanded.setdefault(name, m.start())
    reads = {name for name, at in expanded.items() if name not in BASH_SETS and assigned.get(name, len(text)) > at}
    return reads | ({a or b for a, b in EMBEDDED_READ.findall(text)} - set(assigned))


def _env_reads(python: dict[str, str], shell: dict[str, str]) -> tuple[dict[str, set[str]], list[str]]:
    """Each environment variable the code reads, with the files that do, and the Python reads
    whose name is not a string."""
    found, unnamed = _python_env_reads(python)
    for path, text in shell.items():
        for name in _shell_env_reads(text):
            found.setdefault(name, set()).add(path)
    return found, unnamed


# The variables okl reads that no doc of okl's explains: each is another program's, read with the
# meaning that program gives it. A variable okl gives a meaning to is documented instead, so keep
# this short.
NOT_OKLS = {
    "CLAUDE_PROJECT_DIR": "Claude Code sets it to the project's root for the hooks it runs, which start there",
    "GITHUB_ACTIONS": "GitHub sets it on its runners; the kit's review script then writes annotations",
    "TMPDIR": "the system's temporary directory, where the Stop hook keeps its once-a-session marker",
    "HF_HUB_OFFLINE": "Hugging Face's offline switch: okl sets it while loading a cached model and reads "
                      "it to put it back",
    "TRANSFORMERS_OFFLINE": "Hugging Face's older name for HF_HUB_OFFLINE, read as huggingface_hub reads it",
}


def _env_problems(living: dict[str, str], reads: dict[str, set[str]], not_okls: dict[str, str]) -> list[str]:
    """Each variable the code reads that no living doc names and NOT_OKLS does not explain, and
    each NOT_OKLS entry the code no longer reads."""
    problems = [f"`{name}` is read by {', '.join(sorted(files))} and named in no living doc (README.md, "
                "docs/): document it beside the variables it works with, or, if another program "
                "defines it, add it to NOT_OKLS with the reason"
                for name, files in sorted(reads.items())
                if name not in not_okls and not any(_names(text, name) for text in living.values())]
    return problems + [f"NOT_OKLS names `{name}`, which okl no longer reads: remove it"
                       for name in sorted(set(not_okls) - set(reads))]


def test_every_config_key_the_code_reads_is_declared():
    """client.CONFIG_KEYS is every .okl/config.json key the code reads or writes, Python and
    hooks, and nothing else (#455): the set the docs test below holds the docs to. A new key fails
    here until it is declared, and then there until a doc names it."""
    from okl.client import CONFIG_KEYS
    python = _committed("src/okl/*.py")
    keys, unnamed = _config_keys_in(python)
    used = set(keys) | set(_hook_config_keys(_shell_sources()))
    # The reader finds a key by the name the config is held under; whatever load_config() returns
    # must be held under one of them, or its keys would go unread.
    elsewhere = [f"{path}:{n.lineno}" for path, text in python.items() for n in ast.walk(ast.parse(text))
                 if isinstance(n, ast.Assign) and ast.unparse(n.value).endswith("load_config()")
                 and not all(ast.unparse(t) in (*CONFIG_HOLDERS, "self.config") for t in n.targets)]

    assert not unnamed, f"a config key this cannot name; use a string or a module's constant: {unnamed}"
    assert not elsewhere, f"hold load_config()'s result as `config` or `cfg`: {elsewhere}"
    assert len(keys) > 12, keys     # okl uses seventeen; a reader that finds few is broken
    assert used == CONFIG_KEYS, (f"used in the code, not in client.CONFIG_KEYS: {sorted(used - CONFIG_KEYS)}; "
                                 f"in CONFIG_KEYS, used nowhere: {sorted(CONFIG_KEYS - used)}")


def test_every_config_key_is_in_the_docs():
    """Every key in client.CONFIG_KEYS is named as a key of .okl/config.json in a living doc
    (README.md, docs/): `key` or "key", where the doc names the file (#455)."""
    from okl.client import CONFIG_KEYS
    problems = _config_key_problems(_living_docs(), CONFIG_KEYS)

    assert not problems, "config keys no doc names:\n  " + "\n  ".join(problems)


def test_every_environment_variable_okl_reads_is_in_the_docs():
    """Every environment variable okl's Python and the shell it ships read is named in a living
    doc, unless NOT_OKLS says whose it is (#455)."""
    reads, unnamed = _env_reads(_committed("src/okl/*.py"), _shell_sources())
    problems = _env_problems(_living_docs(), reads, NOT_OKLS)

    assert not unnamed, f"a variable this cannot name; read it by a string: {unnamed}"
    assert len(reads) > 30, reads   # okl reads over forty; a reader that finds few is broken
    # One from each place: the Python, an agent hook, a gate and the kit's review script.
    assert {"OKL_DATABASE_URL", "OKL_TASK", "OKL_DIAGRAM_OUT_EXT", "REVIEW_BASE_REF"} <= set(reads)
    assert not problems, "environment variables no doc names:\n  " + "\n  ".join(problems)


SHELL_FIXTURE = r"""#!/usr/bin/env bash
LOCAL=1
echo "$LOCAL ${OKL_EXPANDED:-x} $PWD ${#OKL_LENGTH}" '$OKL_SINGLE_QUOTED'
# $OKL_IN_A_COMMENT
cat <<'EOF'
$OKL_IN_A_QUOTED_HEREDOC
EOF
cat <<EOF
$OKL_IN_A_HEREDOC
EOF
echo "OKL_IN_A_STRING=1 is not an assignment"; echo "$OKL_IN_A_STRING"
OKL_HANDED="$x" python3 -c 'import os; print(os.environ["OKL_HANDED"], os.environ.get("OKL_EMBEDDED"))'
"""


def test_the_config_and_environment_checks_name_what_is_missing():
    """Red where they should be: a key or a variable new code reads with no doc, a key's every
    mention removed, a key named away from .okl/config.json, a stale NOT_OKLS entry; and a write,
    a quoted word, a comment and a value handed to python3 are not reads."""
    from okl.client import CONFIG_KEYS
    living = _living_docs()

    # A key new code reads, as a string, through another module's constant, and one it cannot name.
    keys, unnamed = _config_keys_in({
        "src/okl/a.py": 'KEY = "on_edit"\n',
        "src/okl/b.py": "from .a import KEY as K\ndef f(cfg, k):\n"
                        '    return cfg.get("frobnicate"), load_config()[K], self.config.pop(k)\n'})
    assert set(keys) == {"frobnicate", "on_edit"}
    assert unnamed == ["src/okl/b.py:3: k"]
    assert _config_key_problems(living, {"frobnicate"}) == [
        '`frobnicate` is in no living doc (README.md, docs/) as a key of .okl/config.json: write it as '
        '`frobnicate` or "frobnicate" where the doc names .okl/config.json, in docs/WHAT-INIT-WRITES.md '
        "for a key a command writes or docs/COSTS-AND-KNOBS.md for a setting"]
    # Every mention of `owned` as a key removed from the docs.
    dropped = {name: text.replace('"owned"', '"ownd"').replace("`owned`", "`ownd`") for name, text in living.items()}
    assert [p.split(" is ")[0] for p in _config_key_problems(dropped, CONFIG_KEYS)] == ["`owned`"]
    # Named, but not as a key of the file; then under a heading that names it.
    assert _config_key_problems({"a.md": 'Set `"owned"` here.\n'}, {"owned"}) != []
    assert _config_key_problems({"a.md": "## What `.okl/config.json` holds\n\n| Key | What |\n|---|---|\n"
                                         '| `"owned"` | paths |\n'}, {"owned"}) == []

    # A variable read in Python, and one in a hook; writes, quotes, comments and hand-offs are not.
    python = {"src/okl/x.py": 'import os\nos.environ["OKL_SET"] = "1"\nos.environ.pop("OKL_POPPED", None)\n'
                              'a = os.environ.get("OKL_GOT") or os.getenv("OKL_GETENV") or os.environ.get(a)\n'}
    reads, unnamed = _env_reads(python, {"hooks/x.sh": SHELL_FIXTURE})
    assert set(reads) == {"OKL_GOT", "OKL_GETENV", "OKL_EXPANDED", "OKL_LENGTH", "OKL_IN_A_HEREDOC",
                          "OKL_IN_A_STRING", "OKL_EMBEDDED"}
    assert unnamed == ["src/okl/x.py:4: a"]
    assert _env_problems({"a.md": "Set `OKL_GOT`."}, {"OKL_GOT": {"x.py"}, "OKL_NEW": {"x.sh"}}, {}) == [
        "`OKL_NEW` is read by x.sh and named in no living doc (README.md, docs/): document it beside "
        "the variables it works with, or, if another program defines it, add it to NOT_OKLS with the reason"]
    assert _env_problems(living, {}, {"OKL_GONE": "why"}) == [
        "NOT_OKLS names `OKL_GONE`, which okl no longer reads: remove it"]


# Every place the docs say something is not yet measured or still open, and the open question it
# waits on (#334). Docs kept saying "not yet measured" after the measurement had landed, and a
# review caught it three times (the anatomy sheet on #333 had three). The REPORT result or
# CHANGELOG entry that answers a question writes "Settles open question `<id>`"; this test then
# fails until the sentence is rewritten and its entry removed. A new sentence of this kind fails
# until it names its question here, or says in NOT_OPEN why it is not one.
OPEN_PHRASE = re.compile(r"(?i)\b(?:not|never) (?:yet )?(?:been )?measured\b|\bunmeasured\b|\bstill open\b")
OPEN_QUESTIONS = {
    # (file, words of the sentence around the phrase): the question it waits on.
    ("docs/COSTS-AND-KNOBS.md", "how often a check in CI raises a false alarm is not measured yet"):
        "lesson-review-ci-false-alarms",
    ("docs/COSTS-AND-KNOBS.md", "How often it raises one is not measured yet"):
        "lesson-review-before-push-false-alarms",
    ("docs/ACROSS-AN-ORG.md", "Reporting the rate per pack rather than per store is still open in #252"):
        "per-pack-rate",
    ("docs/overview/okl-anatomy.html", "a working session is not yet measured"):
        "one-line-lesson-in-a-working-session",
    ("src/okl/core.py", "no probe prompt has one subject word, so extending it is unmeasured (#282)"):
        "common-word-weight-for-one-word-tasks",
    ("README.md", "It has never been measured; use it to get a new repo"):
        "scaffold-effect",
    ("docs/EVALUATION.md", "and sessions with nothing to learn | Not measured (#251)"):
        "capture-without-fabrication",
    ("src/okl/core.py", "On other repositories it is not yet measured; on this one's 43 graded defects"):
        "review-after-writing-beyond-one-repository",
    ("docs/GETTING-STARTED.md", "Whether a failing check at the edit changes what an agent writes has not been measured yet"):
        "check-on-edit-changes-the-code",
    ("README.md", "whether that holds on real work in another repository is not yet measured"):
        "transfer-to-another-repository",
    ("docs/EVALUATION.md", "not yet measured as a channel"):
        "on-edit-as-a-reach-channel",
    ("README.md", "found the break 0.429 of the time against 0.279 ([REPORT §4bl](evals/REPORT.md)), not yet measured in sessions"):
        "path-question-in-review-sessions",
}
# The phrase, used for something that is not a question waiting on an answer, with why.
NOT_OPEN = {
    ("docs/EVALUATION.md", "is marked unmeasured or removed"): "a rule for public claims, not a question",
    ("README.md", "a bug that is still open"): "about a team's bugs, not about okl",
    ("docs/COMMANDS.md", "REPORT §4s says why it was not measured live"): "a fact about one finished run",
    ("docs/overview/okl-anatomy.html", "Not measured in this A/B"): "scopes one finished A/B",
    ("docs/decisions/2026-07-21-subject-tags-controlled-vocabulary.md", "**Still open:** the rank-cutoff half"):
        "a dated record; its 2026-09-01 entry closes it",
    ("docs/decisions/2026-07-21-subject-tags-controlled-vocabulary.md", 'the "still open" rank cutoff above is closed'):
        "the entry that closes it",
    ("src/okl/recap.py", "**Still open:**"): "a heading in `okl recap`'s output",
    ("docs/DEVELOPING.md", '"not yet measured", "unmeasured" and "still open" sentences'): "describes this check",
}
SETTLES = re.compile(r"Settles open question `([\w-]+)`")


def _open_question_problems(docs: dict[str, str], settled_in: str, questions: dict, not_open: dict) -> list[str]:
    """What is wrong with the docs' open-question sentences: one no entry names, an entry whose
    sentence is gone, or a sentence still in the docs after its question was settled."""
    problems, seen = [], set()
    entries = {**{k: ("open", q) for k, q in questions.items()}, **{k: ("not", w) for k, w in not_open.items()}}
    for name, text in docs.items():
        flat = " ".join(text.split())
        for m in OPEN_PHRASE.finditer(flat):
            covering = [key for key in entries if key[0] == name and any(
                p <= m.start() and m.end() <= p + len(key[1])
                for p in (i.start() for i in re.finditer(re.escape(key[1]), flat)))]
            if not covering:
                problems.append(f"{name}: {flat[max(0, m.start() - 80):m.end() + 40]!r} says something is "
                                "open: name its question in OPEN_QUESTIONS, or say in NOT_OPEN why it is not one")
            seen.update(covering)
    problems += [f"{name}: no longer says {words!r}: remove its entry" for name, words in entries.keys() - seen]
    settled = set(SETTLES.findall(settled_in))
    problems += [f"{name}: still says {words!r}, but open question `{q}` is settled: rewrite the sentence"
                 for (name, words), q in questions.items() if q in settled]
    return problems


def test_every_open_question_in_the_docs_names_what_settles_it():
    """The docs' open questions, held to the REPORT and CHANGELOG that settle them (#334)."""
    docs = {str(p.relative_to(ROOT)): p.read_text() for p in _published_docs()}
    settled_in = (ROOT / "evals" / "REPORT.md").read_text() + (ROOT / "CHANGELOG.md").read_text()

    assert _open_question_problems(docs, settled_in, OPEN_QUESTIONS, NOT_OPEN) == []


def test_the_open_question_check_fails_on_a_settled_question_and_an_unnamed_one():
    """The check is red where it should be: a settled question's sentence still in the docs, a
    new sentence nobody named, and an entry whose sentence is gone."""
    questions = {("a.md", "the warm model's recall is not yet measured"): "warm-recall"}
    docs = {"a.md": "Fast. The warm model's recall\nis not yet measured. Its size is still open."}

    problems = _open_question_problems(docs, "## §9\nSettles open question `warm-recall`.", questions, {})
    assert any("`warm-recall` is settled" in p for p in problems), problems
    assert any("size is still open" in p and "name its question" in p for p in problems), problems

    assert _open_question_problems({"a.md": "Fast."}, "", questions, {}) == [
        "a.md: no longer says \"the warm model's recall is not yet measured\": remove its entry"]


# What the docs claim about an optional or opt-in part of okl, and the condition each place it is
# said must also name (the findings log's "absolute public claim broader than a shipped opt-in
# file", three times: "no generative model ever" while the scaffold's review step runs one when
# named; a lesson "misses" a task with no shared word while the warm model finds it by meaning;
# --owner "makes each change need your approval" while that needs a branch rule okl does not set).
# A claim is held where it is said: its paragraph, list item or table row must carry the condition.
# A new claim of this kind goes here with its condition, so the next doc that repeats it is held too.
OPT_IN_CLAIMS = {
    r"calls no generative model": (r"(?=.*(?:only if you name one|REVIEW_CMD))(?=.*okl review)",
                                   "the scaffold's review step runs a model when REVIEW_CMD names one, "
                                   "and okl review runs one when the person runs it"),
    r"shares no exact word with a lesson misses it": (r"[Ww]ithout the warm model",
                                                      "the warm model finds a lesson by meaning once indexed"),
    r"CI runs what your hooks run": (r"installed from PyPI",
                                     "only an okl installed from an index writes the pin CI installs"),
    r"--owner @you`?[^|]*?needs? your approval": (r"branch rule|code-owner review",
                                                   "GitHub enforces the owner only with a rule requiring "
                                                   "code-owner review, which okl does not set"),
}


def _opt_in_claim_problems(docs: dict[str, str], claims: dict) -> list[str]:
    """Each place a claim is made without its condition, and each claim no doc makes any more."""
    problems, seen = [], set()
    for name, text in docs.items():
        # A paragraph, a list item or a table row: the condition must sit where the claim does.
        for unit in re.split(r"\n\s*\n|\n(?=\s*[-*|] )|</?(?:li|p|tr)\b[^>]*>", text):
            flat = " ".join(unit.split())
            for claim, (condition, why) in claims.items():
                if re.search(claim, flat):
                    seen.add(claim)
                    if not re.search(condition, flat):
                        problems.append(f"{name}: {flat[:160]!r} claims {claim!r} without its condition ({why})")
    return problems + [f"no doc claims {c!r} any more: remove its entry" for c in claims if c not in seen]


def test_every_opt_in_claim_names_its_condition_where_it_is_made():
    """The claims in OPT_IN_CLAIMS, held in every published doc."""
    docs = {str(p.relative_to(ROOT)): p.read_text() for p in _published_docs()}

    assert _opt_in_claim_problems(docs, OPT_IN_CLAIMS) == []


def test_the_opt_in_claim_check_fails_on_a_bare_claim_and_a_stale_entry():
    """Red where it should be: the claim without its condition, in its own paragraph."""
    claims = {r"calls no generative model": (r"only if you name one", "the review step")}
    docs = {"a.md": "okl calls no generative model.\n\nThe review step runs one only if you name one.\n"}

    assert _opt_in_claim_problems(docs, claims) == [
        "a.md: 'okl calls no generative model.' claims 'calls no generative model' without its condition "
        "(the review step)"]
    assert _opt_in_claim_problems({"a.md": "okl calls no generative model, and the review step runs one "
                                           "only if you name one."}, claims) == []
    assert _opt_in_claim_problems({"a.md": "Nothing here."}, claims) == [
        "no doc claims 'calls no generative model' any more: remove its entry"]


def test_the_docs_state_defaults_as_the_code_has_them():
    """COSTS-AND-KNOBS, COMMANDS and GETTING-STARTED quote on-edit's defaults: the seconds a check gets
    after an edit, the seconds one edit gets, the hook's registered timeout and --quick's limit; and
    COMMANDS quotes `okl dedup`'s threshold. Each quote is built here from the constants, so a default
    changed without its docs, or a doc changed without its default, fails (#470, #455). The
    CHANGELOG's released sections are history, not held to later code."""
    from okl.cli.on_edit import BUDGET, HOOK_TIMEOUT, QUICK, TIMEOUT
    from okl.core import DEDUP_THRESHOLD
    quotes = {
        "docs/COSTS-AND-KNOBS.md": [f"at most {TIMEOUT} seconds each and {BUDGET} an edit",
                                    f"last passing run took {QUICK} seconds or less",
                                    f"above 0 and up to {TIMEOUT}"],
        "docs/COMMANDS.md": [f"--timeout ({TIMEOUT} s) and one edit --budget ({BUDGET} s)",
                             f"(default {DEDUP_THRESHOLD}, set to over-report)"],
        "docs/GETTING-STARTED.md": [f"last passing run took {QUICK} s or less",
                                    f"each gets {TIMEOUT} seconds and one edit gets {BUDGET} in all, inside the "
                                    f"{HOOK_TIMEOUT}-second timeout",
                                    f"passed in {QUICK} seconds or less", f"above 0 and up to {TIMEOUT}"],
    }
    missing = [(doc, q) for doc, qs in quotes.items() for q in qs
               if q not in " ".join((ROOT / doc).read_text().split())]
    assert not missing, f"a doc no longer quotes a default as the code has it: {missing}"
