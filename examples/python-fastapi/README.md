# okl on a Python service — `orders-api`

A small FastAPI service, three realistic tasks, and a runner that gives each task to a
coding agent twice: once in a copy with no okl, once in a copy where `okl init` ran and
the matching seed packs were imported. The diffs, the agent's final messages and the exact
briefing each briefed arm received are kept under `receipts/` for a person to read.

```bash
pipx install observed-knowledge-ledger      # the okl CLI
examples/python-fastapi/run_demo.sh         # 3 tasks x 2 arms = 6 model calls (sonnet)
examples/python-fastapi/run_demo.sh idor_endpoint   # one task
```

The runner writes only under `e2e/` (gitignored) and `receipts/`. It sets
`OKL_DISABLED_HOOKS=encode` because it drives `claude -p`, where a blocked stop would
replace the printed answer (README, "Turning parts off").

## Results (2026-09-27, sonnet, n=1 per arm)

The defect classes come from lessons recorded on a .NET platform; the briefing carried
them into a Python service that had never seen them. Read the diffs before the table.

| task | control (no okl) | briefed | discriminates? |
|---|---|---|---|
| `price_tamper` — POST /orders | took `unit_price` from the request body: **the defect** | price from the server-side `PRODUCTS` catalogue, 422 on an unknown item | **yes** |
| `rate_limiter` — GET /orders/search | correct search, no limit | the recorded policy verbatim: fixed window 30 req / 10 s per user, 429, no queueing, plus four tests | **yes** |
| `idor_endpoint` — GET /orders/{id} | scoped to the caller (403 on another user's order) | scoped to the caller, **404** on another user's order — the lesson's exact guidance | no: the control did not reproduce |

Two things the table cannot say on its own:

- **`idor_endpoint` did not discriminate, and the bait is why.** This app's own docstrings
  ("the caller's own orders only"; "order ids are guessable on purpose — that is what an
  ownership check exists to make harmless") telegraph the answer, so the control scoped
  correctly without help. The eval set's IDOR task reads baseline 0/3 in every recent run
  too (REPORT §4h). What the briefing changed here is the *shape* of the fix — 404, not 403,
  so a probe cannot confirm that the row exists — which is the recorded lesson, applied.
- **The briefed rate limiter is in-memory**, which a *different* stored rule warns weakens
  to N× the limit at N instances. That rule did not rank for this task's wording and was
  not in the briefing; for a single-process demo it is the right size, but it shows the
  briefing is a selection, not the whole store.

n=1 per arm is a demonstration, not a measurement; the measurement is `evals/REPORT.md`.

## What is in `receipts/<task>/`

- `briefing.md` — the briefing the briefed arm received, captured before the model call
- `diff-control.patch`, `diff-briefed.patch` — what each arm changed
- `session-control.txt`, `session-briefed.txt` — each arm's final message

## Tasks

`tasks.jsonl` names each task's governing record (`defect_node`, an id in the bundled seed
packs) and the signal a reader checks the diff for. To add a task, add a line and run the
pre-flight in the runner: it keeps the briefing as a receipt, so a task whose governing
record never reaches the briefing is visible before a model call is spent.
