# ADR: OKL stays keyword/FTS until a measured scale threshold, then adds semantic retrieval

- **Status:** Accepted (2026-07-17)
- **Context prompted by:** Codified Context (arXiv 2602.20478 §3.3.1, §5.3), which uses keyword
  substring matching and names embedding retrieval as future work "to improve precision at scale";
  and the OKL positioning memo, which flagged that "staying flat" must read as a *decision*, not a gap.

## Context

`okl check` / `okl search` rank nodes with SQLite FTS5 (BM25 `ORDER BY rank`), falling back to `LIKE`
when FTS isn't compiled in. There is no embedding model, no vector index, no graph. The design doc's
standing rule is: *refuse to start as a graph; add complexity when a symptom demands it.*

Two external data points support staying flat **at current scale**:

1. **Mem0 removed its graph layer in v3** after its own benchmarks showed the graph lost on recall, ran
   ~3× slower, and cost ~2× tokens versus the flat store. Graph/semantic machinery is not free and does
   not automatically win.
2. Codified Context ran a **283-session** single project whose keyword-indexed corpus was its Tier-3
   knowledge base — **~16,250 lines across 34 specification docs** (the MCP server's substring matching
   indexes only the specs, per §3.3.1; the ~26.2K total-context figure also counts the always-loaded
   constitution and trigger-invoked agent specs, which are not keyword-searched) — and still reported the
   retrieval layer as load-bearing. Keyword matching did not break at that corpus size.

At OKL's current scale (tens of nodes per repo, low hundreds org-wide) FTS ranking is adequate: the A/B
experiment showed the correct lesson leading the briefing for covered tasks once `ORDER BY rank` was
fixed.

## Decision

Keep keyword/FTS retrieval as the default and **only** backend until a concrete, measured symptom
appears. The trigger to add semantic (embedding) retrieval is **any one** of:

- **Scale:** a single scope (org, or one repo) exceeds **~1,000 nodes** OR **~32,000 knowledge lines**
  (roughly 2× the ~16,250-line keyword-indexed corpus above). Below that, keyword recall is not the
  bottleneck.
- **Measured miss rate:** the coverage/A/B harness shows `okl check` failing to surface a node that *does*
  exist in scope (a retrieval miss, not a coverage gap) on **>10%** of tasks in a run of ≥20.
- **Vocabulary mismatch:** repeated real cases where the task and the encoded lesson share meaning but no
  words (the classic keyword failure), confirmed by inspection — not anecdote.

When triggered, the first step is **additive and measured**: add an embedding index *alongside* FTS,
fuse with reciprocal-rank fusion (the same RRF the RAG service profile already documents), and A/B the
fused ranker against FTS-only on the same task set before making it the default. Adopt it only if it
wins on that measurement — mirroring Mem0's mistake in reverse.

## Consequences

- **Positive:** zero embedding infra, zero model dependency, deterministic offline behavior, trivial
  install (`pip install okl` with no ML stack), and a clear falsifiable line for when the calculus
  changes.
- **Negative:** pure lexical recall can miss a semantically-related node phrased differently; until a
  trigger fires, we accept that and lean on good node titles + the FTS body index.
- **Revisit when:** any trigger above is hit, or the store gains a node type whose matching is inherently
  semantic (e.g. code-embedding similarity over diffs).
