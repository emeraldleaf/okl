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

1. **Mem0's graph variant cost more and won little.** In Mem0's own paper (arXiv 2504.19413, Tables 1
   and 2, vendor-run), the graph variant scored 68.44 against 66.88 overall but lower on single-hop
   (65.71 against 67.13) and multi-hop questions (47.19 against 51.15), retrieved about twice the memory
   tokens (3,616 against 1,764) and took about three times the search p95 (0.657 s against 0.200 s).
   Mem0 v3 later removed the external graph stores from its open-source SDK (PR #4805, April 2026) in
   favour of entity matching as a third hybrid-search signal; it stated no reason, and graph memory
   remains on its paid platform. Graph/semantic machinery is not free and does not automatically win.
   (Corrected 2026-10-25: this item first said Mem0 removed the graph "after its own benchmarks", an
   inference Mem0 never stated; the figures above were read from the paper's tables.)
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

## Amendments

- 2026-09-29: the install line above reads `pip install okl`, but the distribution is published
  as `observed-knowledge-ledger` (PyPI refuses the name `okl`); the command is
  `pip install observed-knowledge-ledger`, and the CLI is still `okl`. The consequence it
  illustrates, an install with no ML stack, is unchanged.
- 2026-10-23: the vocabulary-mismatch trigger fired (`evals/results/probe-rephrase-20261021.txt`,
  #258: paraphrases of the eval tasks reached their lesson 0 of 8 times). The first step was
  not the embedding index. Two lexical arms were measured first and both shipped: a symptom on
  every advice record (REPORT §4o; the probe's bug-report row 3 → 8 of 8) and authored
  aliases (§4p; one more ticket and one more paraphrase on a blind held-out set). The index
  then followed the step above: a local static model (`minishlab/potion-retrieval-32M`) beside
  FTS5, fused by reciprocal rank and by a convex combination, measured on the same tasks
  (§4q). It did not win by enough to become the default: one more held-out paraphrase of
  eight under linear fusion at a 0.40 cosine line, nothing on tickets or bug reports, one
  record more on two of six short prompts, and 0.8 s per prompt for the model load. It ships
  optional (`okl embed`, `okl check --hybrid`, `"hybrid": "linear"` in `.okl/config.json`),
  off by default, and the README's "no embeddings" line says so. Scale: the search is a numpy
  matrix product over every stored vector (24 ms at 50,000 records after an 80 ms read,
  `semantic-scale-20261031-0559.txt`; the figure first written here timed the product alone,
  corrected per REPORT §4q's erratum); the next tier, an
  approximate index over the same table (sqlite-vec locally, pgvector on the service), is the
  amendment to make when a store crosses about 100,000 vectors or a search exceeds 100 ms.
  The next retrieval experiment is a stronger local model or a reranker on the held-out set;
  the default changes only if one wins there.
- 2026-10-23, later: the reranker was measured (REPORT §4t). A local cross-encoder
  (`Xenova/ms-marco-MiniLM-L-6-v2`, chosen from five on a selection set; five contextual
  embedders were compared at the same time and the static model kept) over the first 24
  fused candidates moved one held-out paraphrase into the briefing and one held-out bug
  report out, left the six short prompts' counts unchanged, and cost 0.5 s a check; the
  pre-registered falsifier fired, so it ships as `okl check --rerank`, off. The default
  remains the first stage. The next experiment is the floor's rule for a candidate only the
  semantic arm returned, or a wider first-stage window, each pre-registered.
