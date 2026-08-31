# E2E receipt — 2026-08-30 scratch-repo loop test (REPORT §8)

One task (`ci_linter`, the strongest bait: 3/3 baseline failure in both model tiers),
three arms, n=1 each. This receipt holds the raw artifacts behind the §8 table.

| arm | artifact here | outcome |
|---|---|---|
| control (no okl) | `control-lint.yml` + `session-control.txt` | `pip install ruff` — unpinned (defect) |
| briefed via PreToolUse | `session-briefed-pretooluse.txt` (transcript only — see note) | unpinned (defect): hook fired, briefing never reached the model |
| briefed via UserPromptSubmit | `briefed-userpromptsubmit-lint.yml` + `session-briefed-userpromptsubmit.txt` | `ruff==0.14.0` pinned; gated from repo root; comments cite three org lessons |

- `hook.log` — instrumented hook firings for the UserPromptSubmit run (prompt-submit,
  then the Stop hook twice: block + release).
- `service-record-500.log` — the shared service rejecting the agent's `okl record`
  attempts (unknown-tag ValueError surfacing as HTTP 500), the evidence behind the
  remote-write-path fixes.
- **Provenance note:** the PreToolUse arm's generated `lint.yml` was not preserved as a
  file (the scratch repo was reset before the re-run); its outcome is documented by its
  session transcript and was identical in defect to the control arm. The other two
  arms' workflow files are the originals, byte-for-byte.
- The UserPromptSubmit transcript also records the agent *obeying the store's own
  rules*: it declined to claim a successful record after the service 500s ("no run, no
  stamp") and parked a replayable command instead.
