---
description: RAG pipeline rules — retrieval vs identity, eval integrity, agent contract
paths: ["**/*.py"]
---

# RAG / agentic pipeline (Python / FastAPI / Qdrant / eval)

> Ported from the RAG service docs/findings-log.md + agent-contract.md. Stack: FastAPI, Qdrant (hybrid
> dense+BM25+RRF), Redis, Postgres, Ollama/OpenAI-compatible LLM, deepeval. Each rule is a numbered
> finding.

## The through-line (the one bug wearing different clothes)

> **Something inferred an answer by resemblance when an exact answer was available.**
> The fix is always the same move: **make the model choose the constraint, and make code satisfy it.**

- Semantic search *ranks* by content — it cannot distinguish one document from another (every contract
  has a termination clause). **Document identity must be indexed and pre-filtered, not ranked** (Part 3).
- A corpus-wide question (`multi-12`/`multi-13`: "list every company", "do any two docs share one?") is
  a **`GROUP BY`, not a similarity question** — a ranked retriever cannot answer it at any top-k, because
  a question about the whole corpus has no best-matching chunk. Read the index and aggregate in code (Part 4).
- Don't match filename tokens loosely when the filename has a grammar (EDGAR `COMPANY_DATE-EX-N.N-TYPE`):
  `"sla" in "Tesla"`, exhibit numbers `10.1` indexed as companies. **Parse the structure; match on token
  boundaries; require a party to contain two consecutive letters** (Part 3).

## Eval integrity (the most dangerous defects)

- **A metric that cannot report its own failure rate is not a metric** (#1: "LLM Judge 5.0/5.0" while 19
  of 20 cases crashed — the harness averaged only the completed ones). The summary **leads with its own
  failure count** and prints `❌ RESULTS NOT USABLE` above a 20% failure rate.
- **The judge must not grade its own homework** (#5: the LLM judge defaulted to the same model as the
  generator — a mirror, not a signal; its default was even an embedding model that can't generate). Judge
  ≠ generator, always.
- **Run the error-analysis cross-tab** `retrieval_hit × judge_score` (#6). It's what revealed *generation*,
  not retrieval, was the dominant failure mode — after a whole session optimizing retrieval. The conclusion
  "agentic retrieval is architecturally weaker" was exactly backwards and got the eval-results doc retracted.
- **Fixtures you invented cannot falsify assumptions you hold** (Part 3): entity tests used invented
  fixtures (`Apple_10K.html`) and passed at 100% while the live index had `10.1` as a company. Tests are
  now the **25 real filenames, verbatim**.
- **Use the instrumentation you already have** (#6 meta-lesson): OpenTelemetry, Prometheus, per-stage trace
  timings existed the whole time while debugging happened by `curl` and `grep`.

## Measure the same system

- **Runs must target the same corpus/config** (#2: four Qdrant collections existed — `python-rag-service_hybrid`,
  `python-rag-service_ids`, `python-rag-service_full` (zero entities), `python-rag-service_entities` — and the container was
  hand-pointed at one while `config.py` named another). One canonical collection; strays deleted + tombstoned.
- **Give each arm the same budget** (#4: the agent's `search_corpus` inherited `top_k=3` while classic used
  8 on the same question — comparing 3 chunks against 8 and blaming the architecture).
- **A tool that throws on every call makes the agent measure a broken tool, not an architecture** (#3:
  `search_filtered` defaulted to a paid Voyage reranker with no key and threw every call; the agent burned
  its whole step budget retrying). Empty results return the entity vocabulary so the agent can self-correct.

## The agent contract (read-only tools, budgets, allowlist)

- **The agent's capability surface is the tool registry — allowlist, not denylist.** A tool exists only if
  registered; unknown names are never executed (`test_unknown_tool_is_rejected` — "the loop must never
  invent capabilities").
- **Budgets are explicit and env-overridable:** `AGENT_MAX_STEPS`, `AGENT_TOKEN_BUDGET`,
  `AGENT_TOOL_TIMEOUT_S`. Exhaustion finishes with what was gathered and flags the trace. `finish` is the
  explicit stop signal; there is no unbounded path through the loop.
- **Build side-effect machinery with the first mutating tool, not speculatively.** Adding a read-only tool
  = registry entry + tests + a doc row. A tool with side effects requires argument-schema validation, a
  pre-execution control mode (audit/approval/block), and severity-gated alerting *before* it ships — none
  of which exists today, deliberately.

## Config / model swapping

- **The LLM is hot-swappable (any OpenAI-compatible endpoint, no re-index); the embedder is NOT** — its
  output dimension is baked into the Qdrant collection at ingest. Changing `EMBEDDER_TYPE` means setting
  `EMBEDDING_DIM` to match AND re-indexing.
- **Library dependency direction is one-way:** the app imports the library, never the reverse; the library
  is pip-installed (no `PYTHONPATH`/`sys.path` edits). Heavy optional capabilities live behind extras.
