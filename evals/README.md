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
python3 evals/ab_harness.py                    # full run (16 generations + 16 judgments)
GENERATOR_CMD="..." JUDGE_CMD="..." ...        # any CLI that takes a prompt on stdin
```

Results land in `evals/results/ab-<timestamp>.json` — commit them; they're the receipts.

## Provenance of the originally quoted numbers

The 50%→6% / 75%→8% figures cited in the sixth-surface decision record came from a
held-fixed A/B with the same design run on 2026-07-17, whose raw artifacts were not
checked in. Treat those as *recorded results with documented controls, not currently
reproducible*. This harness exists so every future number carries a committed,
re-runnable receipt. Numbers from runs marked RESULTS NOT USABLE are never quoted.
