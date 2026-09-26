#!/usr/bin/env bash
# okl-fingerprint: sha256:4810245df77ba0c1966372c8c399eae745da7187b911f2e453498a3d35d8b23c
# Stop hook — the write-side mechanical catch for the encoding loop.
#
# The read side (okl check) is enforced by the PreToolUse hook; nothing enforced the WRITE
# side, so a session could end without recording what it learned ("a merged fix without the
# rule is a half-finished job"). This hook asks the question at the ship moment, once:
# if the session changed the working tree, block the first stop (exit 2) with a prompt to
# either `okl record` the lesson or state that there is none. It never fires twice in one
# session (marker file) and never loops (stop_hook_active guard).
set -uo pipefail

# Anchor to the project. A hook runs in the session's CURRENT directory, and a `cd` in any
# command moves it; from outside the project, okl finds no config and the hook blocked
# every prompt as "unreachable" until the session was restarted. Claude Code sets
# CLAUDE_PROJECT_DIR for every hook; without it, stay where we are.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "$CLAUDE_PROJECT_DIR" ]; then
  if ! cd "$CLAUDE_PROJECT_DIR" 2>/dev/null; then
    # Continuing from the drifted directory is the failure this block exists to prevent.
    echo "okl encode reminder skipped — cannot enter the project directory $CLAUDE_PROJECT_DIR." >&2
    exit 0   # a reminder: never block ending the session over it
  fi
fi

# Switched off by name: OKL_DISABLED_HOOKS=briefing,encode. For running beside tools whose
# hooks already cover the same moment, or for debugging. Turning off the end-of-session question is a choice
# the operator makes explicitly, never a fallback the hook takes on its own.
case ",${OKL_DISABLED_HOOKS:-}," in *,encode,*) exit 0 ;; esac

# Same resolver as pretooluse-okl-check.sh (env → pinned config → PATH → python3 -m okl);
# the reminder is best-effort, so an unresolvable okl silently disables it rather than blocking.
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

OKL=$(resolve_okl) || exit 0

payload=$(cat 2>/dev/null || true)
parsed=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
print(d.get("session_id", ""))
print("true" if d.get("stop_hook_active") else "false")
' 2>/dev/null) || parsed=""
session_id=$(printf '%s\n' "$parsed" | sed -n 1p)
stop_hook_active=$(printf '%s\n' "$parsed" | sed -n 2p)
[ -n "$stop_hook_active" ] || stop_hook_active="false"

# Never loop: if we already blocked once and Claude is stopping again, let it stop.
[ "${stop_hook_active}" = "true" ] && exit 0

# Only fire when the session plausibly did work: uncommitted changes, or a commit in the
# last hour (covers commit-then-stop sessions).
changed=0
if [ -n "$(git status --porcelain 2>/dev/null)" ]; then
  changed=1
elif last=$(git log -1 --format=%ct 2>/dev/null); then
  now=$(date +%s)
  [ $((now - last)) -lt 3600 ] && changed=1
fi
[ "$changed" = "1" ] || exit 0

# Once per session (fall back to a repo-scoped marker when no session id is provided).
marker="${TMPDIR:-/tmp}/okl-encode-reminder-${session_id:-$(pwd | cksum | cut -d' ' -f1)}"
[ -e "$marker" ] && exit 0
touch "$marker" 2>/dev/null || true

cat >&2 <<'MSG'
ENCODING LOOP — before this session ends: did it surface a lesson worth keeping?
A non-obvious failure mode, a rule discovered the hard way, a decision that shouldn't be
silently reversed? If yes, record it now. Three independent axes, each chosen deliberately:

  --scope       WHO may see it: 'org' spreads to every repo, 'repo' stays local
  --tags        WHAT it is about, from the closed vocabulary
  --applies-to  WHERE IT IS TRUE — omit unless the lesson is false or meaningless off
                that stack. Unset means valid on every stack - still subject to scope
                and the repo's declared interests - which is the safe default; a wrong
                value hides the record silently. A tag says where a lesson was FOUND and
                is never a reason to set this.

  okl record --type Defect|Rule|Decision --scope org|repo --tags "<subjects>" \
    --id "<stable-key>" --title "..." --symptom "..." --body "cause: ..." --fix "..." \
    [--applies-to <stack>]   # ONLY for a genuinely framework-bound lesson

  --id is what makes the write idempotent, and leaving it off is the common mistake.
  Without it every record is minted a fresh random id, so the same lesson recorded in two
  sessions becomes two rows, which `okl dedup` will report but cannot remove: there is no
  delete subcommand. Choose a short stable key and reuse it. Where a repo keeps its
  lessons in a seed file, use the id that file derives, "seed:<seed-file-stem>:<key>", so
  a later `okl seed` upserts that same row rather than adding a second one beside it.

If the session genuinely learned nothing durable, state that explicitly and finish.
MSG
exit 2
