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

Eval scripts that call `claude -p` with cwd=REPO (pick_fix, plan_reach, when_lines...) save each call under `~/.claude/projects/<the checkout's absolute path, with / and _ turned into ->/*.jsonl` (the rule above; a worktree or another checkout has its own directory). Select files by mtime window, take the first `type: user` timestamp (UTC), the `message.model`, and classify by the prompt's first words. Then compare with `git log --format=%cI` to check "written before any call", "amendment before any row" and the real call counts (#434: 162 Sonnet picks against the 58 reported).

**How to apply:** when a REPORT claims something about every session, re-count it with a short script over these dirs. Ask for that script's output to be committed as a receipt, since the transcripts are local and will be swept. Related: [[review-findings-log]].

§4az's review sessions are saved under `~/.claude/projects/*okl-4aw-*`, and each sub-agent prompt names `review-lessons/<id>.md`, so the review's own picks can be recovered there; the receipt (`review-e2e-20261111-1543.json`) records only a count of sub-agents (found on #440: the right lesson reached the sub-agents on #115 3 of 4, #198 3 of 3, and 0 on #168, #196 and #309; heuristic and uncommitted, not citable until a receipt script commits it).
