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
| `price_tamper` — POST /orders | `unit_price` taken from the request body | `unit_price` **also** taken from the body; the briefed arm protected `owner` (set from the auth token, never the body) but not the price | **no** — a miss: the governing rule was in the briefing |
| `rate_limiter` — GET /orders/search | correct search, no limit | correct search, no limit | **no** — the rule was in the briefing, as action 10 of 12 |
| `idor_endpoint` — GET /orders/{id} | scoped to the caller, **403** on another user's order | scoped to the caller, **404** — the lesson's exact guidance, so a probe cannot confirm the row exists | partly: both scoped; only the briefed arm hid the row's existence |

- **`price_tamper` is an application miss.** The rule ("server-controlled fields trusted
  from the client body") was the second action in the briefing. The agent applied it to
  the ownership field and not to the price. The same task discriminated on the .NET
  example in its clean run.
- **`rate_limiter` is a ranking miss:** the rule reached the agent near the end of the
  list, behind actions that did not apply.

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
