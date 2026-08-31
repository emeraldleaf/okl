---
description: FastAPI request-path rules — async event loop, middleware order, streaming, config
paths: ["**/main.py", "**/app/**/*.py", "**/backend/**/*.py"]
---

# FastAPI backend (async request path)

> Ported from the RAG service docs/code-review.md — each is a dated, file:line finding.

## The async event loop is shared — never block it

- **No CPU/IO-heavy synchronous work in an async handler** (main.py:1889: synchronous PDF work in an async handler stalled the event loop for all concurrent requests, including in-flight SSE streams). Offload to a thread/executor or a background task.
- **No synchronous network calls inside an async path** (rag_pipeline.py:526: a synchronous `requests.post` to Qdrant inside async `retrieve()` blocked the whole event loop; semantic_cache.py:319: `clear()` uses the blocking `KEYS` command and `clear()`/`get_stats()` run sync Redis calls on the async loop). Use the async client.
- **Don't drive a loop-bound async provider via `asyncio.run()` on executor threads** (document_grader.py:363: broke in the default config and silently disabled CRAG grading).

## Middleware order and auth are security-critical

- **Auth vs CORS ordering** (main.py:567: `APIKeyMiddleware` added after `CORSMiddleware` made it outermost, so CORS-preflight OPTIONS got 401 and blocked all browser clients). Order middleware deliberately; test a browser preflight.
- **A rate-limit tier must not be granted on an unvalidated header** (main.py:527: the higher per-key tier was granted to any request merely carrying an `X-API-Key` header — the key was never validated, so each forged key got its own quota bucket).
- **`slowapi` finds the request parameter by NAME** (main.py:978: `/query/stream` 500'd on every request when rate limiting was on because the parameter named `request` was the Pydantic body). Name the `Request` parameter `request`.

## Streaming must not bypass the validation the non-streaming path runs

- **Scrub/validate before the first token reaches the client** (main.py:1218: `AnswerScrubber` PII redaction was bypassed on `/query/stream` — raw LLM tokens streamed before validation ran). Streaming scrub-before-emit is the rule.
- **Don't reimplement a pipeline per endpoint** (main.py:976: `/query/stream` reimplemented ~300 lines of the `/query` pipeline and drifted — no audit log, no metrics, no OTel span — while config claimed audit covered both). One orchestrator behind both `/query` and `/query/stream`.

## Errors, persistence, admin state

- **Never leak raw exception text to clients** (main.py:1288: raw exception text leaked on both endpoints, bypassing the DEBUG gate the general exception handler implements). Return a generic error + correlation id.
- **Non-essential persistence stays off the critical path** (main.py:928: trace + conversation writes sat unguarded on the request path, so a Postgres/Redis outage turned an already-generated answer into a 500). Make observability writes best-effort.
- **Don't mutate shared pipeline state mid-flight** (main.py:2120: `POST /admin/models` mutated shared pipeline state with no lock, reached into private methods, and left `app.state.llm_provider` stale so metrics/audit reported the wrong model). Guard with a lock; go through the public seam.
- **An advertised parameter that's a silent no-op is a defect** (main.py:1539: `GET /api/search` advertised a `mode` param that was silently ignored).

## Config layering — one settings source

- **Read config through the settings layer, not `os.environ` at import time** (opik_tracer.py:66 and MODEL_PROFILES: `os.getenv` at import time while `config.py` defined the same settings via pydantic-settings, so values set only in `.env` silently left features disabled; MODEL_PROFILES was even keyed on a dev VM's absolute path).
- **One embedding-dimension source of truth** (rag_pipeline.py:288: resolving `EMBEDDING_DIM` via `os.environ.get(..., 768)` bypassed the backend's `settings.EMBEDDING_DIM=1024` and silently built a cache index with the wrong vector dimension). Two parallel pydantic Settings systems with conflicting defaults is the root cause — collapse them.
