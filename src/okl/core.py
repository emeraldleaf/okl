"""The three operations, independent of transport (CLI / HTTP / MCP all call these).

check(repo, task)   -> the pre-task neighborhood: armed gates, live retractions,
                       in-scope tombstones, THREAT prior-art, vocabulary, stale warnings.
                       This is the load-bearing read (design doc §3.4). Fails CLOSED
                       at the transport layer, never here.
record(node, scope) -> the org-scope arm of the encoding response (§3.3).
search(query, ...)  -> targeted retrieval (progressive disclosure).
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import asdict
from typing import Any

# STACK_TAGS is re-exported, not used here: adapters may import core and client but
# never store (dependency direction is one-way), and the CLI needs the stack list to
# judge which bundled seed packs fit a repo.
from .store import STACK_TAGS as STACK_TAGS
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

    TWO FILTERS, AND THEY ARE NOT SYMMETRIC.

    `applies_to` is EXCLUSIVE: it says where a lesson is valid, and a repo outside that
    set does not get it. Unset means "anywhere", which is the overwhelming default and
    the reason this is safe — a store that has never used the field behaves exactly as it
    did before.

    `tags` are INCLUSIVE: one shared subject is enough. Exclusive stack-tag filtering was
    tried here and reverted after the A/B measured it (REPORT.md §4d) — it hid 35 of 172
    org records and the briefed arm reproduced a defect whose rule it had dropped. The
    reason is that a stack tag records where a lesson was FOUND, not where it applies:
    "in-memory rate limiters weaken at N instances" carries `dotnet` because that is the
    codebase it came from, and is true of every runtime.

    That is the whole distinction. Provenance is inferred at import and is often wrong
    about applicability; `applies_to` is a judgment someone made deliberately, so it is
    the only one allowed to exclude.
    """
    if n.scope == repo_scope:
        return True
    if n.scope != "org":
        return False

    # APPLICABILITY first, and it is the only exclusive test. `applies_to` says where a
    # lesson is VALID, set deliberately by whoever recorded it. Unset means "anywhere",
    # so a store that has never used the field behaves exactly as before — the default is
    # the permissive path, which is what makes this safe to introduce. Contrast the tag
    # filter below, which is inclusive: one shared subject is enough.
    applies = split_tags(n.applies_to) - {"any"}
    wanted = {t.strip().lower() for t in (interests or []) if t.strip()}
    if applies and wanted and not (applies & wanted):
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
        "vocabulary": [], "decisions": [], "context": [], "stale_warnings": [],
    }
    for n in hits:
        pub = _node_public(n)
        if n.is_stale():
            buckets["stale_warnings"].append(pub)
        if n.type == "Retraction" or n.status == "retracted":
            # A withdrawn record of ANY type is a retraction, never live guidance. Only a
            # retracted Claim used to land here, so a Decision withdrawn in #122 was still
            # briefed under "made on purpose; do not silently reverse".
            buckets["live_retractions"].append(pub)
        elif n.type == "Gate":
            buckets["armed_gates"].append(pub)
        elif n.type == "Defect":
            buckets["relevant_defects"].append(pub)
        elif n.type == "Tombstone":
            buckets["in_scope_tombstones"].append(pub)
        elif n.type == "PriorArt" and (n.status == "live" or (n.body and "THREAT" in n.body)):
            buckets["threat_prior_art"].append(pub)
        elif n.type == "Rule":
            buckets["rules"].append(pub)
        elif n.type == "Vocabulary":
            buckets["vocabulary"].append(pub)
        elif n.type == "Decision":
            buckets["decisions"].append(pub)
        else:
            # Everything else that won a top-k slot (a live Claim, an Entity, prior art that
            # is not a threat) is still shown. These types had no bucket: they took a slot
            # and vanished, uncounted, so a Decision matching the task by its own title never
            # reached the agent (found by a docs audit, 2026-09-29).
            buckets["context"].append(pub)
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
    # `id` and `cause` let the briefing name each record once: the action line carries
    # everything the record's section entry used to repeat (see render_check_for_agent).
    actions: list[dict] = [
        {"kind": "arm_gate", "target": g["title"], "id": g.get("id"), "cause": g.get("body"), "stale": g.get("stale"),
         "symptom": g.get("symptom"), "why": g.get("catches") or None,
         "how": g.get("fix") or "run this gate before you finish the task"}
        for g in buckets["armed_gates"]
    ]
    actions += [
        {"kind": "apply_fix", "target": d["title"], "id": d.get("id"), "cause": d.get("body"), "stale": d.get("stale"),
         "symptom": d.get("symptom"), "how": d["fix"]}
        for d in buckets["relevant_defects"] + buckets["rules"] if d.get("fix")
    ]
    actions += [
        {"kind": "avoid_retracted", "target": r["title"], "id": r.get("id"), "cause": r.get("body"), "stale": r.get("stale"),
         "how": "do not restate this as fact; it was retracted"}
        for r in buckets["live_retractions"]
    ]
    actions += [
        {"kind": "avoid_identifier", "target": t["title"], "id": t.get("id"), "cause": t.get("body"), "stale": t.get("stale"),
         "how": "do not reintroduce this retired identifier"}
        for t in buckets["in_scope_tombstones"]
    ]
    return actions


def record(store: Store, *, type: str, title: str, scope: str, repo: str | None = None,
           body: str | None = None, status: str | None = None, found_by: str | None = None,
           ttl_days: int | None = None, owner: str | None = None,
           files: str | None = None, symptom: str | None = None,
           applies_to: str | None = None, fix: str | None = None,
           tags: str | None = None, verified: bool = False, id: str | None = None,
           keep_verification: bool = False, replace: bool = False,
           ) -> str:
    """Create a node. `scope` is 'org' (meant for every repo) or 'repo:<name>'.

    The scope decision is the curation gate: only world-facts (prior art, API
    contracts, data-source gotchas, vocabulary) should be 'org'. Repo-specific
    quirks stay 'repo:<name>' and never leak into another repo's `check`.

    `files` is a comma-separated list of path globs the node governs; setting it
    enrolls the node in the source-vs-spec drift detector (see drift.py).
    `symptom`/`fix` populate the Symptom→Cause→Fix schema (cause lives in `body`)
    so `check` can surface "if you see X, it's Y, do Z" instead of prose.
    `tags` is a comma-separated subject list from the controlled vocabulary
    (store.KNOWN_TAGS); repos declare interest tags so `check` can filter by subject.

    `keep_verification` is for re-importing a lesson the store already holds (`okl seed`).
    Verification is about the code, not the lesson's wording, so the existing stamp, its
    evidence and its commit are kept while the governed files are the same, and cleared
    when they change (#110). Without it, every re-seed re-stamped each lesson as verified
    now and wiped its evidence, so a repo that re-seeds after edits could never drift.

    An `id` that already names a lesson raises LessonExistsError unless `replace` (or
    `keep_verification`) says the overwrite is meant. Re-recording an id used to replace
    the whole row, proof and creation date included, and every surface taught it as the
    way to refine a lesson (okl review R1); `update` is that way now. An overwrite keeps
    the lesson's first creation date.
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
        "applies_to": applies_to,
        "verified_at": _now_ms() if verified else None,
    }
    # An explicit id names the lesson; omit it and the store mints a fresh random one.
    if id is not None:
        kw["id"] = id
        _carry_over(store, kw, id, replace=replace, keep_verification=keep_verification)
    n = Node(**kw)
    return store.add_node(n)


class LessonExistsError(ValueError):
    """Raised when `record` is given the id of a lesson the store already holds.

    A ValueError, so every caller that reports a rejected write (exit 2, a 400 from the
    service, NOT RECORDED over MCP) reports this one too, with its message.
    """


def _carry_over(store: Store, kw: dict[str, Any], node_id: str, *,
                replace: bool, keep_verification: bool) -> None:
    """Decide what a write to an existing id keeps from the lesson it overwrites.

    Refuses unless the overwrite is meant. Always keeps the first creation date. Keeps
    the proof only for a re-import (`keep_verification`) whose governed files are the
    same: verification is about the code, so a check of other files proves nothing here.
    When the files differ the stamp goes but the stored check (`verified_by`) stays, so
    `okl reverify` can re-run it against the new files.
    """
    old = store.get_node(node_id)
    if old is None:
        return
    if not (replace or keep_verification):
        raise LessonExistsError(
            f"a lesson with id {node_id!r} already exists ({old.title!r}). To change it, use "
            f"`okl update {node_id} --<field> ...` (the okl_update tool over MCP), which keeps "
            "its proof; to overwrite it entirely, record it again with --replace.")
    kw["created_at"] = old.created_at
    if not keep_verification:
        return
    if not _same_files(old.files, kw.get("files")):
        kw.update(verified_at=None, verified_commit=None, verified_by=old.verified_by)
    elif old.verified_at is not None:
        kw.update(verified_at=old.verified_at, verified_by=old.verified_by,
                  verified_commit=old.verified_commit)


# The fields `update` may change, and those it may not leave empty.
UPDATABLE_FIELDS = ("type", "title", "scope", "body", "status", "found_by", "ttl_days",
                    "owner", "files", "symptom", "fix", "tags", "applies_to")
_REQUIRED = ("type", "title", "scope")


def update(store: Store, node_id: str, repo: str | None = None,
           **fields: Any) -> dict[str, Any]:
    """Change the given fields of an existing lesson, keep the rest, and return it.

    The way to refine a lesson (okl review R1). A field passed as None is left alone, and
    an empty string clears an optional one. The proof (verified_at, verified_by,
    verified_commit) and the first creation date are kept, unless the governed `files`
    change: a check of other files proves nothing about these, so the stamp
    (verified_at, verified_commit) is cleared and the lesson shows as unproven until it
    is verified again. The stored check (verified_by) stays, so `okl reverify` can re-run
    it. `scope="repo"` becomes `repo:<repo>`, as in `record`, and is refused when there is
    no repo to name.

    Raises ValueError for an unknown id, an unknown field, nothing to change, an empty
    required field, or a value the store rejects (an unknown tag, a bad scope).
    """
    n = store.get_node(node_id)
    if n is None:
        raise ValueError(f"no lesson with id {node_id!r}")
    changes = _update_values(fields, repo or n.repo)
    old_files = n.files
    for k, v in changes.items():
        setattr(n, k, v)
    if "files" in changes and not _same_files(old_files, n.files):
        n.verified_at = n.verified_commit = None
    store.add_node(n)
    return _node_public(n)


def _update_values(fields: dict[str, Any], repo: str | None) -> dict[str, Any]:
    """The values `update` writes: None is left out, an empty string clears the field, and
    a required field may not be cleared. Raises ValueError, naming what is wrong."""
    unknown = set(fields) - set(UPDATABLE_FIELDS)
    if unknown:
        raise ValueError(f"cannot update {sorted(unknown)}; updatable: {list(UPDATABLE_FIELDS)}")
    given = {k: v for k, v in fields.items() if v is not None}
    if not given:
        raise ValueError(f"nothing to change: pass at least one of {list(UPDATABLE_FIELDS)}")
    out: dict[str, Any] = {}
    for k, v in given.items():
        blank = isinstance(v, str) and not v.strip()
        if blank and k in _REQUIRED:
            raise ValueError(f"{k} cannot be empty")
        if (k, v) == ("scope", "repo"):
            if not repo:
                raise ValueError("scope 'repo' needs a repo name to become repo:<name>; "
                                 "pass the repo, or give the scope as repo:<name>")
            v = f"repo:{repo}"
        out[k] = None if blank else v
    return out


def get(store: Store, node_id: str) -> dict[str, Any] | None:
    """One lesson by id, as the API exposes it, or None if there is none."""
    n = store.get_node(node_id)
    return _node_public(n) if n is not None else None


def _same_files(a: str | None, b: str | None) -> bool:
    """Whether two `files` values name the same globs, ignoring order, spacing and blanks."""
    def norm(v: str | None) -> set[str]:
        return {g.strip() for g in (v or "").split(",") if g.strip()}
    return norm(a) == norm(b)


def link(store: Store, src: str, rel: str, dst: str) -> None:
    """Join two records with a typed edge, validating the relation."""
    store.add_edge(Edge(src=src, rel=rel, dst=dst))


def verify(store: Store, node_id: str, evidence: str, commit: str | None = None) -> dict[str, Any]:
    """Stamp a node verified from an OBSERVED check — never from assertion.

    `evidence` names the check that passed (the command + when). This is the
    store-side half of the verify-before-claiming rule: callers (the CLI, CI)
    must actually run the check first; this function just refuses to stamp
    without an evidence string and records it as the audit trail.

    `commit` is the git HEAD the check passed at. Drift compares the governed files
    there with HEAD instead of comparing clocks, which git keeps to the second (#102).
    It is always overwritten, so a re-verification outside git cannot leave an older
    commit standing in for a check it never saw.
    """
    if not evidence or not evidence.strip():
        raise ValueError("refusing to stamp verification without evidence — run a check and pass it")
    # The commit reaches `git diff` later, so anything but a hex object name is refused
    # here: a shared store is written by other people.
    if commit is not None and not re.fullmatch(r"[0-9a-f]{7,64}", commit):
        raise ValueError(f"commit must be a git object name (7-64 hex digits), got {commit!r}")
    n = store.get_node(node_id)
    if n is None:
        raise ValueError(f"no node with id {node_id!r}")
    n.verified_at = _now_ms()
    n.verified_by = evidence.strip()
    n.verified_commit = commit
    store.add_node(n)
    return _node_public(n)


def search(store: Store, query: str, scope: str | None = None,
           node_types: list[str] | None = None, limit: int = 25) -> list[dict]:
    """Free-text search with optional scope and type filters, ranked by the backend."""
    return [_node_public(n) for n in store.search(query, scope, node_types, limit)]


def briefing_notice(result: dict[str, Any], shown: int = 3) -> str | None:
    """One line for the PERSON, not the model: what okl just briefed, or None when nothing
    matched (a line on every prompt saying "nothing" is noise). The briefing itself goes to
    the model's context and is invisible in the UI, so without this a user never sees okl
    work and cannot tell a helping tool from a dead one."""
    if not result.get("match_count"):
        if result.get("store_records") == 0:
            return "okl · the store is empty, so nothing was briefed — see docs/GETTING-STARTED.md"
        return None
    titles = [a["target"] for a in result.get("next_actions") or []]
    for key in ("armed_gates", "relevant_defects", "rules", "decisions", "live_retractions",
                "in_scope_tombstones", "threat_prior_art", "context"):
        titles += [r["title"] for r in result.get(key) or [] if r["title"] not in titles]
    def trim(t: str, n: int = 48) -> str:
        t = t.split(" — ")[0].split(" = ")[0].strip()
        return t if len(t) <= n else t[:n].rsplit(" ", 1)[0].rstrip(",;:") + "…"
    short = [trim(t) for t in titles[:shown]]
    more = result["match_count"] - len(short)
    return (f"okl · briefed {result['match_count']} lesson(s): " + "; ".join(short)
            + (f" (+{more} more)" if more > 0 else "")
            + (f" · {result['drifted']} need re-checking" if result.get("drifted") else ""))


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
        out.append(f"- {verb.get(a['kind'], 'DO')}: {a['target']}{_id_tag(a)}{_drift_tag(a)}{sym}")
        out.append(f"  -> {a['how']}")
    return "\n".join(out)


def render_check_for_agent(result: dict[str, Any]) -> str:
    """Format a check() result as compact markdown for injection into agent context."""
    lines = [f"## OKL briefing — {result['repo']} · task: {result['task']}",
             f"_{result['match_count']} relevant node(s) from the org's encoded body._", ""]

    actions = result.get("next_actions") or []
    lines += _render_actions(actions)
    # Each record once. A record routed into an action above used to be printed again, in
    # full, under its section: about half of every briefing, on every prompt. The action
    # line now carries its cause (and what a gate catches), so the section skips it.
    # Guarded by test_briefing_names_each_record_once_and_loses_nothing.
    actioned = {a["id"] for a in actions if a.get("id")}

    order = [
        ("armed_gates", "🔒 Armed gates — adopt before you start"),
        ("relevant_defects", "⚠️  Past defects in this area"),
        ("live_retractions", "🚫 Live retractions — do not restate as fact"),
        ("in_scope_tombstones", "⛔ Retired identifiers — do not resurrect"),
        ("threat_prior_art", "📄 Prior art (THREAT) — novelty already claimed"),
        ("rules", "📐 Encoded rules"),
        ("decisions", "🧭 Decisions — made on purpose; do not silently reverse"),
        ("vocabulary", "📖 Vocabulary"),
        ("context", "📎 Related context"),
    ]
    # Judged on the whole briefing: when every match was routed into an action the sections
    # are empty, and "No encoded rule matched" appeared under a list of actions.
    any_hit = bool(actions)
    for key, header in order:
        items = [it for it in (result.get(key) or []) if it.get("id") not in actioned]
        if not items:
            continue
        any_hit = True
        lines.append(f"### {header}")
        lines += _render_records(items, show_catches=key == "armed_gates")
        lines.append("")
    if result.get("stale_warnings"):
        lines.append(f"> {len(result['stale_warnings'])} node(s) are past TTL and shown demoted — re-verify before trusting.")
    if result.get("drifted"):
        lines.append(f"> {result['drifted']} lesson(s) govern code that changed after their last check, "
                     "or were never checked: confirm them against the code before relying on them.")
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


def _drift_tag(item: dict) -> str:
    """The briefing's mark for a lesson whose governed code moved since its last check (#93).

    Says which files and when, and the command that settles it, so the agent can treat the
    lesson as a lead to confirm rather than a settled rule, and the person can re-check it.
    """
    d = item.get("drift")
    if not d:
        return ""
    files = d["files"] if len(d["files"]) <= 60 else d["files"][:59] + "…"
    lead = ("a lead, not a settled rule: re-run its check (okl reverify), "
            "and if it fails, fix the code or change the lesson on purpose")
    if d["reason"] == "never verified":
        return (f" *(UNVERIFIED — governs {files} but no check has passed; "
                f"prove it: okl verify {item.get('id')} --run …)*")
    # Each verdict carries different fields, so each gets its own sentence. This one has
    # no verification date to print, and reading one crashed the briefing (#126).
    if d["reason"] == "verified with no observed check":
        return (f" *(UNPROVEN — governs {files}, but no observed check backs its stamp; "
                f"prove it: okl verify {item.get('id')} --run …)*")
    if d["reason"] == "verified on another branch":
        return (f" *(STALE — last checked on {d.get('commit', '?')}, a commit from another "
                f"branch, and {files} differ here; {lead})*")
    return (f" *(STALE — {files} changed {d['changed']}, after its last check on "
            f"{d['verified']}; {lead})*")


def _id_tag(item: dict) -> str:
    """The lesson's id in brackets, so an agent can update, retire, link or verify the
    lesson it was just shown without searching for it first (okl review R1)."""
    return f" [{item['id']}]" if item.get("id") else ""


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
        # The per-record stale marker lives here now that a routed record has no section
        # entry of its own (#52 review); a bare count cannot say which action to distrust.
        tag = (" *(STALE — re-verify)*" if a.get("stale") else "") + _drift_tag(a)
        out.append(f"- **{verb.get(a['kind'], 'DO')}: {a['target']}**{_id_tag(a)}{tag}{sym}")
        out.append(f"    → {a['how']}")
        if a.get("why"):
            out.append(f"    catches: {', '.join(a['why'])}")
        if a.get("cause"):
            out.append(f"    why: {a['cause'][:200]}")
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
        tag = (" *(STALE — re-verify)*" if it.get("stale") else "") + _drift_tag(it)
        out.append(f"- **{it['title']}**{_id_tag(it)}{tag}{suffix}")
        if it.get("symptom"):
            out.append(f"  symptom: {it['symptom'][:160]}")
        if it.get("body"):
            out.append(f"  cause: {it['body'][:200]}" if it.get("symptom")
                       else f"  {it['body'][:200]}")
        if it.get("fix"):
            out.append(f"  fix: {it['fix'][:200]}")
    return out


def recurrence_report(store: Store) -> dict[str, Any]:
    """Recurrence, with the coverage that makes it readable (issue #31).

    The metric used to print "0 recurrences ✓" while the store held recorded recurrences,
    because it could only see defects that had a gate attached: 8 of 63 at the time, and it
    never said so. The same shape as the eval judge that scored 5.0/5.0 while 19 of 20
    cases crashed: a number that cannot report its own coverage reads as a result.

    So the report carries three things, never one:
      - `armed`:   recurrences of defects that HAD a gate -- the original metric;
      - `unarmed`: recurrences of defects with no gate -- lessons written down that came
                   back anyway, which is the stronger signal;
      - coverage:  how many defects the armed figure can possibly speak for.

    RECURS_IN is written two ways in practice, and both are read. `new RECURS_IN original`
    (both ends records) names the original as the defect that recurred; the seed packs write
    `defect RECURS_IN <repo name>`, where the far end is not a record and the near end is
    the defect. Reading only the first form silently discarded every seeded recurrence.
    """
    nodes = {n.id: n for n in store.all_nodes()}
    recurs = store.edges(["RECURS_IN"])
    # A record written to SAY a defect recurred is not another defect class: it points at
    # the original, never carries a gate, and counting it in the denominator made every
    # new recurrence quietly lower the coverage percentage. Only classes are counted -- and
    # only a pointer to another DEFECT makes a record a report; one aimed at a Rule does not.
    reports = {e.src for e in recurs if e.dst in nodes and nodes[e.dst].type == "Defect"}
    defect_ids = {i for i, n in nodes.items() if n.type == "Defect" and i not in reports}
    gates_for: dict[str, list[str]] = {}
    for e in store.edges(["CATCHES"]):
        # Only a Gate arms a defect. The seed packs hold a Rule that CATCHES a defect -- a
        # testing practice -- and a practice nobody runs mechanically is not arming.
        if e.dst in defect_ids and e.src in nodes and nodes[e.src].type == "Gate":
            gates_for.setdefault(e.dst, []).append(nodes[e.src].title)

    armed: list[dict[str, Any]] = []
    unarmed: list[dict[str, Any]] = []
    for e in recurs:
        if e.dst in nodes:                        # new RECURS_IN original
            cls, where = e.dst, (nodes[e.src].repo if e.src in nodes else None)
        else:                                     # defect RECURS_IN <repo name>
            cls, where = e.src, e.dst
        if cls not in nodes or nodes[cls].type != "Defect":
            continue                              # not a defect class we hold
        row = {"defect_class": nodes[cls].title, "defect_id": cls, "recurred_in": where}
        if cls in gates_for:
            armed.append({**row, "gates": gates_for[cls]})
        else:
            unarmed.append(row)

    return {"armed": armed, "unarmed": unarmed,
            "defects": len(defect_ids), "defects_with_gate": len(gates_for)}


def recurrence_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    """The pre-#31 flat shape -- one row per gate on each armed recurrence -- derived from
    the report, never computed beside it, so the legacy and new shapes cannot disagree.
    `/metric/recurrence` and `Client.recurrence()` both serve it to callers written
    against v0.5."""
    return [{"recurred_in": r["recurred_in"], "defect_class": r["defect_class"], "gate": g}
            for r in report["armed"] for g in r["gates"]]


# ---------------------------------------------------------------------------
# The exposure log (#129): which lessons briefings actually show. Recurrence says which
# lessons came back; this says which ones anybody was shown, so a lesson nobody has seen
# in months, or one shown constantly with nothing checking it, becomes visible.
# ---------------------------------------------------------------------------

# Left out of "could have been shown": a Vocabulary record declares a tag. It is not
# advice, so going unseen says nothing about whether to keep it.
_NOT_ADVICE = frozenset({"Vocabulary"})


def briefed_ids(result: dict[str, Any]) -> list[str]:
    """The ids of the lessons a briefing showed, in the order it showed them, each once.

    Read from the type buckets, where every briefed record sits exactly once.
    next_actions and stale_warnings are skipped: both repeat records already counted.
    """
    ids: dict[str, None] = {}
    for key, items in result.items():
        if key in ("next_actions", "stale_warnings") or not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and item.get("id"):
                ids.setdefault(str(item["id"]), None)
    return list(ids)


def record_briefing(store: Store, repo: str, result: dict[str, Any]) -> bool:
    """Log which lessons `result` showed, and return whether the log was written.

    OKL_BRIEFING_LOG=0 turns logging off; the eval harness sets it, so test runs do not
    count as exposure. A failed write returns False instead of raising. The log is a side
    channel: the prompt hook fails closed, so an exception here would block the user's
    prompt over a counter.
    """
    if os.environ.get("OKL_BRIEFING_LOG") == "0":
        return False
    try:
        store.log_briefing(repo, briefed_ids(result))
    except Exception:  # noqa: BLE001 - losing one log row beats losing the briefing; see above
        return False
    return True


def exposure_report(store: Store, repo: str, interests: list[str] | None = None,
                    top: int = 10) -> dict[str, Any]:
    """Which of the lessons `repo` can be briefed its briefings have actually shown (#129).

    Coverage travels with the figures, as in recurrence_report. The log holds only the
    briefings since it existed, and only while OKL_BRIEFING_LOG was not 0, so "never
    shown" means never shown in `briefings` logged briefings since `first_at`. Over zero
    briefings the report says nothing about any lesson, and the caller must say so.

    "Can be briefed" is _in_scope, the test check applies, so a lesson this repo's scope
    or interests filter out is not reported as unseen. Each list holds at most `top`.
    """
    logged = store.briefings(repo)
    repo_scope = f"repo:{repo}"
    reachable = [n for n in store.all_nodes()
                 if n.type not in _NOT_ADVICE and _in_scope(n, repo_scope, interests)]
    times = Counter(i for b in logged for i in b.node_ids)

    def row(n: Node) -> dict[str, Any]:
        return {"id": n.id, "type": n.type, "title": n.title, "times": times[n.id],
                "checked": bool(n.verified_by)}

    # Never shown, oldest first: the longer a lesson has gone unseen, the better a
    # candidate it is to review or retire.
    never = sorted((n for n in reachable if not times[n.id]), key=lambda n: (n.created_at, n.id))
    shown = sorted((n for n in reachable if times[n.id]), key=lambda n: (-times[n.id], n.id))
    return {
        "repo": repo,
        "briefings": len(logged),
        "first_at": logged[0].at if logged else None,
        "last_at": logged[-1].at if logged else None,
        "reachable": len(reachable),
        "shown": len(shown),
        "never_shown_count": len(never),
        "never_shown": [row(n) for n in never[:top]],
        "most_shown": [row(n) for n in shown[:top]],
        # Shown often with nothing proving it: candidates for a check (`okl verify --run`).
        "most_shown_unchecked": [row(n) for n in shown if not n.verified_by][:top],
    }
