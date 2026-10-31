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

Fix arms, added after the tuning half showed the calibrated decision found 3 of the 55 applying
recorded lessons (they carry no triggers, and the decision reads only title, symptom, aliases
and triggers):

- `fallback`: a lesson without triggers is scored on its body and fix as well;
- `backfill`: the recorded advice lessons carry triggers written from each lesson alone by a
  model that never saw a prompt (private/backfill-triggers.jsonl), as the seed packs' were;
- `backfill+fallback`: both.

`pool --extend` briefs the already-sampled prompts with the arms a split's pool lacks and
judges only the pairs no arm had briefed. The fix rule, fixed before any fix arm's pair was
judged: the fix arm that finds the most applying lessons on the tuning half's task prompts,
among those whose judged precision there is at least the calibrated arm's; ties go to fewer
lessons per prompt.

Sweep arms, added after the fix arms showed the binding constraint is the line itself (they
moved the calibrated arm from 1.07 to at most 1.37 lessons per task prompt): a terse real
prompt rarely shares three words with the lesson that applies.

- `floor-3`, `floor-5`: the word floor, at most 3 or 5 lessons;
- `line2`, `line2+backfill`: the calibrated decision with a line of two shared words (any
  rarity), on the store as it is and with the recorded lessons' written triggers;
- `line1+backfill`: one shared word, at most five, with the written triggers.

The sweep rule, written before any sweep arm's pair was judged and applied over every arm
measured on the tuning half: the highest F1 of judged precision and pooled recall on task
prompts, among arms briefing at most five lessons per prompt; ties go to fewer lessons per
prompt. The sweep is a choice made on the tuning half after reading its earlier results, so
only the held-out half can say whether it holds.

Tier arms, added after the held-out half showed every arm that briefs at most five lessons
reaching under half of the applying lessons the floor reached (REPORT §4y): the default should
not hide a lesson that matched.

- `tiered`: core.check's tiered decision on the store with the written triggers, counting
  every lesson it names: those it shows in full and those it lists one line each;
- `tiered-full`: the same check, counting only the lessons it shows in full.

The tier rule, written before any tier arm's pair was judged: tiered becomes the default if, on
the held-out half's task prompts, it reaches at least as many applying lessons as the floor.
`size` renders each sampled prompt's briefing under the floor, backfill and tiered arms and
prints its size; the rule for the line's content is in REPORT §4y.
"""
from __future__ import annotations

import argparse
import base64
import dataclasses
import hashlib
import json
import random
import sqlite3
import statistics
import subprocess
import sys
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as bench
from extract_prompts import HARNESS_PROJECTS

from okl import core, decide, warm
from okl import store as okl_store
from okl.store import EDGE_RELS, Node, Store

PRIVATE = bench.ROOT / "evals" / "bench" / "private"
SNAPSHOT = PRIVATE / "real-store.db"
PER_BATCH = 15
BACKFILL = PRIVATE / "backfill-triggers.jsonl"
CONTEXT_ARMS = ("prev", "prev-own", "reply-own")
FIX_ARMS = ("fallback", "backfill", "backfill+fallback")
SWEEP_ARMS = ("floor-3", "floor-5", "line2", "line2+backfill", "line1+backfill")
TIER_ARMS = ("tiered", "tiered-full")
WARM_ARMS = ("warm", "warm-full")
# §4ad: the tier and warm arms stemmed, as §4ad built and measured them. Every other arm runs
# unstemmed, as it was measured and as the product ships (_stemming).
STEM_ARMS = ("tiered-stem", "tiered-stem-full", "warm-stem", "warm-stem-full")
ARMS = ("floor", "calibrated", *CONTEXT_ARMS, *FIX_ARMS, *SWEEP_ARMS, *TIER_ARMS, *WARM_ARMS, *STEM_ARMS)
# The index's tokenizer and the two lines, set together, at W 0 and W 8 of each receipt: stemmed
# (bench-20261029-sel-dense-embeddinggemma-int8-words-stem.txt), and unstemmed, as §4w and §4z set
# them and the product ships (bench-20261027-sel-dense-embeddinggemma-int8-words.txt).
STEMMED = ("porter unicode61", 3.0014486, 6.004063)
UNSTEMMED = ("unicode61", 2.0017173, 5.767926)
WARM_VECTORS = PRIVATE / "warm-vectors.json"


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
        with _stemming(False):   # the snapshot is read as it was written, its index not rebuilt
            self.full = Store(f"sqlite:///{SNAPSHOT}")
        self.nodes = self.full.all_nodes()
        self.recorded = sorted((n for n in self.nodes if not n.id.startswith("seed:")), key=lambda n: n.created_at)
        self.edges = self.full.edges(sorted(EDGE_RELS))
        self._cache: dict[tuple[int, bool, bool, bool], Store] = {}
        self._backfill: dict[str, str] | None = None

    def backfill(self) -> dict[str, str]:
        """The written triggers for recorded lessons that have none, by lesson id."""
        if self._backfill is None:
            by: dict[str, list[str]] = defaultdict(list)
            for r in _rows(BACKFILL.name):
                by[r["lesson"]].append(r["text"])
            self._backfill = {k: "\n".join(v) for k, v in by.items()}
        return self._backfill

    def warm_vectors(self) -> dict[str, tuple[str, str]]:
        """Every snapshot lesson's warm vectors with the written triggers in place, by id, as
        (phrasings hash, base64 rows): embedded once by the model in this process and kept in
        private/, re-embedded only where a lesson's phrasings changed."""
        # Keyed on the model and its revision too: new model files with unchanged phrasings would
        # otherwise reuse vectors the old model made (review on #300).
        identity = {"model": warm.MODEL_ID, "revision": warm.model_revision()}
        saved = json.loads(WARM_VECTORS.read_text()) if WARM_VECTORS.exists() else {}
        cached = saved.get("vectors", {}) if saved.get("identity") == identity else {}
        extra = self.backfill()
        out: dict[str, tuple[str, str]] = {}
        todo = []
        for n in self.nodes:
            m = dataclasses.replace(n, triggers=extra[n.id]) if n.id in extra else n
            if not warm.phrasings(m):
                continue
            h = warm.phrasings_hash(m)
            if cached.get(n.id, [None])[0] == h:
                out[n.id] = (h, cached[n.id][1])
            else:
                todo.append((n.id, h, warm.phrasings(m)))
        for node_id, h, texts in todo:
            out[node_id] = (h, base64.b64encode(warm._pack(warm.embed(texts, "doc"))).decode())
        if todo or saved.get("identity") != identity:
            WARM_VECTORS.write_text(json.dumps({"identity": identity, "vectors": {k: list(v) for k, v in out.items()}}))
        return out

    def as_of(self, ms: int, *, backfilled: bool = False, vectors: bool = False, stem: bool = False) -> Store:
        """The store a prompt at `ms` was checked against, built once per distinct moment; with
        `backfilled`, its recorded lessons carry the written triggers; with `vectors`, its
        lessons carry their warm vectors (REPORT §4z); with `stem`, its index stems (§4ad)."""
        k = sum(1 for n in self.recorded if n.created_at < ms)
        if (k, backfilled, vectors, stem) not in self._cache:
            keep = {n.id for n in self.nodes if n.id.startswith("seed:")} | {n.id for n in self.recorded[:k]}
            extra = self.backfill() if backfilled else {}
            with _stemming(stem):
                s = Store("sqlite:///:memory:")
            # Copied as stored: these nodes passed validation when they were written.
            for n in sorted((n for n in self.nodes if n.id in keep), key=lambda n: n.type != "Vocabulary"):
                s._impl.upsert_node(dataclasses.replace(n, triggers=extra[n.id]) if n.id in extra else n)
            for e in self.edges:
                if e.src in keep and e.dst in keep:
                    s._impl.upsert_edge(e)
            for node_id, (h, rows) in (self.warm_vectors().items() if vectors else ()):
                if node_id in keep:
                    s.put_embedding(node_id, warm.MODEL_ID, h, base64.b64decode(rows))
            self._cache[(k, backfilled, vectors, stem)] = s
        return self._cache[(k, backfilled, vectors, stem)]

    def for_arm(self, prompt: dict, arm: str) -> Store:
        """The store an arm checks a prompt against."""
        return self.as_of(millis(prompt["at"]),
                          backfilled="backfill" in arm or arm in (*TIER_ARMS, *WARM_ARMS, *STEM_ARMS),
                          vectors=arm.startswith("warm"), stem=arm in STEM_ARMS)


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


@contextmanager
def _fallback(on: bool) -> Iterator[None]:
    """Score a lesson without triggers on its body and fix as well as its about-text."""
    saved = decide.about_text

    def about_text(n: Node) -> str:
        return saved(n) if n.triggers else " ".join(x or "" for x in (saved(n), n.body, n.fix))

    if on:
        decide.about_text = about_text
    try:
        yield
    finally:
        decide.about_text = saved


@contextmanager
def _stemming(on: bool) -> Iterator[None]:
    """Run okl stemmed, as §4ad measured it, or unstemmed, as every other arm ran: the index's
    tokenizer and both lines change together."""
    saved = (okl_store.FTS_TOKENIZE, decide.CALIBRATED_LINE, warm.LINE)
    okl_store.FTS_TOKENIZE, decide.CALIBRATED_LINE, warm.LINE = STEMMED if on else UNSTEMMED
    try:
        yield
    finally:
        okl_store.FTS_TOKENIZE, decide.CALIBRATED_LINE, warm.LINE = saved


def brief(store: Store, prompt: dict, arm: str) -> list[str]:
    """The lesson ids an arm briefs for a prompt, checked against `store` (Stores.for_arm). A
    stem arm is its unstemmed namesake run stemmed."""
    with _stemming(arm in STEM_ARMS):
        return _brief(store, prompt, arm.replace("-stem", ""))


def _brief(store: Store, prompt: dict, arm: str) -> list[str]:
    repo = repo_of(prompt)
    if arm in (*TIER_ARMS, *WARM_ARMS):
        res = core.check(store, repo, prompt["text"], interests=None, decision="tiered", warm=arm in WARM_ARMS)
        if arm in WARM_ARMS and not res.get("warm") and core.briefing_terms(prompt["text"]):
            sys.exit(f"ABORT: the warm arm ran without its model: {res.get('warm_unavailable')}")
        named = [e["id"] for e in res["also_matched"]] if arm in ("tiered", "warm") else []
        return core.briefed_ids(res) + named
    if arm.startswith("floor-"):
        return core.briefed_ids(core.check(store, repo, prompt["text"], limit=int(arm.split("-")[1]), interests=None,
                                           decision="floor"))
    if arm.startswith("line"):
        saved = decide.CALIBRATED_LINE
        decide.CALIBRATED_LINE = float(arm[4])
        try:
            return core.briefed_ids(core.check(store, repo, prompt["text"], interests=None, decision="calibrated"))
        finally:
            decide.CALIBRATED_LINE = saved
    if arm in FIX_ARMS:
        with _fallback(arm.endswith("fallback")):
            return core.briefed_ids(core.check(store, repo, prompt["text"], interests=None, decision="calibrated"))
    if arm in ("floor", "calibrated"):
        return core.briefed_ids(core.check(store, repo, prompt["text"], interests=None, decision=arm))
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


def _write_batches(items: list[dict], stem: str) -> int:
    """Write judging items, PER_BATCH a file, without the lesson ids; return the file count."""
    for b in range(0, len(items), PER_BATCH):
        with (PRIVATE / f"{stem}{b // PER_BATCH}.jsonl").open("w") as f:
            for it in items[b:b + PER_BATCH]:
                f.write(json.dumps({k: v for k, v in it.items() if k != "_ids"}) + "\n")
    return -(-len(items) // PER_BATCH)


def _item(i: int, p: dict, lessons: list[str], nodes: dict[str, Node], first_n: int = 0) -> dict:
    """One judging item: a prompt with its context and the lessons to judge, numbered from first_n."""
    return {"item": i, "prompt": p["text"], "previous": p["previous"], "reply": p.get("reply", ""),
            "lessons": [{"n": first_n + j, "title": nodes[lid].title, "symptom": nodes[lid].symptom or "",
                         "fix": nodes[lid].fix or ""} for j, lid in enumerate(lessons)], "_ids": lessons}


def cmd_pool(args: argparse.Namespace) -> None:
    """Brief the sampled task and null prompts under the arms and write the blind judging batches;
    with --extend, add the arms a split's pool lacks and judge only the pairs it has not seen."""
    stores = Stores()
    nodes = {n.id: n for n in stores.nodes}
    arms = args.arms or list(ARMS)
    _model_for(arms)
    meta_path = PRIVATE / f"real-arms-{args.split}.json"
    if args.extend:
        meta = json.loads(meta_path.read_text())
        by_id = {p["id"]: p for label in ("task", "null") for p in prompts(label)}
        chosen = [(label, by_id[pid]) for label, pid in meta["chosen"]]
        # --rebrief briefs arms already pooled again, after a change to the code they run (the
        # tier arms after the review on #299); only pairs no arm had briefed are judged.
        new_arms = [a for a in arms if a not in meta["briefed"] or args.rebrief]
        for arm in new_arms:
            meta["briefed"][arm] = {p["id"]: brief(stores.for_arm(p, arm), p, arm) for _l, p in chosen}
        rng = random.Random(f"{meta['seed']}:{args.split}:extend")  # noqa: S311 - a reproducible shuffle
        items = []
        for i, (_label, p) in enumerate(chosen):
            seen = meta["pooled"].get(str(i), [])
            fresh = sorted({lid for arm in new_arms for lid in meta["briefed"][arm][p["id"]]} - set(seen))
            if not fresh:
                continue
            rng.shuffle(fresh)  # NOSONAR - the seeded order the judge reads, reproducible on purpose
            items.append(_item(i, p, fresh, nodes, first_n=len(seen)))
            meta["pooled"][str(i)] = seen + fresh
        rng.shuffle(items)  # NOSONAR - prompts in a seeded order, reproducible on purpose
        # Each extension writes its own family of files: the sweep's first run numbered from x0
        # again and overwrote the fix arms' inputs, whose labels were moved aside by hand.
        meta["extensions"] = meta.get("extensions", 0) + 1
        files = _write_batches(items, f"real-judge-{args.split}-e{meta['extensions']}-")
        meta_path.write_text(json.dumps(meta))
        print(f"extended with {', '.join(new_arms)} · {sum(len(it['_ids']) for it in items)} new pairs on "
              f"{len(items)} prompts · {files} batches", file=sys.stderr)
        return
    # A copy faithful to the snapshot briefs what the snapshot briefs; check before trusting it.
    full = stores.as_of(10**15)
    for p in sample("task", args.split, 20, args.seed):
        for arm in ("floor", "calibrated"):
            # Sets: a rebuilt full-text index may order exact ties differently.
            if set(brief(full, p, arm)) != set(brief(stores.full, p, arm)):
                sys.exit("ABORT: the rebuilt store briefs differently from the snapshot; fix Stores first")
    chosen = ([("task", p) for p in sample("task", args.split, args.sample, args.seed)]
              + [("null", p) for p in sample("null", args.split, args.nulls, args.seed)])
    briefed: dict[str, dict[str, list[str]]] = {arm: {} for arm in arms}
    before: dict[str, list[str]] = {}
    for _label, p in chosen:
        for arm in arms:
            briefed[arm][p["id"]] = brief(stores.for_arm(p, arm), p, arm)
        before[p["id"]] = previous_briefing(stores.as_of(millis(p["at"])), p)
    rng = random.Random(f"{args.seed}:{args.split}")  # noqa: S311 - a reproducible shuffle, not a secret
    items = []
    order = list(range(len(chosen)))
    rng.shuffle(order)  # NOSONAR - task and null prompts interleaved for the judge, reproducibly
    for i in order:
        _label, p = chosen[i]
        pooled = sorted({lid for arm in arms for lid in briefed[arm][p["id"]]})
        if not pooled:
            continue
        rng.shuffle(pooled)  # NOSONAR - the seeded order the judge reads, reproducible on purpose
        items.append(_item(i, p, pooled, nodes))
    files = _write_batches(items, f"real-judge-{args.split}-")
    meta = {"split": args.split, "seed": args.seed, "chosen": [[label, p["id"]] for label, p in chosen],
            "briefed": briefed, "before": before, "pooled": {str(it["item"]): it["_ids"] for it in items},
            "store": bench.digest([SNAPSHOT])}
    meta_path.write_text(json.dumps(meta))
    pairs = sum(len(it["_ids"]) for it in items)
    print(f"{sum(1 for x in chosen if x[0] == 'task')} task and {sum(1 for x in chosen if x[0] == 'null')} null "
          f"prompts · {pairs} (prompt, lesson) pairs on {len(items)} prompts · {files} batches", file=sys.stderr)


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


def _undecided(rule: str, arms: tuple[str, ...] | list[str], judged: set[str]) -> bool:
    """Say that `rule` is undecided while an arm it reads has a task pair no judge has seen, and
    return whether it is: a rule read from part of its arms' labels picks on partial data
    (review on #309)."""
    waiting = [a for a in arms if a not in judged]
    if waiting:
        print(f"\n{rule} rule: undecided until every task pair of {', '.join(waiting)} is judged")
    return bool(waiting)


def _warm_rule(meta: dict, verdict: dict[tuple[str, str], str | None], applies: dict[str, set[str]],
               stats: dict[str, tuple[float, int, float, int]], judged: set[str]) -> None:
    """§4z's rule, written before any warm arm's pair was judged: the warm arm ships on when it
    shows more applying lessons in full than tiered-full at a precision no lower than
    tiered-full's lower 95% bound, reaches at least as many as tiered, and shows a lesson in
    full on at most twice as many null prompts."""
    if not {"warm", "warm-full", "tiered", "tiered-full"} <= set(stats):   # the rule reads all four
        return
    if _undecided("warm", ("warm", "warm-full", "tiered", "tiered-full"), judged):
        return
    b = meta["briefed"]
    tasks = [pid for k, pid in meta["chosen"] if k == "task"]
    nulls = [pid for k, pid in meta["chosen"] if k == "null"]
    full = {a: _arm_row(tasks, b[a], meta["before"], verdict, applies) for a in ("tiered-full", "warm-full")}
    lo, _hi = bench.wilson(full["tiered-full"]["yes"], full["tiered-full"]["judged"])
    null_any = {a: sum(1 for pid in nulls if b[a][pid]) for a in ("tiered-full", "warm-full")}
    checks = {
        "more in full": full["warm-full"]["found"] > full["tiered-full"]["found"],
        f"in-full precision at least {lo:.1%}": stats["warm-full"][0] >= lo,
        "reach at least tiered's": stats["warm"][1] >= stats["tiered"][1],
        "null prompts at most twice tiered-full's": null_any["warm-full"] <= 2 * null_any["tiered-full"],
    }
    print(f"\nwarm rule: {'warm' if all(checks.values()) else 'not warm'} ("
          + "; ".join(f"{k}: {'yes' if v else 'NO'}" for k, v in checks.items())
          + f"; in full {full['warm-full']['found']} against {full['tiered-full']['found']}, "
          f"null prompts {null_any['warm-full']} against {null_any['tiered-full']})")


def _stem_rule(meta: dict, verdict: dict[tuple[str, str], str | None], applies: dict[str, set[str]],
               stats: dict[str, tuple[float, int, float, int]]) -> None:
    """§4ad's rule, written before any stem arm's pair was judged: stemming becomes the default
    when, for the tier arms and for the warm arms, the stemmed arm reaches at least as many
    applying lessons as its unstemmed namesake and shows at least 90% as many in full, at an
    in-full precision no lower than the namesake's lower 95% bound, on at most twice as many
    null prompts, naming at most 15% more lessons a task prompt. The decision reads the held-out
    half; the tuning half is reported beside it. While a stem arm's pairs are unjudged, only the
    two checks that need no label are read: the rule can fail then, never hold."""
    pairs = (("tiered", "tiered-stem"), ("warm", "warm-stem"))
    if not all({a, f"{a}-full", st, f"{st}-full"} <= set(stats) for a, st in pairs):   # reads all eight
        return
    b = meta["briefed"]
    tasks = [pid for k, pid in meta["chosen"] if k == "task"]
    nulls = [pid for k, pid in meta["chosen"] if k == "null"]
    held = []
    for base, stem in pairs:
        bf, sf = f"{base}-full", f"{stem}-full"
        full = {a: _arm_row(tasks, b[a], meta["before"], verdict, applies) for a in (bf, sf)}
        lo, _hi = bench.wilson(full[bf]["yes"], full[bf]["judged"])
        null_any = {a: sum(1 for pid in nulls if b[a][pid]) for a in (bf, sf)}
        # The label checks compare the stemmed arms with their baselines, so the baselines'
        # pairs must be judged too; they read task prompts only, so a null pair waits for
        # nothing (reviews on #309).
        unjudged = sum(1 for a in (base, bf, stem, sf) for pid in tasks for lid in b[a][pid]
                       if verdict.get((pid, lid)) is None)
        checks = {
            f"null prompts at most twice {bf}'s": null_any[sf] <= 2 * null_any[bf],
            "at most 15% more named a prompt": stats[stem][2] <= 1.15 * stats[base][2],
        }
        if not unjudged:
            checks = {
                f"reach at least {base}'s": stats[stem][1] >= stats[base][1],
                f"in full at least 90% of {bf}'s": full[sf]["found"] >= 0.9 * full[bf]["found"],
                f"in-full precision at least {lo:.1%}": stats[sf][0] >= lo,
                **checks,
            }
        held.append(all(checks.values()) if not unjudged or not all(checks.values()) else None)
        verdict_word = {True: "holds", False: "fails", None: "undecided"}[held[-1]]
        print(f"\nstem rule, {base}: {verdict_word} ("
              + (f"{unjudged} of its briefed pairs unjudged, so only the checks that need no label: "
                 if unjudged else "")
              + "; ".join(f"{k}: {'yes' if v else 'NO'}" for k, v in checks.items())
              + f"; null prompts {null_any[sf]} against {null_any[bf]}, named a prompt "
              f"{stats[stem][2]:.2f} against {stats[base][2]:.2f}"
              + ("" if unjudged else f", reach {stats[stem][1]} against {stats[base][1]}, "
                 f"in full {full[sf]['found']} against {full[bf]['found']}") + ")")
    overall = "not stemmed" if False in held else "stemmed" if all(held) else "undecided until judged"
    print(f"stem rule: {overall} (on this half)")


def pool_open(verdict: dict[tuple[str, str], str | None], ids: list[str]) -> bool:
    """Whether a pooled pair of `ids` has no judge's label yet. Such a pair may apply, so the
    pool's count of applying lessons, the recall denominator every arm shares, is a floor
    until every pair is judged, and recall and F1 over it would read high (review on #309)."""
    keep = set(ids)
    return any(v is None for (pid, _lid), v in verdict.items() if pid in keep)


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
    judged_task: set[str] = set()   # arms with every task pair judged: all a rule or F1 may read
    task_open = pool_open(verdict, [pid for k, pid in chosen if k == "task"])
    for kind in ("task", "null"):
        ids = [pid for k, pid in chosen if k == kind]
        total = sum(len(applies[pid]) for pid in ids)
        with_any = sum(1 for pid in ids if applies[pid])
        is_open = pool_open(verdict, ids)
        # Both denominators come from the pool's labels, so both are floors while it is open.
        shown, shown_any = ("-", "-") if is_open else (total, with_any)
        print(f"\n{kind} prompts: {len(ids)} person-typed · {with_any} with an applying lesson · "
              + (f"at least {total} applying lessons in the pool, some pairs unjudged" if is_open
                 else f"{total} applying lessons in the pool"))
        print(f"  {'arm':11} {'precision [95%]':>22} {'applying found':>15} {'prompts hit':>12} {'briefed any':>12} "
              f"{'lessons/prompt':>15} {'off-topic/prompt':>17} {'repeat':>7}")
        for arm in [a for a in ARMS if a in meta["briefed"]]:
            r = _arm_row(ids, meta["briefed"][arm], meta["before"], verdict, applies)
            lo, hi = bench.wilson(r["yes"], r["judged"]) if r["judged"] else (0.0, 0.0)
            prec = f"{r['yes'] / r['judged']:.1%} [{lo:.1%}, {hi:.1%}]" if r["judged"] else "n/a"
            # An arm with pairs no judge has seen has no precision or reach yet: a figure over
            # the judged part alone would read as the arm's (§4ad stopped before judging).
            unjudged = sum(1 for pid in ids for lid in meta["briefed"][arm][pid] if verdict.get((pid, lid)) is None)
            if kind == "task" and not unjudged:
                judged_task.add(arm)
            if unjudged:
                print(f"  {arm:11} {f'{unjudged} unjudged':>22} {'-':>15} {'-':>12} "
                      f"{r['any']:>5} of {len(ids):<4} {r['per']:>15.2f} {'-':>17} {r['repeat']:>7.0%}")
            else:
                print(f"  {arm:11} {prec:>22} {r['found']:>7} of {shown!s:<5} {r['hit']:>5} of {shown_any!s:<4} "
                      f"{r['any']:>5} of {len(ids):<4} {r['per']:>15.2f} {r['off']:>17.2f} {r['repeat']:>7.0%}")
            if kind == "task":
                stats[arm] = (r["yes"] / r["judged"] if r["judged"] else 0.0, r["found"], r["per"], total)
    # F1 of judged precision and pooled recall, the sweep rule's measure.
    f1 = {a: (2 * p * (f / t) / (p + f / t) if p and t and f else 0.0) for a, (p, f, _per, t) in stats.items()
          if a in judged_task}
    print("\nF1 on task prompts (judged precision, pooled recall): "
          + ("n/a until every task pair is judged" if task_open
             else " · ".join(f"{a} {v:.3f}" for a, v in f1.items())))
    # The selection rules, each fixed before its arms' pairs were judged (module docstring).
    for name, family in (("context", CONTEXT_ARMS), ("fix", FIX_ARMS)):
        present = [a for a in family if a in stats]
        if not present or "calibrated" not in stats:
            continue
        if _undecided(name, ["calibrated", *present], judged_task):
            continue
        eligible = [a for a in present if stats[a][0] >= stats["calibrated"][0]]
        pick = min(eligible, key=lambda a: (-stats[a][1], stats[a][2])) if eligible else None
        print(f"\n{name} rule: {pick or f'no {name} arm'} "
              + (f"(most applying lessons found on task prompts among the {name} arms at least as precise as "
                 "calibrated)" if pick else "(none is at least as precise as calibrated on task prompts)"))
    if "tiered" in stats and "floor" in stats and not _undecided("tier", ("tiered", "floor"), judged_task):
        holds = stats["tiered"][1] >= stats["floor"][1]
        print(f"\ntier rule: {'tiered' if holds else 'not tiered'} (it reaches {stats['tiered'][1]} applying lessons "
              f"on task prompts, the floor {stats['floor'][1]}; the rule asks at least as many)")
    _warm_rule(meta, verdict, applies, stats, judged_task)
    _stem_rule(meta, verdict, applies, stats)
    if any(a in stats for a in SWEEP_ARMS):
        eligible = [a for a in f1 if stats[a][2] <= 5] if not task_open else []
        if eligible:
            pick = min(eligible, key=lambda a: (-f1[a], stats[a][2]))
            print(f"\nsweep rule: {pick} (highest F1 on task prompts among arms briefing at most five lessons "
                  "a prompt)")
        else:
            print("\nsweep rule: undecided (no arm with every task pair judged briefs at most five lessons a "
                  "prompt, or a task pair is unjudged)")


def cmd_misses(args: argparse.Namespace) -> None:
    """Where each applying lesson an arm missed on task prompts stopped inside core.check: not
    among the candidates, below the line by how many about-words it shares, or cut by the cap
    (REPORT §4y). Labels as the pool stood before the extension families named by --before.
    Counts only: no prompt, no lesson."""
    meta = json.loads((PRIVATE / f"real-arms-{args.split}.json").read_text())
    label: dict[tuple[int, int], str] = {}
    for f in sorted(PRIVATE.glob(f"real-judge-{args.split}-*-out.jsonl")):
        if not any(f"-{family}-" in f.name for family in args.before):
            for o in _rows(f.name):
                label[(int(o["item"]), int(o["n"]))] = o["label"]
    chosen = meta["chosen"]
    applies: dict[str, set[str]] = defaultdict(set)
    for item, ids in meta["pooled"].items():
        for n, lid in enumerate(ids):
            if label.get((int(item), n)) == "APPLIES":
                applies[chosen[int(item)][1]].add(lid)
    by_id = {p["id"]: p for p in prompts("task")}
    stores = Stores()
    stopped: dict[str, int] = defaultdict(int)
    total = 0
    for kind, pid in chosen:
        if kind != "task":
            continue
        total += len(applies[pid])
        missed = applies[pid] - set(meta["briefed"][args.arm][pid])
        if not missed:
            continue
        p = by_id[pid]
        store = stores.for_arm(p, args.arm)
        hits, *_ = core._live_hits(store, p["text"], 12, f"repo:{repo_of(p)}", None)
        live = [n for n in store.all_nodes() if n.status not in core.RETIRED_STATUSES]
        terms = [w.lower() for w in core.briefing_terms(p["text"])]
        kept, matched, _weak = decide.select(hits, terms, decide.Rarity(live))
        kept_ids, hit_ids = {n.id for n in kept}, {n.id for n in hits}
        for lid in missed:
            if lid not in hit_ids:
                stopped["not among the candidates"] += 1
            elif lid in kept_ids:
                stopped["cleared the line, cut by the cap"] += 1
            else:
                shared = len(matched.get(lid, []))
                stopped[f"among the candidates, below the line: {min(shared, 2)}{'+' if shared >= 2 else ''} "
                        "shared about-word(s)"] += 1
    found = total - sum(stopped.values())
    print(f"real prompts · split {args.split} · arm {args.arm} · labels before {', '.join(args.before) or 'none'} · "
          f"store {meta['store']}")
    print(f"task prompts: {total} applying lessons in the pool; {args.arm} found {found}, missed {total - found}")
    for k, v in sorted(stopped.items(), key=lambda kv: -kv[1]):
        print(f"  {v:4}  {k}")


SIZE_ARMS = ("floor", "backfill", "tiered", "warm", "tiered-stem", "warm-stem")


def _model_for(arms: list[str] | tuple[str, ...]) -> None:
    """Load the warm model into this process once when an arm needs it (REPORT §4z): the arms
    run core.check's own warm path, with the encoder here instead of the server."""
    if any(a.startswith("warm") for a in arms):
        warm.set_encoder(warm.load_model())


def cmd_size(args: argparse.Namespace) -> None:
    """The briefing each arm hands the agent (the hook's additionalContext) for every sampled
    prompt of a split, in characters and in tokens at four characters each (REPORT §4y)."""
    meta = json.loads((PRIVATE / f"real-arms-{args.split}.json").read_text())
    by_id = {p["id"]: p for label in ("task", "null") for p in prompts(label)}
    stores = Stores()
    _model_for(SIZE_ARMS)
    decision = {"floor": "floor", "backfill": "calibrated", "tiered": "tiered", "warm": "tiered",
                "tiered-stem": "tiered", "warm-stem": "tiered"}
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=bench.ROOT, check=False).stdout.strip()
    print(f"briefing size · split {args.split} · store {meta['store']} · code {commit} · "
          "characters / 4 = tokens, a rough rule")
    for kind in ("task", "null"):
        ids = [pid for k, pid in meta["chosen"] if k == kind]
        print(f"\n{kind} prompts: {len(ids)}")
        print(f"  {'arm':9} {'median':>8} {'mean':>8} {'p90':>8} {'max':>8}   (tokens)")
        for arm in SIZE_ARMS:
            with _stemming(arm in STEM_ARMS):
                sizes = sorted(len(core.render_check_for_agent(core.check(
                    stores.for_arm(by_id[pid], arm), repo_of(by_id[pid]), by_id[pid]["text"], interests=None,
                    decision=decision[arm], warm=arm.startswith("warm")))) // 4 for pid in ids)
            print(f"  {arm:9} {statistics.median(sizes):>8.0f} {statistics.mean(sizes):>8.0f} "
                  f"{sizes[9 * len(sizes) // 10]:>8} {sizes[-1]:>8}")


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
    pp.add_argument("--arms", nargs="+", choices=ARMS, help="the arms to brief (default: every arm)")
    pp.add_argument("--extend", action="store_true",
                    help="add the given arms to the split's existing pool and judge only their new pairs")
    pp.add_argument("--rebrief", action="store_true",
                    help="with --extend: brief the given arms again even if pooled, after a code change")
    pt = sub.add_parser("tally")
    pt.add_argument("--split", choices=["tuning", "heldout"], required=True)
    ps = sub.add_parser("size")
    ps.add_argument("--split", choices=["tuning", "heldout"], required=True)
    pm = sub.add_parser("misses")
    pm.add_argument("--split", choices=["tuning", "heldout"], required=True)
    # Only the arms that run the calibrated line as it is: the classifier rebuilds that decision,
    # so for any other arm it would name the wrong cause (review on #299).
    pm.add_argument("--arm", choices=["calibrated", "backfill"], default="backfill")
    pm.add_argument("--before", nargs="*", default=[], help="label families to leave out, such as e1")
    args = ap.parse_args()
    {"snapshot": cmd_snapshot, "pool": cmd_pool, "tally": cmd_tally, "size": cmd_size,
     "misses": cmd_misses}[args.cmd](args)


if __name__ == "__main__":
    main()
