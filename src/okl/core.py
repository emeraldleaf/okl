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
    """
    """Scope answers "who may see this"; tags answer "what is this about".
    The repo's own nodes and untagged nodes always pass — declared interests
    only drop org nodes tagged entirely outside them."""
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

    buckets: dict[str, list[dict]] = {
        "armed_gates": [], "relevant_defects": [], "live_retractions": [],
        "in_scope_tombstones": [], "threat_prior_art": [], "rules": [],
        "vocabulary": [], "stale_warnings": [],
    }
    # Step 3: bucket by type. A record can land in stale_warnings AND its type bucket —
    # staleness demotes a record, it does not hide it, so the reader still sees the
    # content and is told not to trust it blindly.
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

    # Follow each gate's CATCHES edge to name the defect it prevents. "Run this check"
    # is an order; "run this check, it catches THIS bug" is a reason, and a reason is
    # what survives contact with someone in a hurry.
    for g in buckets["armed_gates"]:
        why = {n.title for (e, n) in store.neighbors(g["id"], rels=["CATCHES"])
               if n.type == "Defect"}
        g["catches"] = sorted(why)

    # Router (Codified Context §3.1.1 `suggest_agent`): turn the matched nodes into an
    # explicit, ordered action list so the agent gets "do this" not just "here's context".
    actions: list[dict] = []
    for g in buckets["armed_gates"]:
        actions.append({"kind": "arm_gate", "target": g["title"],
                        "why": g.get("catches") or None,
                        "how": g.get("fix") or "run this gate before you finish the task"})
    for d in buckets["relevant_defects"] + buckets["rules"]:
        if d.get("fix"):
            actions.append({"kind": "apply_fix", "target": d["title"],
                            "symptom": d.get("symptom"), "how": d["fix"]})
    for r in buckets["live_retractions"]:
        actions.append({"kind": "avoid_retracted", "target": r["title"],
                        "how": "do not restate this as fact; it was retracted"})
    for t in buckets["in_scope_tombstones"]:
        actions.append({"kind": "avoid_identifier", "target": t["title"],
                        "how": "do not reintroduce this retired identifier"})

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
    kw = dict(
        type=type, title=title, scope=scope, repo=repo, body=body, status=status,
        found_by=found_by, ttl_days=ttl_days, owner=owner,
        files=files, symptom=symptom, fix=fix, tags=tags,
        verified_at=_now_ms() if verified else None,
    )
    # An explicit id makes the write idempotent (upsert replaces the same row);
    # omit it and the store mints a fresh random id (a genuinely new node).
    if id is not None:
        kw["id"] = id
    n = Node(**kw)
    return store.add_node(n)


def link(store: Store, src: str, rel: str, dst: str) -> None:
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

    # Router first: the ordered "do this" list, so the agent acts, not just reads.
    actions = result.get("next_actions") or []
    if actions:
        lines.append("### ✅ Do this (routed actions)")
        verb = {"arm_gate": "ARM", "apply_fix": "FIX", "avoid_retracted": "AVOID",
                "avoid_identifier": "AVOID"}
        for a in actions:
            v = verb.get(a["kind"], "DO")
            sym = f" — when you see: {a['symptom']}" if a.get("symptom") else ""
            lines.append(f"- **{v}: {a['target']}**{sym}")
            lines.append(f"    → {a['how']}")
        lines.append("")

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
        for it in items:
            suffix = ""
            if key == "armed_gates" and it.get("catches"):
                suffix = f"  ← catches: {', '.join(it['catches'])}"
            tag = " *(STALE — re-verify)*" if it.get("stale") else ""
            lines.append(f"- **{it['title']}**{tag}{suffix}")
            if it.get("symptom"):
                lines.append(f"  symptom: {it['symptom'][:160]}")
            if it.get("body"):
                lines.append(f"  cause: {it['body'][:200]}" if it.get("symptom") else f"  {it['body'][:200]}")
            if it.get("fix"):
                lines.append(f"  fix: {it['fix'][:200]}")
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
