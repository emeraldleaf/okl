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

## Results

_Pending: the runs land here with the same table as the Python example._

## What is in `receipts/<task>/`

- `briefing.md` — the briefing the briefed arm received, captured before the model call
- `diff-control.patch`, `diff-briefed.patch` — what each arm changed
- `session-control.txt`, `session-briefed.txt` — each arm's final message

## Tasks

`tasks.jsonl` names each task's governing record (`defect_node`, an id in the bundled seed
packs) and the signal a reader checks the diff for. The runner keeps each briefing as a
receipt, so a task whose governing record never reaches the briefing is visible before a
model call is spent.
