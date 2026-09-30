# The A/B harness — re-runnable defect-reproduction measurement

**The claim this makes checkable:** injecting the `okl check` briefing before a task
reduces how often generated code reproduces known defect classes.

## Method (held-fixed A/B)

Each task in `tasks.jsonl` is defect bait: a realistic request shaped to invite one
specific stored lesson's mistake (`defect_node` names the store node). Every task runs
twice with the same generator; the ONLY difference between arms is the briefing:

- **baseline** — the task alone
- **briefed** — `okl check --task <task>` output prepended, live from the store

The outcome is judged **blind**: the judge sees the task, the code, and the defect
signal — never which arm produced it — and answers strict JSON. The judge must be a
different model from the generator; the harness refuses to run otherwise.

## Integrity rules (stored lessons, obeyed here)

- **Failure count first** (`qz_judge_crash`): the report leads with its own failure
  rate and prints RESULTS NOT USABLE above 20% — before any score.
- **Judge ≠ generator** (`qz_judge_self`): enforced at startup, exit 3.
- **Equal budgets** (`qz_unequal_budget`): both arms get identical prompts, timeouts,
  and models; the briefing is the sole variable.
- **Clean room**: generator/judge subprocesses run in a temp cwd so this repo's own
  hooks can't inject context into the experiment (discovered the hard way: a smoke
  call in the repo cwd came back answering our Stop hook instead of the question).
- **Briefed arm fails closed**: if `okl check` errors, that run counts as a harness
  failure — it must never silently degrade into a second baseline.

## Usage

```bash
python3 evals/ab_harness.py --dry-run          # list tasks, no calls
python3 evals/ab_harness.py --limit 2          # smoke run
python3 evals/ab_harness.py --samples 3        # citable run (8 tasks x 2 arms x 3 = 48 generations + 48 judgments)
GENERATOR_CMD="..." JUDGE_CMD="..." ...        # any CLI that takes a prompt on stdin
```

A single sample per (task, arm) is noisy; quote only `--samples 3` runs. The harness
reads these variables:

- `OKL_BRIEF_INTERESTS` — the `--interests` the briefed arm's `okl check` runs with.
  Default empty (unfiltered), which is what every run in the report used; it is stamped
  into the receipt.
- `AB_RESULTS_DIR` — where receipts are read and written (default `evals/results/`).
- `GENERATOR_CMD` / `JUDGE_CMD` — default `claude -p --model sonnet` / `--model haiku`.

Before any model call, a live run refuses to start (a dry run skips these) if:

- `evals/preflight.py` fails — some task would not receive the rule it tests: exit 5;
- a task's `defect_node` is not a record in the store: exit 4.

Judge == generator exits 3. A run whose failure rate is above 20% exits 1.

Results land in `evals/results/ab-<timestamp>.json` — commit them; they're the receipts.

## Provenance of the originally quoted numbers

An earlier held-fixed A/B of the same design, run on 2026-07-17, produced figures whose
raw artifacts were never checked in, and the decision record that cited them is not in
this repo. They are quarantined in [REPORT §7](REPORT.md#7-provenance-of-the-earlier-numbers):
not reproducible here, and not to be quoted as results. This harness exists so every
number carries a committed, re-runnable receipt. Numbers from runs marked RESULTS NOT
USABLE are never quoted.
