---
name: reference-harness-transcripts
description: Where drift_mutate's breaker and judge sessions are saved, and what they do not contain, for checking REPORT claims made "from the transcripts"
metadata:
  type: reference
---

The headless `claude -p` sessions that `evals/drift_mutate.py` runs are saved by Claude Code under
`~/.claude/projects/`. The directory name is the cwd with `/` and `_` turned into `-`:
- breakers: `-private-var-folders-...-T-okl-mutate-<run>-breaker-<slot>-<lesson[:16]>/` (one session per patch)
- first-pass judges: `-private-var-folders-...-T-okl-mutate-<run>/`. Its cwd is the run's scratch room (it holds the breaker worktrees), not an empty directory.
- re-judges: `...-T-okl-rejudge-<id>/`. Its cwd is an empty mkdtemp.
- Known runs: §4af = `vqivxk4v` (78 breakers), re-judge `13xnfg38` (2026-10-31). §4ah re-run = `cefb1r8y` (54), re-judge `fnt18zq9` (2026-11-01).

What they lack:
- A judge killed at the 300 s time-out saves only the user prompt: no assistant text, no thinking. Time-outs leave no evidence of what the judge was doing.
- The breaker's git status sits in a `session_context` attachment (`gitStatus`), and Claude Code cuts it at 2,000 characters. With `--blind`'s 1,000+ deleted files, only the first ~44 names appear, in alphabetical order through `evals/results/bench-*`.

**How to apply:** when a REPORT claims something about every session, re-count it with a short script over these dirs. Ask for that script's output to be committed as a receipt, since the transcripts are local and will be swept. Related: [[review-findings-log]].
