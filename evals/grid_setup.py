"""What the selection-set grids share (window_grid, admission_grid and common_word_grid, for
REPORT §4u and §4v): the local store and its config, the probe's own rephrasings, the authored
tasks, the six no-match prompts, and the two measures the probe reports. Imported, not run;
each grid's docstring says how to run it. Nothing is opened at import: the store and the files are
read by `load()` on first use (#486), and the old names (`grid_setup.store`, `.REPO`, ...) still
resolve, through it.
"""
import ast
import functools
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, "src")
from okl import core
from okl.client import Client, load_config


@functools.cache
def load() -> SimpleNamespace:
    """The local store and its config, the probe's rephrasings, the authored tasks and the six prompts,
    read once, when a grid first needs them; at import this opened the store (#486)."""
    store = Client()._local_store()
    cfg = load_config()
    src = Path("evals/probe_rephrase.py").read_text()
    return SimpleNamespace(
        store=store, cfg=cfg, REPO=cfg.get("repo") or "okl", INTERESTS=cfg.get("interests"), src=src,
        variants=ast.literal_eval(re.search(r"VARIANTS = (\{.*?\n\})\n", src, re.S).group(1)),
        tasks={json.loads(line)["id"]: json.loads(line)
               for line in Path("evals/tasks.jsonl").read_text().splitlines() if line.strip()},
        prompts=json.loads(Path("evals/probe_prompts.json").read_text())["prompts"])


def __getattr__(name: str) -> Any:
    """`grid_setup.store` and the other names the grids read, from `load()` on first access."""
    loaded = load()
    if hasattr(loaded, name):
        return getattr(loaded, name)
    raise AttributeError(f"module 'grid_setup' has no attribute {name!r}")


LABELS = ("authored", "ticket", "paraphrase", "bug-report")
BUCKETS = ("rules", "relevant_defects", "armed_gates", "live_retractions", "in_scope_tombstones",
           "threat_prior_art", "vocabulary", "decisions", "context")


def returned(res: dict) -> set[str]:
    """Ids of every record a check result briefed."""
    return {r["id"] for b in BUCKETS for r in res.get(b, [])}


def governing_hits(hybrid: str | None, grid: str) -> dict[str, int]:
    """Governing lessons briefed per variant (harness config: no interests). A hybrid row whose
    semantic arm did not run stops the grid, named, rather than print lexical numbers."""
    s = load()
    hits = dict.fromkeys(LABELS, 0)
    for tid, t in s.tasks.items():
        for label, text in zip(LABELS, [t["task"], *s.variants[tid]], strict=True):
            res = core.check(s.store, repo=s.REPO, task=text, interests=None, hybrid=hybrid)
            if hybrid and res.get("hybrid_unavailable"):
                sys.exit(f"{grid}: {res['hybrid_unavailable']}")
            hits[label] += t["defect_node"] in returned(res)
    return hits


def prompt_counts(hybrid: str | None) -> list[int]:
    """Records each of the six no-match prompts returns (hook config: the repo's interests)."""
    s = load()
    return [len(returned(core.check(s.store, repo=s.REPO, task=p, interests=s.INTERESTS, hybrid=hybrid)))
            for p in s.prompts]
