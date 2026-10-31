"""evals/bench/run.py: the retrieval bench builds its corpus in a throwaway store of its own."""
import argparse
import contextlib
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

from okl import store
from okl.store import Store

ROOT = Path(__file__).resolve().parents[1]


def test_the_corpus_ignores_the_store_and_service_the_environment_names(tmp_path, monkeypatch):
    """With OKL_DATABASE_URL set, the bench seeded that store and stripped its triggers, and a
    stemmed arm, which switches the tokenizer before the corpus is built, would have rebuilt its
    index on open; with OKL_SERVICE_URL set, it would have sent the seeds to the service (review
    on #308)."""
    real = tmp_path / "real.db"
    Store(f"sqlite:///{real}").close()
    before = real.read_bytes()
    monkeypatch.setenv("OKL_DATABASE_URL", f"sqlite:///{real}")
    monkeypatch.setenv("OKL_SERVICE_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(store, "FTS_TOKENIZE", "porter unicode61")   # as v2.set_stem(True) does
    spec = importlib.util.spec_from_file_location("bench_run", ROOT / "evals" / "bench" / "run.py")
    bench = importlib.util.module_from_spec(spec); spec.loader.exec_module(bench)
    corpus = bench.build_corpus(tmp_path / "corpus")
    try:
        assert len(corpus.all_nodes()) > 100
        fts = corpus._impl.conn.execute("SELECT sql FROM sqlite_master WHERE name = 'node_fts'").fetchone()[0]
        assert "porter" in fts
    finally:
        corpus.close()
    assert real.read_bytes() == before
    with contextlib.closing(sqlite3.connect(real)) as c:
        assert c.execute("SELECT count(*) FROM node").fetchone() == (0,)


def _real_prompts(monkeypatch):
    """evals/bench/real_prompts.py as a module; it puts evals/bench on the path, undone after."""
    monkeypatch.setattr(sys, "path", list(sys.path))
    spec = importlib.util.spec_from_file_location("real_prompts", ROOT / "evals" / "bench" / "real_prompts.py")
    rp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rp)
    return rp


def test_pooled_recall_waits_until_every_pair_is_judged(monkeypatch):
    """real_prompts.tally: a pair no judge has seen may apply, so while one is open the pool's
    count of applying lessons is a floor, and recall and F1 over it would read high (review on
    #309). Only the prompts asked about count."""
    rp = _real_prompts(monkeypatch)
    verdict = {("t1", "a"): "APPLIES", ("t1", "b"): None, ("n1", "a"): "DOES_NOT_APPLY"}
    assert rp.pool_open(verdict, ["t1"])
    assert not rp.pool_open(verdict, ["n1"])
    assert not rp.pool_open({("t1", "a"): "APPLIES"}, ["t1"])



def test_the_tally_decides_nothing_from_part_of_an_arms_labels(tmp_path, monkeypatch, capsys):
    """While a task pair is unjudged, the pool's denominators print as '-', F1 and the sweep wait,
    and a rule waits for every arm it reads; a rule whose arms are all judged still decides
    (reviews on #309)."""
    rp = _real_prompts(monkeypatch)
    monkeypatch.setattr(rp, "PRIVATE", tmp_path)
    nothing = {"t1": [], "t2": [], "n1": []}
    briefed = {"floor": {**nothing, "t1": ["a"], "t2": ["b"]},
               "calibrated": {**nothing, "t1": ["a"]},
               "prev": {**nothing, "t1": ["a"], "t2": ["c"]},     # c on t2: no judge has seen it
               "tiered": {**nothing, "t1": ["a"], "t2": ["b"]},
               "floor-3": {**nothing, "t1": ["a"]}}
    meta = {"seed": 1, "store": "s", "chosen": [["task", "t1"], ["task", "t2"], ["null", "n1"]],
            "pooled": {"0": ["a"], "1": ["b", "c"], "2": []}, "briefed": briefed, "before": nothing}
    (tmp_path / "real-arms-x.json").write_text(json.dumps(meta))
    (tmp_path / "real-judge-x-a-out.jsonl").write_text(
        json.dumps({"item": 0, "n": 0, "label": "APPLIES"}) + "\n"
        + json.dumps({"item": 1, "n": 0, "label": "APPLIES"}) + "\n")
    rp.cmd_tally(argparse.Namespace(split="x"))
    out = capsys.readouterr().out
    assert "context rule: undecided until every task pair of prev is judged" in out, out
    assert "pooled recall): n/a until every task pair is judged" in out, out
    assert "sweep rule: undecided" in out, out
    assert "tier rule: tiered" in out, out                        # tiered and floor are fully judged
    floor_row = next(line for line in out.splitlines() if line.startswith("  floor "))
    # Applying lessons found, and prompts hit: both counted against the open pool.
    assert floor_row.count(" of - ") == 2, floor_row


def test_the_stem_rule_waits_for_its_baselines_labels_too(monkeypatch, capsys):
    """Its label checks compare each stemmed arm with its baseline, so a baseline pair no judge
    has seen leaves the rule undecided rather than stemmed (review on #309)."""
    from collections import defaultdict
    rp = _real_prompts(monkeypatch)
    arms = ("tiered", "tiered-full", "tiered-stem", "tiered-stem-full",
            "warm", "warm-full", "warm-stem", "warm-stem-full")
    briefed = {a: {"t1": ["a"], "n1": []} for a in arms}
    briefed["tiered"]["t1"] = ["a", "z"]                         # z: the baseline's unjudged pair
    meta = {"chosen": [["task", "t1"], ["null", "n1"]], "briefed": briefed, "before": {"t1": [], "n1": []}}
    applies = defaultdict(set, {"t1": {"a"}})
    rp._stem_rule(meta, {("t1", "a"): "APPLIES", ("t1", "z"): None}, applies, {a: (1.0, 1, 1.0, 1) for a in arms})
    out = capsys.readouterr().out
    assert "stem rule, tiered: undecided" in out and "stem rule: undecided until judged" in out, out


def test_the_stem_rule_does_not_wait_for_null_pairs(monkeypatch, capsys):
    """Its label checks read task prompts only, and its null check counts briefings, so a null
    pair no judge has seen leaves the rule free to decide (review on #309)."""
    from collections import defaultdict
    rp = _real_prompts(monkeypatch)
    arms = ("tiered", "tiered-full", "tiered-stem", "tiered-stem-full",
            "warm", "warm-full", "warm-stem", "warm-stem-full")
    briefed = {a: {"t1": ["a"], "n1": ["q"]} for a in arms}       # q on n1: no judge has seen it
    meta = {"chosen": [["task", "t1"], ["null", "n1"]], "briefed": briefed, "before": {"t1": [], "n1": []}}
    applies = defaultdict(set, {"t1": {"a"}})
    rp._stem_rule(meta, {("t1", "a"): "APPLIES", ("n1", "q"): None}, applies, {a: (1.0, 1, 1.0, 1) for a in arms})
    out = capsys.readouterr().out
    assert "stem rule, tiered: holds" in out and "stem rule: stemmed" in out, out
