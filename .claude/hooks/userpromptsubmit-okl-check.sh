#!/usr/bin/env bash
# UserPromptSubmit hook — inject the org's relevant lessons into the model's context
# BEFORE it starts the task. This event is the only correct one for delivery: its stdout
# (exit 0) is added to Claude's context, and its stdin carries the actual prompt text, so
# the briefing is retrieved for the task the user really asked for.
#
# (The earlier PreToolUse version fired on every edit and printed the briefing to a channel
# the model never sees — PreToolUse exit-0 stdout goes to the transcript only. Discovered by
# an end-to-end test: hook fired, briefing correct, defect reproduced anyway.)
#
# FAILS CLOSED via exit 2: if the knowledge layer is unreachable, the prompt is blocked
# rather than letting the agent proceed blind. A check that reports "clean" while broken is
# worse than no check.
set -uo pipefail

# Anchor to the project. A hook runs in the session's CURRENT directory, and a `cd` in any
# command moves it; from outside the project, okl finds no config and the hook blocked
# every prompt as "unreachable" until the session was restarted. Claude Code sets
# CLAUDE_PROJECT_DIR for every hook; without it, stay where we are.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "$CLAUDE_PROJECT_DIR" ]; then
  if ! cd "$CLAUDE_PROJECT_DIR" 2>/dev/null; then
    # Continuing from the drifted directory is the failure this block exists to prevent.
    echo "OKL CHECK DID NOT RUN — cannot enter the project directory $CLAUDE_PROJECT_DIR, so" >&2
    echo "a briefing from here would read the wrong configuration. Blocking this prompt." >&2
    exit 2
  fi
fi

# Resolve how to invoke okl (env → pinned config → PATH → python3 -m okl); hooks run in
# whatever environment the harness spawns, which often lacks the venv/pipx bin dir.
resolve_okl() {
  if [ -n "${OKL_BIN:-}" ]; then printf '%s' "$OKL_BIN"; return 0; fi
  local d="$PWD"
  while [ "$d" != "/" ]; do
    if [ -f "$d/.okl/config.json" ]; then
      local bin
      bin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("okl_bin") or "")' \
            "$d/.okl/config.json" 2>/dev/null || true)
      if [ -n "$bin" ]; then printf '%s' "$bin"; return 0; fi
      break
    fi
    d=$(dirname "$d")
  done
  if command -v okl >/dev/null 2>&1; then printf '%s' "okl"; return 0; fi
  if python3 -c "import okl" >/dev/null 2>&1; then printf '%s' "python3 -m okl"; return 0; fi
  return 1
}

if ! OKL=$(resolve_okl); then
  [ "${OKL_OFFLINE:-0}" = "1" ] && exit 0
  echo "okl NOT FOUND — blocking (a check that can't run must not pass as clean)." >&2
  echo "Install it: pip install observed-knowledge-ledger. NOT 'pip install okl' — PyPI refuses that" >&2
  echo "name as confusable, so it fails and looks like the tool does not exist." >&2
  echo "Or set OKL_BIN, or re-run 'okl init' from a shell where okl works (that pins okl_bin" >&2
  echo "into .okl/config.json). OKL_OFFLINE=1 proceeds without the layer." >&2
  exit 2
fi

# The task is the prompt itself (stdin JSON: {"prompt": "..."}); OKL_TASK overrides;
# last-commit-message is only the fallback of last resort.
payload=$(cat 2>/dev/null || true)
prompt=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    print((json.load(sys.stdin).get("prompt") or "").strip()[:2000])
except Exception:
    print("")
' 2>/dev/null || true)
TASK="${OKL_TASK:-${prompt:-$(git log -1 --pretty=%s 2>/dev/null || echo 'general work')}}"

# $OKL unquoted on purpose: it may be a command + args ("python3 -m okl").
# okl's stderr is kept: it says WHY a check did not run (unreachable, refused, not
# configured), and discarding it turned every refusal into a misreported outage.
# No guessable fallback path: a fixed name under /tmp could be pre-planted as a symlink by
# another local user. Without a private temp file the reason is lost, not the check.
errf=$(mktemp 2>/dev/null) || errf=""
if out=$($OKL check --task "$TASK" --format agent 2>"${errf:-/dev/null}"); then
  [ -n "$errf" ] && rm -f "$errf"
  printf '%s\n' "$out"      # stdout → the model's context
  exit 0
fi
why=""
if [ -n "$errf" ]; then why=$(head -c 1500 "$errf" 2>/dev/null); rm -f "$errf"; fi

if [ "${OKL_OFFLINE:-0}" = "1" ]; then
  echo "OKL offline (OKL_OFFLINE=1 acknowledged) — proceeding without the layer." >&2
  exit 0
fi
echo "OKL CHECK DID NOT RUN — blocking this prompt. A check that reports 'clean' while broken is worse than no check." >&2
echo "okl said: ${why:-(nothing — it exited non-zero without a reason)}" >&2
echo "Ran from: $PWD. Fix the cause above, or start the session with OKL_OFFLINE=1 to proceed without the layer." >&2
exit 2
