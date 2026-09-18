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
- 2026-09-02: `python` added. A code review of this repo found 190 records of which 75 were
  tagged `dotnet` — CQRS, aggregates, outbox, DI scopes — governing a Python codebase that has
  none of those things, while okl's own conventions had no subject to file under. `python-rag`
  was the nearest existing tag and is wrong: it is a stack tag for one service's retrieval
  pipeline, not a language. The distinction the vocabulary already draws (stacks vs subjects)
  did not have a slot for "the language this is written in", and adding one is cheaper than
  overloading a stack tag whose meaning other repos depend on.
- 2026-09-03: **the "revisit when" condition above was met, and the vocabulary is now
  extensible per store.** `KNOWN_TAGS` remains, but as the *floor* every store ships with
  rather than the whole vocabulary: a store widens it by recording `Vocabulary` nodes,
  whose title is the tag, and `Store.add_node` validates against floor ∪ declared.

  The trigger was a language-support audit. Everything else in okl is language-agnostic —
  drift asks git about path globs, verification runs whatever command you hand it, the
  store holds text — and a Rust repo was driven end to end successfully except for one
  thing: `okl record --tags rust` was refused, and the only remedy was to fork the package.
  That is a hard stop on adoption for a tool whose whole claim is that a lesson learned in
  one place reaches another.

  What the closed vocabulary was *for* survives intact. It exists to catch the typo that
  files a record where nobody looks, and closed-per-store still does: `rustt` is refused in
  a store that declared `rust`. What changes is who is entitled to grow it — the org that
  owns the store, rather than whoever can merge to this package.

  A `Vocabulary` node is validated against the floor only. Otherwise the first declaration
  in a fresh store would require the tag it is declaring.

  **Not extended:** `STACK_TAGS`, which gates `applies_to`. Declaring `rust` makes it usable
  as a subject tag, not as an applicability value. That is a narrower and rarer need — it
  only matters for a lesson that is genuinely false off-stack — and §4h measured that the
  filter `applies_to` feeds changes 0% of delivered briefing slots today. Extending the
  exclusive mechanism without a measurement is exactly what §4d punished.
