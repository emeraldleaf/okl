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
    sized = (ROOT / "evals" / "results" / "real-20261026-heldout-size.txt").read_text()
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
