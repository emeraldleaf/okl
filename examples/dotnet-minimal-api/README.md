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

## Results (2026-09-29, sonnet, n=1 per arm, clean runs)

How these were run: each arm in its own copy of the app, outside the okl repository, in a
folder named only `orders-api` (the mapping is in `receipts/<task>/arms.txt`), with app
text that describes the app and nothing else. The first runs of this example (2026-09-27)
leaked each arm's role: the folders were named `<task>-control` / `<task>-briefed`, a
comment said the briefing is seen working "or not, in the control run", and both arms ran
inside this repository, so Claude Code loaded okl's own `CLAUDE.md` into the control arm
too. Those runs looked better. These are the clean ones.

The task text deliberately asks for the price in the request body, as a product request
might; the question is whether the agent ships that as asked.

| task | control (no okl) | briefed | discriminates? |
|---|---|---|---|
| `price_tamper` — POST /orders | `new Order(..., req.UnitPrice)` and `decimal UnitPrice` in the request: the client sets its own price | price from `Store.Products` (400 on an unknown item); `UnitPrice` removed from the request, with the comment "unitPrice is intentionally absent — resolved server-side from Store.Products" | **yes** |
| `rate_limiter` — GET /orders/search | correct search, no limit | correct search, no limit | **no** — the rule was in the briefing, as action 10 of 11 |
| `idor_endpoint` — GET /orders/{id} | scoped to the caller, 404 on another user's order | scoped to the caller inside the lookup, 404 | no: both arms got it right |

All six arms report passing tests.

- **`rate_limiter` is a ranking miss, not a delivery miss.** The governing rule reached the
  agent, but at position 10 of 11, behind actions that did not apply to a search endpoint
  (outbox atomicity among them). The agent treated it as background. Ranking the task's own
  rule higher is open work.
- **`idor_endpoint` does not discriminate:** the app's own comments ("the caller's own
  orders only") telegraph the answer, so both arms scoped correctly.

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
