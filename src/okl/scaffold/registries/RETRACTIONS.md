# Retractions

Claims this project once made and has since found to be false. A retraction is a **receipt**, not a
deletion — the wrong claim stays visible with its correction so it cannot be quietly restated.

The `retractions` gate fails any tracked doc that states a retracted claim without also retracting it.

## Format
Each entry: a stable `id`, the retracted claim (quoted), why it is false, and the date/commit.

<!-- <<FILL: retractions as you earn them. Example from the RAG service: -->
<!--
### R-0001 — "agentic's retrieval is architecturally weaker than classic"
- **Retracted:** the conclusion in `docs/rag-mode-eval-results.md`.
- **Why false:** the agent's primary tool (`search_filtered`) threw on every call and it was given
  top_k=3 vs classic's 8. It measured broken instrumentation, not an architecture. Error-analysis
  cross-tab showed generation, not retrieval, is the dominant failure mode.
- **Date/commit:** 2026-07 / findings-log Part 2.
-->
