# E2E receipt — 2026-09-26 fresh-install loop test (REPORT §10)

The whole loop, from a wheel built off `main` at `e3be24c`, in a scratch repo that had never
seen okl — not this repo's dogfood install. One bait task (`ci_linter`, the strongest in
`evals/tasks.jsonl`), two arms, n=1 each; then the write side and the CI side by hand. This
is a delivery check, not a measurement: it asks whether each surface works for a new user,
not how much the briefing helps (§4 measures that).

## What ran

| step | evidence here | outcome |
|---|---|---|
| `pipx`-style install from the wheel, `okl init --interests python,method,security`, `okl seed` | (setup script in the session log) | hooks installed and registered, CI verifier installed, guidance printed |
| deterministic pre-flight: does the briefing for the task carry the governing rule? | (run before any model call) | yes: "Unpinned linter/formatter in CI retro-fails…" present, hook delivers it with exit 0 |
| control session (no okl) | `session-control.txt`, `transcript-control.jsonl` | `run: ruff check .` — no install step, no pin (the defect) |
| briefed session | `transcript-briefed.jsonl`, `briefed-lint.yml` | `pip install ruff==0.9.0`, `ruff check app/`, rationale citing two stored lessons; Stop hook fired, answered honestly ("learned nothing durable") |
| record → verify with evidence → export → commit → `okl drift --gate --snapshot` | `okl-drift-scratch.json` | gate 0 after verify; 1 after a governed edit committed later |
| the shipped `okl-verify.yml` drift step, run as its own shell with no store env | (session log) | exit 0 from the committed snapshot |
| `okl doctor`, `okl init` again, `okl init --uninstall --dry-run` | (session log) | 0 / "already current" ×5, nothing clobbered / dry run changed nothing |
| `OKL_DISABLED_HOOKS=briefing,encode` in a live session (1 haiku call) | `transcript-envtest.jsonl`, `session-envtest.txt` | neither hook fired: hooks see the caller's environment |

`command.txt` holds the exact `claude -p` invocation. Budget declared before the run: 4 model
calls; 3 used (sonnet ×2, haiku ×1). Two earlier attempts failed before any model was called
(macOS has no `timeout`; `claude -p` wants the prompt on stdin), and are not receipts.

## Findings

**1. In `claude -p`, a blocked Stop replaces the printed answer.** Print mode emits only the
final assistant message. The Stop hook blocked the first stop, the agent answered "what did
we learn?", and that answer is what `session-briefed.txt` contains; the YAML the user asked
for exists only in the transcript. Nothing documented lets a hook tell print mode from an
interactive session (checked against the hooks docs; the transcript's `entrypoint` field is
inherited from the parent environment and cannot be trusted). Resolution: headless callers
set `OKL_DISABLED_HOOKS=encode`, which this run proved works; the README says so. The
harness was already unaffected (it runs generators in a clean room).

**2. Pack recommendation is stack-keyed, so a Python repo is pointed at 2 records** (#54).
`okl init` marked only `geospatial-eval-defects` as matching; the pack holding the very rule
this run shows working went unmarked, because it names the stack it was found on.

**3. Instrumentation, not product:** an `OKL_BIN` wrapper meant to log the hook's `okl`
calls was never invoked inside the session, although the same variable mechanism carried
`OKL_DISABLED_HOOKS` in the next session and the wrapper works by hand. Cause unconfirmed.
The transcript's `hook_success` attachment, which holds the injected briefing verbatim, is
the delivery evidence instead — and is better evidence than a wrapper log.

## Provenance notes

- `briefed-lint.yml` is the briefed session's two steps as produced, wrapped by hand in the
  minimal job a user would put them in (the task asked for steps only); the wrapping is
  the file's header comment. The loop's governed-file edit appended a comment to that file.
- The scratch repos live under `e2e/` (gitignored); the store there holds the two seeded
  packs plus the one rule recorded during the loop.
- The August run (§8, `e2e-20260830/`) used the shared HTTP service; this run used a local
  SQLite store, which is what a first install gets.
