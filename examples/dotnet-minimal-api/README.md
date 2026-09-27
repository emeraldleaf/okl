# okl on a .NET service — `orders-api`

A small ASP.NET minimal API, three realistic tasks, and a runner that gives each task to a
coding agent twice: once in a copy with no okl, once in a copy where `okl init` ran and
the .NET seed packs were imported. The diffs, the agent's final messages and the exact
briefing each briefed arm received are kept under `receipts/` for a person to read.

This is the stack most of the bundled lessons came from (a .NET platform: 109 records
across four packs), so it is where the briefing has the most to say — and the Python
example next door shows the same lessons crossing into a stack they were not found on.

```bash
pipx install observed-knowledge-ledger          # the okl CLI
examples/dotnet-minimal-api/run_demo.sh         # 3 tasks x 2 arms = 6 model calls (sonnet)
examples/dotnet-minimal-api/run_demo.sh idor_endpoint   # one task
```

Requires the .NET SDK (`dotnet`). The runner writes only under `e2e/` (gitignored) and
`receipts/`. It sets `OKL_DISABLED_HOOKS=encode` because it drives `claude -p`, where a
blocked stop would replace the printed answer (README, "Turning parts off").

## Results (2026-09-27, sonnet, n=1 per arm)

The same three tasks as the Python example, on the stack the lessons were found on. All
six arms report passing tests. Read the diffs before the table.

| task | control (no okl) | briefed | discriminates? |
|---|---|---|---|
| `price_tamper` — POST /orders | `new Order(..., req.UnitPrice)`: the price comes from the client body, **the defect** | price from `Store.Products`, 404 on an unknown item; comment: "Price is always sourced from the catalog — never from the client body" | **yes** |
| `rate_limiter` — GET /orders/search | correct search, no limit | `AddFixedWindowLimiter("search-limit")`: 30 permits / 10 s, `QueueLimit = 0`, 429, applied only to the search endpoint — the recorded policy in the framework's own API, with a configurable window so the test does not send 30 requests | **yes** |
| `idor_endpoint` — GET /orders/{id} | scoped to the caller, `403` on another user's order | ownership predicate inside the lookup, `404` on another user's order — the lesson's exact guidance | no: the control did not reproduce |

Same two caveats as the Python example, and they hold here too:

- **`idor_endpoint` did not discriminate, and the bait is why.** The app's own comments
  ("the caller's own orders only"; "order ids are guessable on purpose") telegraph the
  answer, so the control scoped correctly without help. What the briefing changed is the
  *shape*: the ownership check moved into the lookup and the miss became a 404, so a probe
  cannot confirm that the row exists — which is the recorded lesson, applied.
- **The briefed rate limiter is in-process**, which a different stored rule warns weakens
  to N× the limit at N instances. That rule did not rank for this task's wording and was
  not in the briefing; for a single-instance demo it is the right size, but it shows the
  briefing is a selection, not the whole store.

n=1 per arm is a demonstration, not a measurement; the measurement is `evals/REPORT.md`.

## What is in `receipts/<task>/`

- `briefing.md` — the briefing the briefed arm received, captured before the model call
- `diff-control.patch`, `diff-briefed.patch` — what each arm changed
- `session-control.txt`, `session-briefed.txt` — each arm's final message

## Tasks

`tasks.jsonl` names each task's governing record (`defect_node`, an id in the bundled seed
packs) and the signal a reader checks the diff for. The runner keeps each briefing as a
receipt, so a task whose governing record never reaches the briefing is visible before a
model call is spent.
