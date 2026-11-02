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
NO_EVIDENCE = {"each session's lessons are recorded": "the Stop hook's behaviour, held by its tests, not a measurement"}


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
    return {
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
    """Every `okl <command> --flag` in the README, docs/ and the overview sheets is one the CLI
    has (#314): only `okl init`'s flags, in three docs, were checked before."""
    found, checked = _doc_commands().problems(_doc_commands().docs())

    assert found == []
    assert checked > 400, checked             # the docs write hundreds; none found means a broken reader


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


# Every place the docs say something is not yet measured or still open, and the open question it
# waits on (#334). Docs kept saying "not yet measured" after the measurement had landed, and a
# review caught it three times (the anatomy sheet on #333 had three). The REPORT result or
# CHANGELOG entry that answers a question writes "Settles open question `<id>`"; this test then
# fails until the sentence is rewritten and its entry removed. A new sentence of this kind fails
# until it names its question here, or says in NOT_OPEN why it is not one.
OPEN_PHRASE = re.compile(r"(?i)\b(?:not|never) (?:yet )?(?:been )?measured\b|\bunmeasured\b|\bstill open\b")
OPEN_QUESTIONS = {
    # (file, words of the sentence around the phrase): the question it waits on.
    ("docs/ACROSS-AN-ORG.md", "Reporting the rate per pack rather than per store is still open in #252"):
        "per-pack-rate",
    ("docs/overview/okl-anatomy.html", "a working session is not yet measured"):
        "one-line-lesson-in-a-working-session",
    ("src/okl/core.py", "no probe prompt has one subject word, so extending it is unmeasured (#282)"):
        "common-word-weight-for-one-word-tasks",
    ("README.md", "It has never been measured; use it to get a new repo"):
        "scaffold-effect",
}
# The phrase, used for something that is not a question waiting on an answer, with why.
NOT_OPEN = {
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
    r"calls no generative model": (r"only if you name one|REVIEW_CMD",
                                   "the scaffold's review step runs a model when REVIEW_CMD names one"),
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
