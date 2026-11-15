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

**What a session loaded and its effort (Claude Code 2.1.302, found on #451):** each saved session's jsonl has an `api-request` record whose `params.output_config.effort` is the effort actually sent, and `api-request-blob` records hold the exact system prompt and user-context block. Test for CLAUDE.md with the string `Contents of /…/CLAUDE.md`; the interactive session shows it, so the detector works. The user-entry `entrypoint` shows env inheritance: `claude-vscode` was inherited from the parent; under sandbox.clean_env it is `sdk-cli`. Findings, 2026-11-14:
- `-p --restricted` sessions load no CLAUDE.md and no user settings, and ran at effort medium: 387 pick sessions and §4bf's 108+108+6.
- `-p` without `--restricted` reads ~/.claude/settings.json (`effortLevel: xhigh`, plus modelSettings), so the A/B harness's Sonnet generator ran at xhigh (2026-10-22/23/29 samples).
- `CLAUDE_EFFORT` is exported to hooks and Bash and never read back; the input variable is `CLAUDE_CODE_EFFORT_LEVEL`.
- A checkout-run session gets `gitStatus`: the branch, the last five commit subjects and untracked names.
- §4ba/§4bb ran from `~/.claude/projects/-Users-joshuadell-Dev-okl-wt-render/` (branches review-e2e and when-lines). The §4bb when-line WRITER sessions are there too (prompt starts "Below are lessons a software team keeps"; 17 on 2026-11-11, 15 on 2026-11-12).
- §4bf: `-private-var-folders-...-T-okl-4bf-<run>-breaker-<N>/` (run k7ezkwzs: 108 breakers, 108 judges in the room dir). §4ag/§4ai census judges: `...-T-okl-judge-<id>-repo/` (a linked worktree, so they read git status).
- Git status is the full short status (deleted and modified lines too), so hidden files' names appear in it.
- Each tool_use block is saved twice (its assistant event and a later api-request-blob): count by tool_use id, or every per-call tally doubles (harness-transcripts-4bf's outside_worktree_calls 38 = 19 calls).
- Breakers sometimes type a mangled own-tree path (`_` as `-`, or `-T-okl-...` for `/T/okl-...`); `--restricted` refuses it as "outside" the working directory, so a path matcher must map it back before calling it an escape. Refused Bash/Write calls ("No such tool available") are saved too.
- From #451 the runners' rooms are `okl-w-<id>/t<slot>` (no lesson or experiment in the name).

**How to apply:** when a REPORT claims something about every session, re-count it with a short script over these dirs. Ask for that script's output to be committed as a receipt, since the transcripts are local and will be swept. Related: [[review-findings-log]].

§4az's review sessions are saved under `~/.claude/projects/*okl-4aw-*`, and each sub-agent prompt names `review-lessons/<id>.md`, so the review's own picks can be recovered there; the receipt (`review-e2e-20261111-1543.json`) records only a count of sub-agents (found on #440: the right lesson reached the sub-agents on #115 3 of 4, #198 3 of 3, and 0 on #168, #196 and #309; heuristic and uncommitted, not citable until a receipt script commits it).
