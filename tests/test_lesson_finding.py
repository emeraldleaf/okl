"""REPORT §4bl: the section quotes its receipt, and the receipt's summary is what its rows say.

Reads only committed files: the prompts' inputs are private and are not in CI (lesson n_119528a07fa5).
"""
import json
from pathlib import Path
from statistics import mean

REPO = Path(__file__).resolve().parent.parent
RECEIPT = "lesson-finding-20261117-0441.json"


def _receipt() -> dict:
    return json.loads((REPO / "evals" / "results" / RECEIPT).read_text())


def _section() -> str:
    report = (REPO / "evals" / "REPORT.md").read_text()
    start = report.index("## 4bl.")
    return " ".join(report[start:report.index("\n## ", start + 1)].split())


def _by(rows, kind, variant, role=None):
    return {r["id"]: r for r in rows if r["kind"] == kind and r["variant"] == variant and r.get("role") == role}


def test_the_summary_is_what_the_rows_say():
    """Reach, the checkers' rates and the joined catches, recomputed from the 343 rows."""
    r = _receipt()
    rows = r["rows"]
    assert r["calls"] == len(rows) == 343 and r["of"] == 344
    for v in ("n10", "n30"):
        got = [x["reached"] for x in _by(rows, "pick", v).values()]
        assert r["reach"][v]["rate"] == round(mean(got), 3)
    for key, s in r["said_breaks"].items():
        variant, role = key.split()
        got = [x["breaks"] for x in _by(rows, "check", variant, role).values()]
        assert s["rate"] == round(mean(got), 3) and s["tasks"] == len(got), key
    reach10 = {i: x["reached"] for i, x in _by(rows, "pick", "n10").items()}
    ask = {i: x["breaks"] for i, x in _by(rows, "check", "sonnet-ask", "right").items()}
    assert r["pick_then_check"]["pick 10, sonnet-ask (today)"]["rate"] == round(
        mean(float(reach10[i] and ask[i]) for i in sorted(set(reach10) & set(ask))), 3)
    assert not str(r["okl_commit"]).endswith("+dirty") and r["models"] == ["claude-haiku-5-5", "claude-sonnet-5-5"]


def test_the_section_quotes_the_receipt():
    """Every figure in §4bl's tables and prose is the receipt's."""
    r, text = _receipt(), _section()
    sb = r["said_breaks"]
    assert RECEIPT in text and f"{r['calls']} of {r['of']} calls answered" in text
    assert f"${r['api_priced_usd']:.0f} API-priced" in text
    assert (f"Sonnet's ten held the right lesson on {r['reach']['n10']['rate']} of the 43 tasks, and its thirty on "
            f"{r['reach']['n30']['rate']}: {r['reach_n30_minus_n10']['mean']} more (95% interval "
            f"{r['reach_n30_minus_n10']['ci95'][0]} to {r['reach_n30_minus_n10']['ci95'][1]})") in text
    cost = r["usd_per_call"]
    for label, v in (("Sonnet, today's question", "sonnet-ask"), ("Sonnet, listing every path first", "sonnet-paths"),
                     ("Haiku, listing every path first", "haiku-paths")):
        assert (f"| {label} | {sb[v + ' right']['rate']} | {sb[v + ' decoy']['rate']:g} | "
                f"${cost['check ' + v]:.3f} |") in text, label
    p, pd = r["paths_minus_ask_on_right"], r["paths_minus_ask_on_decoy"]
    assert (f"found {p['mean']} more of the right lessons ({p['ci95'][0]} to {p['ci95'][1]}) for {pd['mean']} more "
            f"decoys ({pd['ci95'][0]:g} to {pd['ci95'][1]})") in text
    h, hd = r["haiku_minus_sonnet_on_right"], r["haiku_minus_sonnet_on_decoy"]
    assert (f"on {h['mean']} more of the right lessons than Sonnet ({h['ci95'][0]} to {h['ci95'][1]}) and on "
            f"{hd['mean']} more of the decoys ({hd['ci95'][0]} to {hd['ci95'][1]})") in text
    joined = r["pick_then_check"]
    for label, key in (("pick 10, Sonnet with today's question (as the review runs now)", "pick 10, sonnet-ask (today)"),
                       ("pick 10, Sonnet listing every path", "pick 10, sonnet-paths"),
                       ("pick 30, Sonnet listing every path", "pick 30, sonnet-paths"),
                       ("pick 30, Haiku listing every path", "pick 30, haiku-paths"),
                       ("pick 30, Haiku screens, then Sonnet listing every path confirms",
                        "pick 30, haiku-paths screen then sonnet-paths")):
        assert f"| {label} | {joined[key]['rate']:g} |" in text, label
