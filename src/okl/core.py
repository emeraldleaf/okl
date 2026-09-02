"""The three operations, independent of transport (CLI / HTTP / MCP all call these).

check(repo, task)   -> the pre-task neighborhood: armed gates, live retractions,
                       in-scope tombstones, THREAT prior-art, vocabulary, stale warnings.
                       This is the load-bearing read (design doc §3.4). Fails CLOSED
                       at the transport layer, never here.
record(node, scope) -> the org-scope arm of the encoding response (§3.3).
search(query, ...)  -> targeted retrieval (progressive disclosure).
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from .store import Edge, Node, Store, _now_ms, split_tags


def _node_public(n: Node) -> dict[str, Any]:
    """A record as the API exposes it: every field, plus computed staleness.

    Staleness is derived rather than stored so it cannot go out of date on disk.
    """
    d = asdict(n)
    d["stale"] = n.is_stale()
    return d


def _in_scope(n: Node, repo_scope: str, interests: list[str] | None) -> bool:
    """Decide whether one record may appear in this repo's briefing.

    Two independent axes, and it helps to keep them straight:
      - SCOPE is permission. "org" means every repo; "repo:<name>" means exactly one.
      - TAGS are subject. They narrow an org record to repos that care about the topic.

    The order below matters. A repo's own records pass first and unconditionally, so a
    repo can never be filtered away from its own knowledge by its own settings.

    ANY-MATCH, DELIBERATELY. Exclusive stack filtering was tried and REVERTED after the
    A/B measured it: a record naming a stack the repo had not declared was dropped even
    when it shared a subject the repo wanted. It hid 35 of 172 org records here, and the
    briefed arm then reproduced the rate-limiter defect that the dropped rule described
    (ab-20260902-0538, REPORT.md §4d).

    The root cause is what a stack tag MEANS. It records where a lesson was FOUND, not
    where it APPLIES: "in-memory rate limiters weaken to N× at N instances" carries
    `dotnet` because it came from a .NET codebase, and is true of every runtime. So is the
    IDOR rule, and "exit 0 having written zero files". Filtering on provenance as though
    it were applicability throws away most of what a shared store is for.

    The problem that motivated the change is still real — genuinely .NET-only rules do
    reach a Python repo. Fixing it needs applicability recorded separately from
    provenance, not a stricter reading of a tag that never meant that.
    """
    if n.scope == repo_scope:
        return True
    if n.scope != "org":
        return False
    if not interests:
        return True
    tags = split_tags(n.tags)
    return not tags or bool(tags & {t.strip().lower() for t in interests if t.strip()})


def check(store: Store, repo: str, task: str, limit: int = 12,
          interests: list[str] | None = None) -> dict[str, Any]:
    """Return the slice of the encoded body relevant to starting `task` in `repo`.

    Matches on the task text across all node types, then buckets by type so the
    agent gets an actionable briefing rather than a flat list. Org-scope nodes
    and this repo's own nodes are both in scope; other repos' repo-scope nodes
    are not (that is the curation boundary, §"repo vs org scope").

    `interests` is the repo's declared subject-tag list (.okl/config.json). When
    set, org-scope nodes tagged entirely OUTSIDE it are dropped: scope answers
    "who may see this", tags answer "what is this about". Untagged nodes and the
    repo's own nodes always pass — declaring interests must never hide them.
    """
    # THE PIPELINE, in four steps. Each one narrows what reaches the agent:
    #
    #   1. SEARCH   — full-text match the task description against every record's title
    #                 and body. We ask for 3x `limit` because the next two steps throw
    #                 records away, and we would rather over-fetch cheaply than come up
    #                 short after filtering.
    #   2. FILTER   — drop anything this repo may not see (scope) or does not care about
    #                 (interests). See _in_scope below.
    #   3. BUCKET   — sort survivors by type, so the briefing can lead with gates and
    #                 defects rather than emitting one undifferentiated list.
    #   4. ROUTE    — turn the buckets into an ordered list of imperatives.
    repo_scope = f"repo:{repo}"
    hits = [n for n in store.search(task, limit=limit * 3)
            if _in_scope(n, repo_scope, interests)]
    # THE CUTOFF. store.search returns BM25-ranked results, but full-text matching is
    # permissive: on a mature store a plausible task matches most of it, so without a
    # cap the "briefing" becomes the library. Ranking already put the best first, so
    # taking the top `limit` keeps what matters and drops the tail. This is the fix for
    # the recorded defect "ranking works, filtering doesn't" — raise `limit` when a task
    # genuinely needs more, rather than removing the cap.
    dropped = max(0, len(hits) - limit)
    hits = hits[:limit]

    buckets = _bucket_by_type(hits)
    _attach_catches(store, buckets["armed_gates"])
    actions = _route_actions(buckets)

    # stale_warnings is excluded from the count because those records are already
    # counted inside their own type bucket; including them would double-count.
    total = sum(len(v) for k, v in buckets.items() if k != "stale_warnings")
    out = {"repo": repo, "task": task, "match_count": total,
           "next_actions": actions, "dropped_by_cutoff": dropped, **buckets}
    # Zero matches has two very different causes: the store holds rules and none apply
    # here, or the store holds nothing at all. Reporting both as "proceed" is the
    # silence-as-safety failure this project exists to prevent, so the count travels
    # with the result. Only computed on the (rare) empty-result path.
    if total == 0:
        out["store_records"] = len(store.all_nodes())
    return out


def _bucket_by_type(hits: list[Node]) -> dict[str, list[dict]]:
    """Step 3 — sort matched records into the buckets a briefing is organised around.

    A record can land in stale_warnings AND its type bucket. Staleness demotes a record,
    it does not hide it: the reader still sees the content and is told not to trust it
    blindly. Deleting or withholding it would destroy the fact that it was once true.
    """
    buckets: dict[str, list[dict]] = {
        "armed_gates": [], "relevant_defects": [], "live_retractions": [],
        "in_scope_tombstones": [], "threat_prior_art": [], "rules": [],
        "vocabulary": [], "stale_warnings": [],
    }
    for n in hits:
        pub = _node_public(n)
        if n.is_stale():
            buckets["stale_warnings"].append(pub)
        if n.type == "Gate":
            buckets["armed_gates"].append(pub)
        elif n.type == "Defect":
            buckets["relevant_defects"].append(pub)
        elif n.type == "Retraction" or (n.type == "Claim" and n.status == "retracted"):
            buckets["live_retractions"].append(pub)
        elif n.type == "Tombstone":
            buckets["in_scope_tombstones"].append(pub)
        elif n.type == "PriorArt" and (n.status == "live" or (n.body and "THREAT" in n.body)):
            buckets["threat_prior_art"].append(pub)
        elif n.type == "Rule":
            buckets["rules"].append(pub)
        elif n.type == "Vocabulary":
            buckets["vocabulary"].append(pub)
    return buckets


def _attach_catches(store: Store, gates: list[dict]) -> None:
    """Name, on each gate, the defect it prevents — by following its CATCHES edge.

    "Run this check" is an order; "run this check, it catches THIS bug" is a reason, and
    a reason is what survives contact with someone in a hurry. Mutates in place because
    the gate dicts are already the objects the briefing will render.
    """
    for g in gates:
        why = {n.title for (_e, n) in store.neighbors(g["id"], rels=["CATCHES"])
               if n.type == "Defect"}
        g["catches"] = sorted(why)


def _route_actions(buckets: dict[str, list[dict]]) -> list[dict]:
    """Step 4 — turn matched records into an ordered list of imperatives.

    The briefing leads with this. An agent handed context decides what to do with it; an
    agent handed "FIX x, ARM y, AVOID z" has already been told. Order is deliberate:
    gates first (cheapest to act on), then fixes, then the two prohibitions.
    """
    actions: list[dict] = [
        {"kind": "arm_gate", "target": g["title"],
         "why": g.get("catches") or None,
         "how": g.get("fix") or "run this gate before you finish the task"}
        for g in buckets["armed_gates"]
    ]
    actions += [
        {"kind": "apply_fix", "target": d["title"],
         "symptom": d.get("symptom"), "how": d["fix"]}
        for d in buckets["relevant_defects"] + buckets["rules"] if d.get("fix")
    ]
    actions += [
        {"kind": "avoid_retracted", "target": r["title"],
         "how": "do not restate this as fact; it was retracted"}
        for r in buckets["live_retractions"]
    ]
    actions += [
        {"kind": "avoid_identifier", "target": t["title"],
         "how": "do not reintroduce this retired identifier"}
        for t in buckets["in_scope_tombstones"]
    ]
    return actions


def record(store: Store, *, type: str, title: str, scope: str, repo: str | None = None,
           body: str | None = None, status: str | None = None, found_by: str | None = None,
           ttl_days: int | None = None, owner: str | None = None,
           files: str | None = None, symptom: str | None = None, fix: str | None = None,
           tags: str | None = None, verified: bool = False, id: str | None = None) -> str:
    """Create a node. `scope` is 'org' (propagates to all repos) or 'repo:<name>'.

    The scope decision is the curation gate: only world-facts (prior art, API
    contracts, data-source gotchas, vocabulary) should be 'org'. Repo-specific
    quirks stay 'repo:<name>' and never leak into another repo's `check`.

    `files` is a comma-separated list of path globs the node governs; setting it
    enrolls the node in the source-vs-spec drift detector (see drift.py).
    `symptom`/`fix` populate the Symptom→Cause→Fix schema (cause lives in `body`)
    so `check` can surface "if you see X, it's Y, do Z" instead of prose.
    `tags` is a comma-separated subject list from the controlled vocabulary
    (store.KNOWN_TAGS); repos declare interest tags so `check` can filter by subject.
    """
    if scope == "repo" and repo:
        scope = f"repo:{repo}"
    # Annotated dict[str, Any] because Node's fields are genuinely heterogeneous
    # (str, int, None); without it the ** splat is checked against whichever field
    # type mypy infers for the whole dict and every argument looks wrong.
    kw: dict[str, Any] = {
        "type": type, "title": title, "scope": scope, "repo": repo, "body": body,
        "status": status, "found_by": found_by, "ttl_days": ttl_days, "owner": owner,
        "files": files, "symptom": symptom, "fix": fix, "tags": tags,
        "verified_at": _now_ms() if verified else None,
    }
    # An explicit id makes the write idempotent (upsert replaces the same row);
    # omit it and the store mints a fresh random id (a genuinely new node).
    if id is not None:
        kw["id"] = id
    n = Node(**kw)
    return store.add_node(n)


def link(store: Store, src: str, rel: str, dst: str) -> None:
    """Join two records with a typed edge, validating the relation."""
    store.add_edge(Edge(src=src, rel=rel, dst=dst))


def verify(store: Store, node_id: str, evidence: str) -> dict[str, Any]:
    """Stamp a node verified from an OBSERVED check — never from assertion.

    `evidence` names the check that passed (the command + when). This is the
    store-side half of the verify-before-claiming rule: callers (the CLI, CI)
    must actually run the check first; this function just refuses to stamp
    without an evidence string and records it as the audit trail.
    """
    if not evidence or not evidence.strip():
        raise ValueError("refusing to stamp verification without evidence — run a check and pass it")
    n = store.get_node(node_id)
    if n is None:
        raise ValueError(f"no node with id {node_id!r}")
    n.verified_at = _now_ms()
    n.verified_by = evidence.strip()
    store.add_node(n)
    return _node_public(n)


def search(store: Store, query: str, scope: str | None = None,
           node_types: list[str] | None = None, limit: int = 25) -> list[dict]:
    """Free-text search with optional scope and type filters, ranked by the backend."""
    return [_node_public(n) for n in store.search(query, scope, node_types, limit)]


def render_actions_only(result: dict[str, Any], limit: int | None = None) -> str:
    """The routed action list and nothing else, for callers on a small context budget.

    A subagent working in a few thousand tokens cannot afford the full briefing (~4-5k
    tokens of bucketed detail). What it actually needs to change its behaviour is the
    imperative list: what to fix, when you see it, what to do. This drops the buckets,
    the prose bodies, and the stale-node footer, keeping one line per action.
    """
    actions = result.get("next_actions") or []
    if limit is not None:
        actions = actions[:limit]
    if not actions:
        if result.get("store_records") == 0:
            return ("OKL: the store is EMPTY (0 records). This is not 'no rules apply' — "
                    "nothing has been recorded yet, so this check proves nothing. "
                    "Run `okl seed` or record your first rule.")
        return f"OKL: no encoded rule applies to this task ({result['repo']}). Proceed."
    verb = {"arm_gate": "ARM", "apply_fix": "FIX", "avoid_retracted": "AVOID",
            "avoid_identifier": "AVOID"}
    out = [f"OKL — {len(actions)} rule(s) apply before you start:"]
    for a in actions:
        sym = f" [when: {a['symptom']}]" if a.get("symptom") else ""
        out.append(f"- {verb.get(a['kind'], 'DO')}: {a['target']}{sym}")
        out.append(f"  -> {a['how']}")
    return "\n".join(out)


def render_check_for_agent(result: dict[str, Any]) -> str:
    """Format a check() result as compact markdown for injection into agent context."""
    lines = [f"## OKL briefing — {result['repo']} · task: {result['task']}",
             f"_{result['match_count']} relevant node(s) from the org's encoded body._", ""]

    lines += _render_actions(result.get("next_actions") or [])

    order = [
        ("armed_gates", "🔒 Armed gates — adopt before you start"),
        ("relevant_defects", "⚠️  Past defects in this area"),
        ("live_retractions", "🚫 Live retractions — do not restate as fact"),
        ("in_scope_tombstones", "⛔ Retired identifiers — do not resurrect"),
        ("threat_prior_art", "📄 Prior art (THREAT) — novelty already claimed"),
        ("rules", "📐 Encoded rules"),
        ("vocabulary", "📖 Vocabulary"),
    ]
    any_hit = False
    for key, header in order:
        items = result.get(key) or []
        if not items:
            continue
        any_hit = True
        lines.append(f"### {header}")
        lines += _render_records(items, show_catches=key == "armed_gates")
        lines.append("")
    if result.get("stale_warnings"):
        lines.append(f"> {len(result['stale_warnings'])} node(s) are past TTL and shown demoted — re-verify before trusting.")
    if result.get("dropped_by_cutoff"):
        lines.append(f"> {result['dropped_by_cutoff']} lower-ranked record(s) were trimmed to keep this "
                     "briefing short. Raise --limit or narrow the task if you expected more.")
    if not any_hit:
        if result.get("store_records") == 0:
            lines.append("> **The store is EMPTY (0 records).** This check proves nothing: there is "
                         "no encoded knowledge to match against yet. That is different from "
                         "\"no rule applies here\". Run `okl seed`, or record your first rule "
                         "with `okl record`.")
        else:
            lines.append("_No encoded rule matched this task. Proceeding with a clean slate — "
                         "record anything you learn with `okl record`._")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Near-duplicate detection
# ---------------------------------------------------------------------------

def _dedup_fields(n: Any) -> dict[str, str]:
    """The fields worth comparing, per field rather than as one bag.

    `body` is deliberately excluded. It holds the cause — the longest, most prose-like
    field — and pooling it into one token bag let common corpus vocabulary ("record",
    "check", "field") dominate the score. Comparing like field with like is far more
    discriminating: two records describing the same observable have similar SYMPTOMS,
    whatever their authors called them.
    """
    get = (lambda k: getattr(n, k, None)) if not isinstance(n, dict) else n.get
    return {f: (get(f) or "") for f in ("title", "symptom", "fix")}


_DEDUP_STOP = {"the", "a", "an", "is", "are", "to", "of", "in", "on", "and", "or", "for",
               "it", "that", "this", "with", "from", "by", "be", "not", "no", "as", "at",
               "its", "so", "than", "then", "when", "which", "must", "never", "always"}


def _tokens(s: str) -> set[str]:
    words = "".join(ch if ch.isalnum() else " " for ch in s.lower()).split()
    # crude suffix stripping so "paginates"/"pagination" and "index"/"indexed" collide;
    # a stemmer would be better and would cost a dependency this package does not have.
    out = set()
    for w in words:
        if w in _DEDUP_STOP or len(w) < 3:
            continue
        for suf in ("ing", "ed", "es", "s"):
            if len(w) > 4 and w.endswith(suf):
                w = w[: -len(suf)]
                break
        out.add(w)
    return out


def _idf(store: Store) -> dict[str, float]:
    """Inverse document frequency over the store's own records.

    Without it every score is dominated by whatever this particular corpus talks about
    constantly. In a store of engineering lessons that is words like "record", "check"
    and "test" — present in most records, distinguishing none. Measured on the real
    190-record store, unweighted Jaccard put true paraphrases and unrelated pairs in the
    same 0.35-0.45 band, which is a detector that cannot be thresholded.
    """
    import math
    df: dict[str, int] = {}
    n = 0
    for node in store.all_nodes():
        n += 1
        for t in set().union(*(_tokens(v) for v in _dedup_fields(node).values())) or set():
            df[t] = df.get(t, 0) + 1
    if not n:
        return {}
    return {t: math.log(1 + n / c) for t, c in df.items()}


def _weighted_jaccard(a: set[str], b: set[str], idf: dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    default = 1.0
    inter = sum(idf.get(t, default) for t in a & b)
    union = sum(idf.get(t, default) for t in a | b)
    return inter / union if union else 0.0


def duplicate_score(a: Any, b: Any, idf: dict[str, float] | None = None) -> float:
    """0..1 similarity between two records. Lexical and explainable on purpose.

    Per-field weighted Jaccard (title, symptom, fix) blended with a difflib ratio over
    the titles, which catches near-identical phrasing that shares few distinctive tokens.
    Symptom carries the most weight: it is the observable, and it is the field two
    documents describing the same rule are most likely to agree on.
    """
    import difflib
    idf = idf or {}
    fa, fb = _dedup_fields(a), _dedup_fields(b)
    weights = {"title": 1.0, "symptom": 1.4, "fix": 0.8}
    num = den = 0.0
    per_field = []
    for f, w in weights.items():
        ta, tb = _tokens(fa[f]), _tokens(fb[f])
        if not ta and not tb:
            continue
        j = _weighted_jaccard(ta, tb, idf)
        per_field.append(j)
        num += w * j
        den += w
    mean_field = num / den if den else 0.0
    # Blend the mean with the strongest single field rather than averaging alone. Two
    # records describing the same observable agree strongly on SYMPTOM while their titles
    # and fixes may share almost nothing — a mean drags that real signal back into the
    # noise. Measured: an IDOR paraphrase whose symptom was near-identical to the stored
    # record scored 0.41 on the mean, indistinguishable from unrelated pairs.
    best_field = max(per_field) if per_field else 0.0
    field_score = 0.5 * mean_field + 0.5 * best_field
    # A near-identical title is its own signal: two short titles can share almost no
    # distinctive tokens for Jaccard to work with and still obviously be the same record.
    title_ratio = (difflib.SequenceMatcher(None, fa["title"].lower(), fb["title"].lower()).ratio()
                   if fa["title"] and fb["title"] else 0.0)
    return max(field_score, title_ratio)


DEDUP_THRESHOLD = 0.45
"""Calibrated on the 190-record dogfood store, and deliberately set to over-report.

Measured. Paraphrases of records already in the store — the same rule as a second
document would state it — score 0.43 to 0.51. The closest pair of genuinely distinct
records scores 0.43, and 12 distinct pairs clear 0.45. Those bands overlap, so no
threshold separates them:

  0.45  catches most paraphrases, and reports ~12 pairs per 190 records that are not
        duplicates at all
  0.50  reports nothing false on this corpus, and also misses two of three paraphrases

Lexical similarity cannot do better than this on paraphrased engineering prose; the words
genuinely differ. Clean separation needs embeddings, which
`docs/decisions/*-flat-retrieval-until-scale.md` defers until a measured symptom appears.
This is one: a miss rate high enough to matter, recorded rather than worked around.

So this surfaces candidates for a person to rule on, and never drops or merges a record.
A detector with this separation that acted on its own would delete real knowledge.
"""


def find_duplicates(store: Store, candidate: Any, threshold: float = DEDUP_THRESHOLD,
                    limit: int = 5, idf: dict[str, float] | None = None
                    ) -> list[tuple[float, Node]]:
    """Existing records that look like `candidate`, best match first.

    Shortlists with the store's own ranked search — the same BM25/ts_rank path a briefing
    uses, so it needs no extra index and no new dependency — then scores the shortlist.
    Search alone is the wrong tool (it ranks relevance to a query, not likeness between
    two records) and scoring every pair is O(n squared); the shortlist is the cheap half
    of the work and the score is the accurate half.
    """
    fields = _dedup_fields(candidate)
    text = " ".join(fields.values())
    if not text.strip():
        return []
    if idf is None:
        idf = _idf(store)
    cand_id = getattr(candidate, "id", None) or (candidate.get("id") if isinstance(candidate, dict) else None)
    hits = []
    for n in store.search(text, limit=max(limit * 6, 30)):
        if n.id == cand_id:
            continue
        score = duplicate_score(candidate, n, idf)
        if score >= threshold:
            hits.append((round(score, 3), n))
    hits.sort(key=lambda h: -h[0])
    return hits[:limit]


def _render_actions(actions: list[dict]) -> list[str]:
    """The routed "do this" list, which leads the briefing.

    First on purpose: an agent handed context decides what to do with it, an agent handed
    "FIX x — when you see y" has already been told. The verb map keeps the imperative
    consistent so the list is skimmable.
    """
    if not actions:
        return []
    verb = {"arm_gate": "ARM", "apply_fix": "FIX", "avoid_retracted": "AVOID",
            "avoid_identifier": "AVOID"}
    out = ["### ✅ Do this (routed actions)"]
    for a in actions:
        sym = f" — when you see: {a['symptom']}" if a.get("symptom") else ""
        out.append(f"- **{verb.get(a['kind'], 'DO')}: {a['target']}**{sym}")
        out.append(f"    → {a['how']}")
    out.append("")
    return out


def _render_records(items: list[dict], show_catches: bool = False) -> list[str]:
    """One bucket's records, in the briefing's line format.

    Fields are truncated rather than dropped: a reader who needs the whole record has its
    id, and a briefing that grows without bound stops being read at all.
    """
    out: list[str] = []
    for it in items:
        suffix = (f"  ← catches: {', '.join(it['catches'])}"
                  if show_catches and it.get("catches") else "")
        tag = " *(STALE — re-verify)*" if it.get("stale") else ""
        out.append(f"- **{it['title']}**{tag}{suffix}")
        if it.get("symptom"):
            out.append(f"  symptom: {it['symptom'][:160]}")
        if it.get("body"):
            out.append(f"  cause: {it['body'][:200]}" if it.get("symptom")
                       else f"  {it['body'][:200]}")
        if it.get("fix"):
            out.append(f"  fix: {it['fix'][:200]}")
    return out
