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

- `GENERATOR_TOOLS` — tools the generator may run, as `claude -p --allowedTools` takes
  them; default empty, the one-shot generator every section through §4q used. `"Bash(okl
  show:*)"` with `--arms baseline,briefed,indexed` is REPORT §4r's instrument: an `okl` shim
  on the generator's PATH logs each fetch, and the receipt says which lessons each sample
  read. `--tasks evals/heldout_tasks.jsonl` (from `evals/make_heldout_tasks.py`) runs the 24
  held-out rephrasings instead of the eight authored tasks; `--accept-missing-lessons` lets
  such a run start although some briefings lack their governing lesson, and the receipt lists
  them (`preflight_missing`). The gate always reads the task file the run executes.
- `OKL_BRIEF_INTERESTS` — the `--interests` the briefed arm's `okl check` runs with.
  Default empty (unfiltered). Receipts `ab-20260903-1323` through `ab-20261011-2254` ran
  with okl's seven interests set and §4o's run unfiltered; each stamps the value it ran
  with, and `evals/preflight.py` reads the same variable, so the gate checks the briefing
  the run will use.
- `AB_RESULTS_DIR` — where receipts are read and written (default `evals/results/`).
- `GENERATOR_CMD` / `JUDGE_CMD` — default `claude -p --model sonnet` / `--model haiku`.

Before any model call, a live run refuses to start (a dry run skips these) if:

- `evals/preflight.py` fails — some task would not receive the rule it tests: exit 5;
- a task's `defect_node` is not a record in the store: exit 4.

Judge == generator exits 3. A run whose failure rate is above 20% exits 1.

Results land in `evals/results/ab-<timestamp>.json` — commit them; they're the receipts.

The receipt names the commit the tree stood at when the run began (`okl_commit_at_start`)
and at the end (`okl_commit`). The briefed arm renders from this checkout's `src/`, so a
branch switch during a run briefs the later samples with other code; a receipt whose tree
moved carries `working_tree_moved` and is not usable (REPORT §4o is the run that taught
this). Run the harness from a pinned git worktree, never from the checkout other work uses.

Two cheaper checks run with no model at all. `evals/preflight.py` asks whether each task's
governing record reaches its briefing. `evals/probe_rephrase.py` asks the two questions the
A/B cannot: whether that record still reaches the top-12 when the task is rephrased (a
terse ticket, a paraphrase sharing no nouns, a bug report), and how many of the twelve
records a short real prompt returns match more than one subject word. Its output is a
diagnostic receipt, `evals/results/probe-rephrase-<date>.txt`. Its second recall table uses
`evals/heldout_variants.json`, rephrasings written blind from the task text alone (its
`_provenance` key says how), so a retrieval change authored by someone who had read the
probe's own variants is also measured on wording they had not; its six precision prompts
are in `evals/probe_prompts.json`. For a change to the seed packs rather than the code,
`evals/compare_seed_briefings.py --against origin/main` seeds two throwaway stores and
prints, per eval task, the governing record's presence and the ids that left and arrived,
plus the held-out recall and the precision prompts' counts on each side. The probe's
`--hybrid off|rrf|linear` runs the same tables with the semantic arm (REPORT §4q; it refuses
to run hybrid when the model or the vectors are missing rather than fall back silently), and
`evals/hybrid_grid.py` prints the recall rows and precision counts over a grid of cosine lines
and both fusion modes, the receipt the subject line was chosen from. `--rerank` runs the
tables with the cross-encoder second stage (REPORT §4t), and every receipt ends its recall
tables with the median `core.check` latency. `evals/rerank_select.py` and
`evals/embedder_select.py` score local cross-encoders and dense models on the selection set
(the probe's own rephrasings and the authored tasks, never the held-out set), one model per
process; `evals/rerank_spike.py` is the first held-out spike §4t declares. The rephrasings are
hand-written, which is its main bias, and it is not pooled with any A/B.

## Provenance of the originally quoted numbers

An earlier held-fixed A/B of the same design, run on 2026-07-17, produced figures whose
raw artifacts were never checked in, and the decision record that cited them is not in
this repo. They are quarantined in [REPORT §7](REPORT.md#7-provenance-of-the-earlier-numbers):
not reproducible here, and not to be quoted as results. This harness exists so every
number carries a committed, re-runnable receipt. Numbers from runs marked RESULTS NOT
USABLE are never quoted.
