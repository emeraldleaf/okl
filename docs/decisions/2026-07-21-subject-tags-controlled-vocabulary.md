# ADR: Subject tags are a controlled vocabulary, orthogonal to scope

- **Status:** Accepted (2026-07-21)
- **Context prompted by:** the first dogfood run — `okl check` for an LLM-judge task returned
  28 of 33 stored nodes as "relevant" (recorded as defect `n_dc7429065f5d`), and the goal of
  growing the store beyond defects (specs, rules, article-review outputs) which would dilute
  every repo's briefing further.

## Context

Nodes had two organizing dimensions: **type** (Defect/Rule/Gate/…) and **scope** (`org` or
`repo:<name>`). Scope answers *who may see this*; nothing answered *what is this about*. So an
eval-integrity task in a Python repo received React and geospatial lessons, because `org` means
"show everyone" with no subject filter in between. The categories already existed informally —
seed-file comments ("eval-integrity lessons are org-scoped") and the scaffold's stack profiles
(`dotnet`, `react`, `python-rag`, `geospatial`) — but were not modeled.

## Decision

1. **One `tags` column** on nodes: comma-separated subject labels, same shape as `files`.
2. **The vocabulary is closed** (`store.KNOWN_TAGS`), like `NODE_TYPES`: stacks mirror the
   scaffold profiles; cross-cutting subjects start as `eval-integrity`, `agent-safety`,
   `security`, `retrieval-design`, `data-quality`, `method`. Growing it is a deliberate edit
   to that set — freeform tags sprawl and stop filtering. Unknown tags are rejected at
   `validate()`.
3. **Repos declare interests** in `.okl/config.json` (`okl init --interests …`). `check` drops
   org-scope nodes tagged entirely outside the declared interests. **Untagged nodes and the
   repo's own nodes always pass** — declaring interests must never hide a repo's own lessons
   or an uncategorized org lesson (fail open on missing metadata, closed only on a positive
   mismatch).
4. **Tags stay orthogonal to scope.** The rejected alternative was a third scope kind
   (`stack:react`); it conflates visibility with subject and breaks down as soon as a node is
   both react and security.

## Consequences

- **Positive:** the reference dogfood task went 28/33 → 20/33 matched nodes with zero ranking
  changes; the residue all shares a declared interest. Specs/rules/review outputs can now be
  added without diluting other repos' briefings.
- **Negative:** curation burden — new nodes should be tagged, and an over-broad interest list
  (declaring everything) restores the old behavior. Untagged legacy nodes bypass the filter by
  design, so tagging the backlog matters.
- **Still open:** the rank-cutoff half of `n_dc7429065f5d` (status: narrowed) — the briefing
  has no top-k or score threshold yet.
- **Revisit when:** the vocabulary needs per-org extension (KNOWN_TAGS is currently baked into
  the package), or the flat tag set starts wanting a hierarchy — which is a scale symptom in
  the sense of [2026-07-17-flat-retrieval-until-scale.md](2026-07-17-flat-retrieval-until-scale.md).

## Amendments

- 2026-07-21: `messaging` added to the vocabulary during the .NET platform canon import — the
  broker/queue/event-driven rules fit no existing subject.
