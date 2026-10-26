#!/usr/bin/env python3
"""Real prompts with the conversation before them: a pooled, judged test set for the briefing (REPORT §4x).

    python3 evals/bench/real_prompts.py snapshot              # once: private/real-store.db
    PYTHONPATH=src python3 evals/bench/real_prompts.py pool --split tuning
    # Sonnet judges label each private/real-judge-<split>-<n>.jsonl into ...-out-<n>.jsonl
    PYTHONPATH=src python3 evals/bench/real_prompts.py tally --split tuning > evals/results/real-<date>-tuning.txt

Why: §4w measured the decision on generated queries and judged it on real prompts it was never
tuned on, and on those it found about a quarter fewer of the lessons that apply. Real prompts
are terse because their subject is in the turns before them, and the prompt hook can read
that transcript. This instrument tunes and tests on what people actually type.

The prompts are the TASK-labelled ones from projects a person typed in (the A/B harness's and
the e2e scratch repos' prompts are authored tasks, not a person's, and are left out), with the
two typed prompts and the assistant reply before each (extract_context.py). They split by the
parity of a salted hash of their id into a tuning half and a held-out half; a seeded sample of
each is pooled. The corpus is a snapshot of this machine's own store, as of each prompt: a
lesson recorded after the prompt (perhaps because of it) is not in its store; the seed packs
always are.

Arms, every one through core.check:
- floor: the word floor, up to 12 (the default before §4w);
- calibrated: the default since §4w;
- context arms, the calibrated decision and its line over the prompt followed by its context:
  `prev` adds the previous typed prompt; `prev-own` also briefs only lessons sharing at least
  one word with the prompt itself; `reply-own` adds the assistant's last reply as well, always
  with the prompt's own word required, since a long reply would otherwise brief on its own.

A first design re-set each context arm's line on the null prompts with their context. Measured
before any judging, it was self-defeating: a continuation prompt ("ok, do it") carries its
previous turn's subject, so the lines rose to 4 to 9 shared words and the context arms briefed
fewer lessons than the calibrated arm (REPORT §4x). Briefing a continuation a relevant new
lesson is not the harm; repeating the last turn's briefing is. So the context arms keep the
calibrated line, and the instrument measures both kinds of prompt:

- task prompts: judged precision and pooled recall;
- null prompts (from the unseen half, never used to set the line): how often each arm briefs
  one, and the judged precision of what it briefs there;
- both: the repeat rate, the share of an arm's briefing that the previous typed prompt's own
  calibrated briefing already held.

Every lesson any arm briefs for a prompt is pooled and judged once, the prompt shown with its
context, the lessons shuffled and unmarked by arm. Recall is pooled: of the applying lessons
any arm found. The selection rule, fixed before any judging: the context arm that finds the
most applying lessons on the tuning half's task prompts, among those whose judged precision
there is at least the calibrated arm's; ties go to fewer lessons per prompt.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sqlite3
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as bench

from okl import core, decide
from okl.store import EDGE_RELS, Node, Store

PRIVATE = bench.ROOT / "evals" / "bench" / "private"
SNAPSHOT = PRIVATE / "real-store.db"
PER_BATCH = 15
HARNESS_PROJECTS = ("okl-ab-", "okl-e2e")
CONTEXT_ARMS = ("prev", "prev-own", "reply-own")
ARMS = ("floor", "calibrated", *CONTEXT_ARMS)


def _rows(name: str) -> list[dict]:
    return [json.loads(x) for x in (PRIVATE / name).read_text().splitlines() if x.strip()]


def prompts(label: str) -> list[dict]:
    """The labelled prompts (task or null) a person typed, each with its context and time."""
    ctx = {r["id"]: r for r in _rows("context.jsonl")}
    out = []
    for p in _rows(f"{label}_prompts.jsonl"):
        c = ctx.get(p["id"])
        if c and not any(k in c["project"] for k in HARNESS_PROJECTS):
            out.append({**p, **c})
    return out


def split_of(prompt: dict) -> str:
    """Tuning or held out, by a salted hash so it is independent of the null prompts' halves."""
    return "tuning" if int(hashlib.sha256(f"real:{prompt['id']}".encode()).hexdigest(), 16) % 2 == 0 else "heldout"


def repo_of(prompt: dict) -> str:
    """The repo a prompt's session ran in, as its project folder names it (…-Dev-okl → okl)."""
    return prompt["project"].split("-Dev-")[-1].lower()


def millis(at: str | None) -> int:
    """An ISO timestamp from a transcript, in epoch milliseconds; no timestamp is "now"."""
    if not at:
        return 10**15
    return int(datetime.fromisoformat(at.replace("Z", "+00:00")).timestamp() * 1000)


class Stores:
    """The snapshot as of a moment: every seed lesson, and the recorded lessons created before it."""

    def __init__(self) -> None:
        self.full = Store(f"sqlite:///{SNAPSHOT}")
        self.nodes = self.full.all_nodes()
        self.recorded = sorted((n for n in self.nodes if not n.id.startswith("seed:")), key=lambda n: n.created_at)
        self.edges = self.full.edges(sorted(EDGE_RELS))
        self._cache: dict[int, Store] = {}

    def as_of(self, ms: int) -> Store:
        """The store a prompt at `ms` was checked against, built once per distinct moment."""
        k = sum(1 for n in self.recorded if n.created_at < ms)
        if k not in self._cache:
            keep = {n.id for n in self.nodes if n.id.startswith("seed:")} | {n.id for n in self.recorded[:k]}
            s = Store("sqlite:///:memory:")
            # Copied as stored: these nodes passed validation when they were written.
            for n in sorted((n for n in self.nodes if n.id in keep), key=lambda n: n.type != "Vocabulary"):
                s._impl.upsert_node(n)
            for e in self.edges:
                if e.src in keep and e.dst in keep:
                    s._impl.upsert_edge(e)
            self._cache[k] = s
        return self._cache[k]


def context_text(prompt: dict, arm: str) -> str:
    """What a context arm reads after the prompt: the previous typed prompt, and the reply."""
    parts = list(prompt["previous"][-1:])
    if arm.startswith("reply") and prompt.get("reply"):
        parts.append(prompt["reply"])
    return "\n".join(parts)


@contextmanager
def _own_words(own: list[str] | None) -> Iterator[None]:
    """Run core.check's calibrated decision so that, when `own` is given, it briefs only
    lessons sharing at least one of those words (the prompt's own)."""
    saved_select = decide.select

    def select(candidates: list[Node], task_terms: list[str],
               rarity: decide.Rarity) -> tuple[list[Node], dict[str, list[str]], int]:
        kept, matched, weak = saved_select(candidates, task_terms, rarity)
        if own is not None:
            mine = {w.lower() for w in own}
            dropped = [n for n in kept if not mine & set(matched.get(n.id, []))]
            kept = [n for n in kept if n not in dropped]
            weak += len(dropped)
        return kept, matched, weak

    decide.select = select
    try:
        yield
    finally:
        decide.select = saved_select


def brief(store: Store, prompt: dict, arm: str) -> list[str]:
    """The lesson ids an arm briefs for a prompt."""
    repo = repo_of(prompt)
    if arm == "floor":
        return core.briefed_ids(core.check(store, repo, prompt["text"], interests=None, decision="floor"))
    if arm == "calibrated":
        return core.briefed_ids(core.check(store, repo, prompt["text"], interests=None, decision="calibrated"))
    task = "\n".join(x for x in (prompt["text"], context_text(prompt, arm)) if x)
    own = core.briefing_terms(prompt["text"]) if arm.endswith("-own") else None
    with _own_words(own):
        return core.briefed_ids(core.check(store, repo, task, interests=None, decision="calibrated"))


def previous_briefing(store: Store, prompt: dict) -> list[str]:
    """What the previous typed prompt was briefed by itself, calibrated: the repeat baseline."""
    if not prompt["previous"]:
        return []
    return brief(store, {**prompt, "text": prompt["previous"][-1]}, "calibrated")


def sample(label: str, split: str, n: int, seed: int) -> list[dict]:
    """A seeded sample of a split's prompts: task prompts, or null prompts from the unseen half
    (the half the calibrated line was never set on)."""
    pool = [p for p in prompts(label) if split_of(p) == split]
    if label == "null":
        pool = [p for p in pool if not bench.is_calibration(p)]
    rng = random.Random(f"{seed}:{label}")  # noqa: S311 - a reproducible sample, not a secret
    return rng.sample(sorted(pool, key=lambda p: p["id"]), min(n, len(pool)))  # NOSONAR - seeded on purpose


def cmd_snapshot(_args: argparse.Namespace) -> None:
    """Copy this machine's store to private/real-store.db, consistently, and print its hash."""
    src = bench.ROOT / ".okl" / "okl.db"
    with sqlite3.connect(src) as a, sqlite3.connect(SNAPSHOT) as b:
        a.backup(b)
    print(f"snapshot {SNAPSHOT.name}: sha {bench.digest([SNAPSHOT])}", file=sys.stderr)


def cmd_pool(args: argparse.Namespace) -> None:
    """Brief the sampled task and null prompts under every arm and write the blind judging batches."""
    stores = Stores()
    # A copy faithful to the snapshot briefs what the snapshot briefs; check before trusting it.
    full = stores.as_of(10**15)
    for p in sample("task", args.split, 20, args.seed):
        for arm in ("floor", "calibrated"):
            # Sets: a rebuilt full-text index may order exact ties differently.
            if set(brief(full, p, arm)) != set(brief(stores.full, p, arm)):
                sys.exit("ABORT: the rebuilt store briefs differently from the snapshot; fix Stores first")
    chosen = ([("task", p) for p in sample("task", args.split, args.sample, args.seed)]
              + [("null", p) for p in sample("null", args.split, args.nulls, args.seed)])
    briefed: dict[str, dict[str, list[str]]] = {arm: {} for arm in ARMS}
    before: dict[str, list[str]] = {}
    for _label, p in chosen:
        store = stores.as_of(millis(p["at"]))
        for arm in ARMS:
            briefed[arm][p["id"]] = brief(store, p, arm)
        before[p["id"]] = previous_briefing(store, p)
    rng = random.Random(f"{args.seed}:{args.split}")  # noqa: S311 - a reproducible shuffle, not a secret
    nodes = {n.id: n for n in stores.nodes}
    items = []
    order = list(range(len(chosen)))
    rng.shuffle(order)  # NOSONAR - task and null prompts interleaved for the judge, reproducibly
    for i in order:
        _label, p = chosen[i]
        pooled = sorted({lid for arm in ARMS for lid in briefed[arm][p["id"]]})
        if not pooled:
            continue
        rng.shuffle(pooled)  # NOSONAR - the seeded order the judge reads, reproducible on purpose
        items.append({"item": i, "prompt": p["text"], "previous": p["previous"], "reply": p.get("reply", ""),
                      "lessons": [{"n": j, "title": nodes[lid].title, "symptom": nodes[lid].symptom or "",
                                   "fix": nodes[lid].fix or ""} for j, lid in enumerate(pooled)],
                      "_ids": pooled})
    for b in range(0, len(items), PER_BATCH):
        with (PRIVATE / f"real-judge-{args.split}-{b // PER_BATCH}.jsonl").open("w") as f:
            for it in items[b:b + PER_BATCH]:
                f.write(json.dumps({k: v for k, v in it.items() if k != "_ids"}) + "\n")
    meta = {"split": args.split, "seed": args.seed, "chosen": [[label, p["id"]] for label, p in chosen],
            "briefed": briefed, "before": before, "pooled": {str(it["item"]): it["_ids"] for it in items},
            "store": bench.digest([SNAPSHOT])}
    (PRIVATE / f"real-arms-{args.split}.json").write_text(json.dumps(meta))
    pairs = sum(len(it["_ids"]) for it in items)
    print(f"{sum(1 for x in chosen if x[0] == 'task')} task and {sum(1 for x in chosen if x[0] == 'null')} null "
          f"prompts · {pairs} (prompt, lesson) pairs on {len(items)} prompts · {-(-len(items) // PER_BATCH)} batches",
          file=sys.stderr)


def _arm_row(ids: list[str], b: dict[str, list[str]], before: dict[str, list[str]],
             verdict: dict[tuple[str, str], str | None], applies: dict[str, set[str]]) -> dict:
    """One arm's figures over a set of prompts."""
    judged = [verdict[(pid, lid)] for pid in ids for lid in b[pid]
              if verdict.get((pid, lid)) in ("APPLIES", "DOES_NOT_APPLY")]
    shown = sum(len(b[pid]) for pid in ids)
    return {"yes": judged.count("APPLIES"), "judged": len(judged),
            "found": sum(len(applies[pid] & set(b[pid])) for pid in ids),
            "hit": sum(1 for pid in ids if applies[pid] & set(b[pid])),
            "any": sum(1 for pid in ids if b[pid]),
            "per": shown / len(ids) if ids else 0.0,
            "off": judged.count("DOES_NOT_APPLY") / len(ids) if ids else 0.0,
            "repeat": sum(len(set(b[pid]) & set(before[pid])) for pid in ids) / shown if shown else 0.0}


def cmd_tally(args: argparse.Namespace) -> None:
    """Join the judges' labels to the arms and print the receipt."""
    meta = json.loads((PRIVATE / f"real-arms-{args.split}.json").read_text())
    label: dict[tuple[int, int], str] = {}
    for f in sorted(PRIVATE.glob(f"real-judge-{args.split}-*-out.jsonl")):
        for o in _rows(f.name):
            label[(int(o["item"]), int(o["n"]))] = o["label"]
    chosen = meta["chosen"]
    verdict: dict[tuple[str, str], str | None] = {}
    for item, ids in meta["pooled"].items():
        for n, lid in enumerate(ids):
            verdict[(chosen[int(item)][1], lid)] = label.get((int(item), n))
    missing = sum(1 for v in verdict.values() if v is None)
    applies: dict[str, set[str]] = defaultdict(set)
    for (pid, lid), v in verdict.items():
        if v == "APPLIES":
            applies[pid].add(lid)
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=bench.ROOT, check=False).stdout.strip()
    print(f"real prompts · split {args.split} (seed {meta['seed']}) · store {meta['store']} · code {commit}")
    print(f"{len(verdict)} pooled pairs, labels missing {missing}")
    stats = {}
    for kind in ("task", "null"):
        ids = [pid for k, pid in chosen if k == kind]
        total = sum(len(applies[pid]) for pid in ids)
        with_any = sum(1 for pid in ids if applies[pid])
        print(f"\n{kind} prompts: {len(ids)} person-typed · {with_any} with an applying lesson · "
              f"{total} applying lessons in the pool")
        print(f"  {'arm':11} {'precision [95%]':>22} {'applying found':>15} {'prompts hit':>12} {'briefed any':>12} "
              f"{'lessons/prompt':>15} {'off-topic/prompt':>17} {'repeat':>7}")
        for arm in ARMS:
            r = _arm_row(ids, meta["briefed"][arm], meta["before"], verdict, applies)
            lo, hi = bench.wilson(r["yes"], r["judged"]) if r["judged"] else (0.0, 0.0)
            prec = f"{r['yes'] / r['judged']:.1%} [{lo:.1%}, {hi:.1%}]" if r["judged"] else "n/a"
            print(f"  {arm:11} {prec:>22} {r['found']:>7} of {total:<5} {r['hit']:>5} of {with_any:<4} "
                  f"{r['any']:>5} of {len(ids):<4} {r['per']:>15.2f} {r['off']:>17.2f} {r['repeat']:>7.0%}")
            if kind == "task":
                stats[arm] = (r["yes"] / r["judged"] if r["judged"] else 0.0, r["found"], r["per"])
    # The selection rule, fixed before any judging (module docstring).
    eligible = [a for a in CONTEXT_ARMS if stats[a][0] >= stats["calibrated"][0]]
    pick = min(eligible, key=lambda a: (-stats[a][1], stats[a][2])) if eligible else None
    print(f"\nselection rule: {pick or 'no context arm'} "
          + ("(most applying lessons found on task prompts among the context arms at least as precise as calibrated)"
             if pick else "(none is at least as precise as calibrated on task prompts)"))


def main() -> None:
    """Snapshot the store, pool a split for judging, or tally the judges' labels."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot")
    pp = sub.add_parser("pool")
    pp.add_argument("--split", choices=["tuning", "heldout"], required=True)
    pp.add_argument("--sample", type=int, default=120, help="task prompts")
    pp.add_argument("--nulls", type=int, default=60, help="null prompts, from the unseen half")
    pp.add_argument("--seed", type=int, default=11)
    pt = sub.add_parser("tally")
    pt.add_argument("--split", choices=["tuning", "heldout"], required=True)
    args = ap.parse_args()
    {"snapshot": cmd_snapshot, "pool": cmd_pool, "tally": cmd_tally}[args.cmd](args)


if __name__ == "__main__":
    main()
