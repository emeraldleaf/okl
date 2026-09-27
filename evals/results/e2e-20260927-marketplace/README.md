# E2E receipt — 2026-09-27 marketplace install, and the block that was not a block

Two things were tested here: that the plugin installs from the GitHub marketplace and
delivers its hook, and — found by accident, then isolated on purpose — that a hook
exiting 2 can still let the prompt through.

## 1. Marketplace install (0.6.0)

In Claude Code: `/plugin marketplace add emeraldleaf/okl`, then `/plugin install okl@okl`.
Installed to `~/.claude/plugins/cache/okl/okl/0.6.0/`. Then one haiku call in the scratch
repo from `e2e-20260926/`:

```
printf '%s' "Reply with exactly the single word: ok" \
  | OKL_DISABLED_HOOKS=encode claude -p --model haiku --allowedTools ""
```

| evidence | outcome |
|---|---|
| `transcript.jsonl` | the hook that fired is the marketplace copy: `…/plugins/cache/okl/okl/0.6.0/hooks/userpromptsubmit-okl-check.sh` — the manifest's `hooks` field is what loads it, so it stays |
| `doctor-in-okl-repo.txt` | in this repo (which has its own project hooks) `okl doctor` reported **wired twice** and exited 1 — the double-wiring check works against a real marketplace install |
| `session.txt` | `ok` — but see below: the prompt should not have gone through |

## 2. The finding: exit 2 was downgraded to a warning

The scratch repo's `.okl/config.json` pinned `okl_bin` into a venv deleted the day before.
The hook ran it anyway; bash wrote `…/okl: No such file or directory` into the hook's
stderr; the hook exited 2. `transcript.jsonl` shows what Claude Code did with that:

```
"type": "hook_non_blocking_error" … "stderr": "Hook script appears to be missing — …
exited 2 with: OKL CHECK DID NOT RUN — blocking this prompt. …
okl said: …/hooks/userpromptsubmit-okl-check.sh: line 83: …/e2e-20260926-venv/bin/okl: No such file or directory
… Treating as non-blocking."
```

The hook script was not missing — it ran, and said so. Claude Code read the ENOENT phrase
in its stderr as "the hook script is missing" and treated the block as a configuration
error. Fail-closed had become fail-open, with a message that looked like a block.

### Isolating it (`claude -p --plugin-dir`, haiku, `OKL_DISABLED_HOOKS=encode`)

| probe | stderr | result |
|---|---|---|
| minimal plugin hook: `exit 2`, nothing on stderr | — | **blocked**: empty stdout, no transcript |
| project hook: `exit 0` | — | `ok`, transcript (the control for that signature) |
| okl's hook with `OKL_BIN=/nonexistent/okl` — path quoted, unquoted, diagnostics reworded (`transcript-probe-last.jsonl` is the reworded one) | carries `No such file or directory` | `hook_non_blocking_error`, prompt proceeds |

A plugin hook can block. The shell's ENOENT text in stderr is what defeats it.

### The fix, and the A/B

Both hooks now use a resolver layer only if `command -v` says it runs, so a dead pin is
skipped rather than executed, and the prompt hook filters that phrase out of anything it
relays. Same scratch repo (`.okl/config.json` pinning `/nonexistent/venv/bin/okl`),
`PATH=/usr/bin:/bin` so nothing else resolves, one call each:

| hook | result |
|---|---|
| `main`'s hook (`transcript-control-main-hook.jsonl`) | `hook_non_blocking_error`, "Hook script appears to be missing", `ok` printed |
| this branch's hook | **empty stdout, no transcript** — blocked |

And with okl reachable further down the chain (the normal case for a stale pin), the dead
pin is skipped and the briefing arrives (`hook_success`, seen in the same probe series).

## What is still open

A clean marketplace re-run needs the fix on `main`, since the marketplace serves `main`.
Until then the fixed hook has only been exercised through `--plugin-dir`, which loads the
same `hooks/hooks.json` by the same mechanism.
