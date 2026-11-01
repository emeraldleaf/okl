# Verification: don't let a step grade itself

Part of okl's documentation; the [README](../README.md) is the short version.

A step reporting "I succeeded" and the work actually being done are two different facts,
and a loop that accepts the first one compounds garbage confidently. (The founding
receipt: a pipeline step that was supposed to write 238 files failed on every one,
swallowed the errors, and exited 0 — everything downstream ran happily on an empty
folder.) Two clarifications that stop the common misreadings:

- **The grader is usually `ls`, not an LLM.** Checking the work means observing the
  work product — files exist, counts match, tests ran, the output contains the success
  signal you named. Boring, deterministic checks. A second model only enters when the
  verify signal is itself a model's *judgment* (LLM-as-judge) — there, and only there,
  the judge must differ from the generator.
- **Not every step — every claim the loop acts on.** Verify at decision boundaries
  (mark done, merge, deploy), cheap invariants in between.

`okl` applies this to its own knowledge in four escalating rungs:

1. **Assertion is refused at the CLI.** `okl record --verified` (a bare claim, no
   evidence) exits 2 and points at `okl verify`. Two doors stay open: `okl seed` imports
   historical, already-verified stamps, and the shared service's API still accepts
   `verified: true` on a record. What closes the loop is the drift gate: the live-store
   scan (and so the pre-push hook) reports a stamp with no `okl verify` evidence as drift,
   CI's snapshot reader refuses a snapshot that carries one (exit 2), and the briefing
   marks it *UNPROVEN* when it governs files here and *UNCHECKED* otherwise.
2. **Observed check with a stored trail** — `okl verify <id> --run "pytest -q"
   --expect "passed"` runs the check itself, reads the real outcome, requires the
   positive signal (exit 0 alone can't self-certify), and stores command + result +
   timestamp on the node (`verified_by`). Every stamp is inspectable and re-runnable;
   a lazy check becomes a visible artifact instead of an invisible belief.
3. **An independent actor re-checks** — with `okl init --ci` (or your own CI), CI runs
   `okl drift --gate` and the method gates on every PR: a mechanical grader with no stake
   in the original claim. The default pre-push hook runs the same gate locally, but it is
   per-clone and `--no-verify` skips it, so it is an early warning, not an independent grader. Nothing
   shipped writes `VERIFIED_ON` receipts by default; a gate script can emit one with
   `okl link <gate_id> VERIFIED_ON <defect_id>` when it watches a gate prove itself.
4. **Time attacks every stamp** — `drift` re-grades verifications the moment governed
   files change after their last verification; a record given `--ttl-days` decays into `STALE` when
   nobody re-earns it (there is no TTL by default);
   and `okl metric` scores the whole system on outcomes — defect classes that came
   back — the one number it can't flatter itself on. It earns that by stating its own
   coverage (how many defects have a gate it could speak for) and by counting
   recurrences with no gate separately: lessons written down that came back anyway.
   Until issue #31 it printed a bare "0 ✓" while the store held three recurrences.
