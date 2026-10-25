"""What the selection-set grids share (window_grid, admission_grid and common_word_grid, for
REPORT §4u and §4v): the local store and its config, the probe's own rephrasings, the authored
tasks, the six no-match prompts, and the two measures the probe reports. Imported, not run;
each grid's docstring says how to run it.
"""
import ast
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, "src")
from okl import core
from okl.client import Client, load_config

store = Client()._local_store()
cfg = load_config()
REPO = cfg.get("repo") or "okl"
INTERESTS = cfg.get("interests")
src = Path("evals/probe_rephrase.py").read_text()
variants = ast.literal_eval(re.search(r"VARIANTS = (\{.*?\n\})\n", src, re.S).group(1))
tasks = {json.loads(line)["id"]: json.loads(line)
         for line in Path("evals/tasks.jsonl").read_text().splitlines() if line.strip()}
prompts = json.loads(Path("evals/probe_prompts.json").read_text())["prompts"]
LABELS = ("authored", "ticket", "paraphrase", "bug-report")
BUCKETS = ("rules", "relevant_defects", "armed_gates", "live_retractions", "in_scope_tombstones",
           "threat_prior_art", "vocabulary", "decisions", "context")


def returned(res: dict) -> set[str]:
    """Ids of every record a check result briefed."""
    return {r["id"] for b in BUCKETS for r in res.get(b, [])}


def governing_hits(hybrid: str | None, grid: str) -> dict[str, int]:
    """Governing lessons briefed per variant (harness config: no interests). A hybrid row whose
    semantic arm did not run stops the grid, named, rather than print lexical numbers."""
    hits = dict.fromkeys(LABELS, 0)
    for tid, t in tasks.items():
        for label, text in zip(LABELS, [t["task"], *variants[tid]], strict=True):
            res = core.check(store, repo=REPO, task=text, interests=None, hybrid=hybrid)
            if hybrid and res.get("hybrid_unavailable"):
                sys.exit(f"{grid}: {res['hybrid_unavailable']}")
            hits[label] += t["defect_node"] in returned(res)
    return hits


def prompt_counts(hybrid: str | None) -> list[int]:
    """Records each of the six no-match prompts returns (hook config: the repo's interests)."""
    return [len(returned(core.check(store, repo=REPO, task=p, interests=INTERESTS, hybrid=hybrid)))
            for p in prompts]
