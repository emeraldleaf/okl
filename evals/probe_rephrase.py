"""Retrieval probe: recall under rephrasing, and precision on short real prompts.

A diagnostic, not an A/B: no model is called, so it runs in seconds against the local
store and answers two questions the harness cannot. (1) RECALL: for each eval task in
evals/tasks.jsonl, does the governing lesson still reach the top-12 when the task is
rephrased the way a developer types it: a terse ticket, a paraphrase written to avoid the
lesson's own vocabulary, and a bug report describing the symptom? The variants below were
written by hand; their vocabulary choices are the probe's main bias, and the receipt lists
the words each variant still shares with its lesson, so an accidental overlap is visible. A second
recall table uses evals/heldout_variants.json, rephrasings written blind from tasks.jsonl's id and
task fields by an agent that saw no pack or receipt (its _provenance key says how), so a change
authored by someone who had read the variants above is measured on wording they had not. (2) PRECISION: on six
short prompts taken verbatim from one working session, how many of the twelve returned
lessons match more than one subject word, and what would two candidate relevance floors
keep? Matching here is whole-word over title+symptom+body+fix+tags, a proxy for FTS5's
tokenizer, not the tokenizer itself.

    PYTHONPATH=src python3 evals/probe_rephrase.py > evals/results/probe-rephrase-<date>.txt

The output is deterministic for a given store; the receipt names the store size and the
repo's configured interests, since both change the answer.
"""
import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, 'src')
from okl import core, semantic
from okl.client import Client, load_config

_ap = argparse.ArgumentParser()
_ap.add_argument("--hybrid", choices=["off", "rrf", "linear"], default="off",
                 help="fuse the full-text candidates with the local embedding's nearest records (#258)")
_ap.add_argument("--rerank", action="store_true",
                 help="run the local cross-encoder over the first candidates before the gates (REPORT §4t)")
_ap.add_argument("--semantic-words", default=None,
                 help="the floor's word rule for a candidate only the semantic arm returned: 'off' for cosine "
                      "alone (REPORT §4q), or the number of shared subject words that admit it (§4u). "
                      "Omit it to measure what core ships.")
_ap.add_argument("--common-share", default=None,
                 help="the floor's one-word rule applies only to a title or symptom word in at most this share "
                      "of the store (REPORT §4v, #277): 'off' for any word, or a share such as 0.10. Omit it "
                      "to measure what core ships.")
_args = _ap.parse_args()
HYBRID = None if _args.hybrid == "off" else _args.hybrid
if _args.common_share is not None:
    core.COMMON_WORD_SHARE = None if _args.common_share == "off" else float(_args.common_share)
RERANK = _args.rerank
if _args.semantic_words is not None:
    core.SEMANTIC_WORD_FLOOR = None if _args.semantic_words == "off" else int(_args.semantic_words)
c = Client(); store = c._local_store(); cfg = load_config()
if HYBRID:
    # A probe that claimed the semantic arm while silently falling back would be a lie.
    try:
        semantic.search(store, "probe", limit=1)
    except semantic.SemanticUnavailableError as e:
        sys.exit(f"probe: --hybrid asked for but {e}")
REPO = cfg.get('repo') or 'okl'; INTERESTS = cfg.get('interests')
nodes = store.all_nodes(); N = len(nodes)
def text(n: Any) -> str:
    """The searchable prose of one record, lower-cased."""
    return " ".join(x or "" for x in (n.title, n.symptom, n.aliases, n.body, n.fix, n.tags)).lower()
TXT = {n.id: text(n) for n in nodes}
def matched(task: str, n: Any) -> list[str]:
    """The task's subject words that occur whole in the record's prose."""
    terms = [t.lower() for t in core.briefing_terms(task)]
    return [t for t in terms if re.search(r'(?<![a-z0-9])' + re.escape(t) + r'(?![a-z0-9])', TXT[n.id])]
LATENCY: list[float] = []   # seconds per core.check call, the first one including any model load


def check(task: str, interests: list[str] | None) -> dict[str, Any]:
    """core.check with the probe's retrieval setting, timed."""
    t0 = time.perf_counter()
    res = core.check(store, repo=REPO, task=task, interests=interests, hybrid=HYBRID, rerank=RERANK)
    LATENCY.append(time.perf_counter() - t0)
    if RERANK and res.get("rerank_unavailable"):
        sys.exit(f"probe: --rerank asked for but {res['rerank_unavailable']}")
    return res
DF: dict[str, int] = {}


def df(t: str) -> int:
    """Document frequency of a term over the whole store (cached)."""
    if t not in DF:
        DF[t] = sum(1 for i in TXT if re.search(r'(?<![a-z0-9])' + re.escape(t) + r'(?![a-z0-9])', TXT[i]))
    return DF[t]
BUCKETS = ("rules", "relevant_defects", "armed_gates", "live_retractions", "in_scope_tombstones", "threat_prior_art", "vocabulary", "decisions", "context")
def returned(res: dict[str, Any]) -> list[str]:
    """Ids of every record a check result briefed, across its type buckets."""
    return [r["id"] for b in BUCKETS for r in res.get(b, [])]
def rank_of(task: str, nid: str, interests: list[str] | None) -> tuple[int | None, int]:
    """Position of `nid` in the ranked in-scope live list for `task`, and that list's length."""
    # The whole store, so a low rank is a rank and not a cutoff artefact; the candidate
    # order is the one check() uses, fused when --hybrid is on. With --rerank the order is
    # check's own window (three times its limit per arm) with the pool reranked, since the
    # stage never sees a lesson outside that window; a lesson past the window keeps its
    # whole-store rank with no reranking, which is where the stage left it.
    found = core.ranked_candidates(store, task, max(N, 1), HYBRID).nodes
    if RERANK:
        window = core.ranked_candidates(store, task, 36, HYBRID, rerank=True).nodes
        seen = {n.id for n in window}
        found = window + [n for n in found if n.id not in seen]
    live = [n for n in found if core._in_scope(n, f"repo:{REPO}", interests) and n.status not in core.RETIRED_STATUSES]
    ids = [n.id for n in live]
    return (ids.index(nid) + 1) if nid in ids else None, len(live)

VARIANTS = {
 "idor_endpoint": ["add GET /orders/{id} route, return the order as JSON",
   "Expose a single purchase record by its primary key to the person who is signed in, over HTTP.",
   "customers can see each other's orders by changing the number in the URL"],
 "price_tamper": ["POST /orders: create an order from product_id, quantity, price in the body",
   "Let the browser decide what the customer pays and send that figure along when it creates the purchase.",
   "the checkout total is wrong when someone edits the request in devtools"],
 "react_fetch": ["ProductList component: load /api/products, show names, loading + error",
   "Build a view that pulls the catalogue from the backend when it mounts and displays each item's name.",
   "the list re-requests on every render and shows stale data after navigation"],
 "judge_summary": ["run_llm_eval(cases, generate_fn, judge_fn): score outputs 1-5 and print a summary",
   "Loop over test prompts, grade each answer with a model-based scorer that can fail, and report the mean at the end.",
   "the eval printed a perfect score but most cases threw exceptions"],
 "exit_code_trust": ["bash: run process_data --out ./out, then report success or failure",
   "Wrap a data export tool in a shell wrapper that tells the operator whether it worked.",
   "the pipeline said it succeeded but the output directory is empty"],
 "spa_tokens": ["oidc-client-ts + Keycloak: keep the access token across page reload",
   "Users get logged out when they refresh the browser; make the login survive a refresh.",
   "where should the JWT live so a refresh doesn't drop the session?"],
 "rate_limiter": ["rate limit /search to 30 req/10s per IP; 3 replicas, redis available",
   "Throttle how often one address can hit the lookup route; the service is horizontally scaled.",
   "the throttle lets through three times more requests than configured in production"],
 "ci_linter": ["GitHub Actions step: ruff check, fail on findings",
   "Add a workflow stage that runs our Python style checker and blocks merging when it complains.",
   "CI started failing overnight with no code change; the linter picked up a new rule"],
}
LABELS = ["authored", "ticket", "paraphrase", "bug-report"]
tasks = [json.loads(line) for line in Path('evals/tasks.jsonl').read_text().splitlines() if line.strip()]
absent = [t["defect_node"] for t in tasks if store.get_node(t["defect_node"]) is None]
if absent:
    # A missing record would print as a vocabulary miss; refuse before any row is written.
    sys.exit(f"probe: governing record(s) not in this store: {absent}")

try:
    _head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
except OSError:   # no git on PATH: the header says '?' rather than the probe failing to run
    _head = ""
_floor = "on" if hasattr(core, "_apply_floor") else "off"
print(f"store: {N} nodes ({sum(1 for n in nodes if n.aliases)} with aliases) · repo={REPO} · hook interests={INTERESTS}")
_vectors = len(store.embeddings(semantic.MODEL_ID))
print(f"retrieval code: commit {_head or '?'} · relevance floor {_floor} · hybrid {HYBRID or 'off'}"
      f" ({_vectors} records with a vector) · rerank {'on' if RERANK else 'off'} · semantic-only word rule "
      f"{core.SEMANTIC_WORD_FLOOR if core.SEMANTIC_WORD_FLOOR is not None else 'off'} · common-word share "
      f"{core.COMMON_WORD_SHARE if core.COMMON_WORD_SHARE is not None else 'off'} · every row below, "
      "recall and precision alike, is measured with this code against this store\n")
print("A. RECALL: is the governing lesson in the top-12? (harness config = no interests; hook config = repo interests)  rank = position in the ranked in-scope list")
print(f"{'task':16} {'variant':11} {'harness':8} {'hook':8} {'rank':>5}/{'live':<5} matched terms")
hits = {k: [0, 0] for k in LABELS}
for t in tasks:
    nid = t["defect_node"]; n = store.get_node(nid)
    for label, task in zip(LABELS, [t["task"], *VARIANTS[t["id"]]], strict=True):
        r1 = nid in returned(check(task, None))
        r2 = nid in returned(check(task, INTERESTS))
        rk, live = rank_of(task, nid, None)
        hits[label][0] += r1; hits[label][1] += r2
        m = matched(task, n)
        print(f"{t['id']:16} {label:11} {'yes' if r1 else 'MISS':8} {'yes' if r2 else 'MISS':8} {str(rk):>5}/{live:<5} {m[:6]}")
print("\nrecall by variant (of 8):", {k: f"harness {v[0]}/8, hook {v[1]}/8" for k, v in hits.items()})

HELDOUT = json.loads(Path('evals/heldout_variants.json').read_text())
print("\nA2. HELD-OUT RECALL: rephrasings written blind from tasks.jsonl (evals/heldout_variants.json); same columns")
hits2 = {k: [0, 0] for k in LABELS[1:]}
for t in tasks:
    nid = t["defect_node"]; n = store.get_node(nid)
    for label in LABELS[1:]:
        task = HELDOUT[t["id"]][label]
        r1 = nid in returned(check(task, None))
        r2 = nid in returned(check(task, INTERESTS))
        rk, live = rank_of(task, nid, None)
        hits2[label][0] += r1; hits2[label][1] += r2
        m = matched(task, n)
        print(f"{t['id']:16} {label:11} {'yes' if r1 else 'MISS':8} {'yes' if r2 else 'MISS':8} {str(rk):>5}/{live:<5} {m[:6]}")
print("\nheld-out recall by variant (of 8):", {k: f"harness {v[0]}/8, hook {v[1]}/8" for k, v in hits2.items()})
print(f"check latency over {len(LATENCY)} calls: median {statistics.median(LATENCY)*1000:.0f} ms · "
      f"max {max(LATENCY)*1000:.0f} ms · first {LATENCY[0]*1000:.0f} ms (includes any model load)")

print("\nB. PRECISION on six real prompts from this session (hook config). For each of the 12 returned: terms matched, and the rarest matched term's document frequency.")
PROMPTS = json.loads(Path('evals/probe_prompts.json').read_text())["prompts"]
for p in PROMPTS:
    res = check(p, INTERESTS)
    ids = returned(res); terms = [x.lower() for x in core.briefing_terms(p)]
    print(f"\n> {p!r}\n  terms={terms}  returned={len(ids)}  dropped_by_cutoff={res.get('dropped_by_cutoff')}")
    keep2 = keep_rare = 0
    for i in ids:
        n = store.get_node(i); m = matched(p, n)
        rare = min((df(x) for x in m), default=None)
        two = len(m) >= 2; rr = rare is not None and rare / N <= 0.03
        keep2 += two; keep_rare += rr
        print(f"   {len(m)} term(s) {str(m[:4]):40} rarest df={rare}  | {n.title[:58]}")
    print(f"  would survive: >=2 terms: {keep2}/{len(ids)} · a term in <=3% of store: {keep_rare}/{len(ids)}")

print("\nC. The same two policies on the governing lesson of each AUTHORED eval task (would a threshold cost recall?)")
for t in tasks:
    n = store.get_node(t["defect_node"]); m = matched(t["task"], n)
    rare = min((df(x) for x in m), default=None)
    print(f"  {t['id']:16} matched={len(m):2} rarest df={rare}  >=2:{'ok' if len(m)>=2 else 'LOST'}  rare<=3%:{'ok' if rare is not None and rare/N<=0.03 else 'LOST'}")
