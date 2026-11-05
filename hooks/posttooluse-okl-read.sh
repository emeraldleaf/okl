#!/usr/bin/env bash
# okl-fingerprint: sha256:5999b0689b50c09260ea1fac6512549e915aedeaacb0e80ac8aaf98b70eb5caf
# PostToolUse hook on Read — brief the lessons that govern a file when the agent reads it (#94).
#
# The prompt hook briefs once, when a prompt is sent; within a long turn the edit a lesson
# governs can come many tool calls later. This hook runs after a Read, asks
# `okl check --path <file>` which lessons govern the file, and returns them as
# `hookSpecificOutput.additionalContext`, which Claude Code puts next to the read's result,
# before any edit. Each lesson once per session, again only while drift marks it. REPORT §4aj
# measured whether it arrives. It never blocks: a read has already happened, so when okl cannot
# answer it says so in one line instead of staying silent, and a file no lesson governs gets
# nothing at all.
set -uo pipefail

# Anchor to the project, as the other hooks do: from a directory a `cd` drifted to, okl finds
# no config. Claude Code sets CLAUDE_PROJECT_DIR for every hook; without it, stay where we are.
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]] && [[ -d "$CLAUDE_PROJECT_DIR" ]]; then
  cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || exit 0
fi

# Switched off by name: OKL_DISABLED_HOOKS=read (or briefing,encode,read).
case ",${OKL_DISABLED_HOOKS:-}," in *,read,*) exit 0 ;; esac

# Not enrolled: step aside, as the other hooks do. The plugin's hooks run in every repo the user
# opens, and most were never set up with `okl init`.
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]] && [[ -z "${OKL_SERVICE_URL:-}${OKL_DATABASE_URL:-}" ]]; then
  enrolled=0; d="$PWD"
  while [[ "$d" != "/" ]]; do
    if [[ -f "$d/.okl/config.json" ]]; then enrolled=1; break; fi
    d=$(dirname "$d")
  done
  [[ "$enrolled" = 1 ]] || exit 0
fi

# The read: which file, in which session. Anything unreadable is no file, and no briefing.
payload=$(cat 2>/dev/null || true)
parsed=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
print((d.get("tool_input") or {}).get("file_path", ""))
print(d.get("session_id", ""))
' 2>/dev/null) || parsed=""
file=$(printf '%s\n' "$parsed" | sed -n 1p)
session_id=$(printf '%s\n' "$parsed" | sed -n 2p)
[[ -n "$file" ]] || exit 0

# Same resolver as the other hooks (env → pinned config → PATH → python3 -m okl). OKL is an
# array, so a path with spaces stays one word; a pinned value is a path, or a python followed
# by " -m okl" that can still import okl.
try_pinned() {
  case "$1" in
    *" -m okl") command -v "${1% -m okl}" >/dev/null 2>&1 \
                  && "${1% -m okl}" -c "import okl" >/dev/null 2>&1 && OKL=("${1% -m okl}" -m okl) ;;
    *) command -v "$1" >/dev/null 2>&1 && OKL=("$1") ;;
  esac
}
OKL=()
okl_layer=0
# The layers, in order: 1 OKL_BIN, 2 the okl_bin pinned in .okl/config.json, 3 okl on PATH,
# 4 python3 -m okl. $1 is the first layer to try, so a command that resolved but then could
# not start can resume at the next one, as in the prompt hook (#152).
resolve_okl() {
  local from="${1:-1}"
  if [[ "$from" -le 1 ]] && [[ -n "${OKL_BIN:-}" ]] && try_pinned "$OKL_BIN"; then okl_layer=1; return 0; fi
  local d="$PWD"
  while [[ "$from" -le 2 ]] && [[ "$d" != "/" ]]; do
    if [[ -f "$d/.okl/config.json" ]]; then
      local bin
      bin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("okl_bin") or "")' \
            "$d/.okl/config.json" 2>/dev/null || true)
      if [[ -n "$bin" ]] && try_pinned "$bin"; then okl_layer=2; return 0; fi
      break
    fi
    d=$(dirname "$d")
  done
  if [[ "$from" -le 3 ]] && command -v okl >/dev/null 2>&1; then OKL=(okl); okl_layer=3; return 0; fi
  if [[ "$from" -le 4 ]] && python3 -c "import okl" >/dev/null 2>&1; then OKL=(python3 -m okl); okl_layer=4; return 0; fi
  return 1
}
# One key per command, so a file reached through two layers (pinned, and on PATH) counts once.
cmd_key() {
  if [[ "${#OKL[@]}" -eq 1 ]]; then command -v "${OKL[0]}" 2>/dev/null || printf '%s' "${OKL[0]}"
  else printf '%s' "${OKL[*]}"; fi
}
# Resolve the next layer whose command has not already failed this read.
failed_cmds="|"
next_layer() {
  while resolve_okl $((okl_layer + 1)); do
    case "$failed_cmds" in *"|$(cmd_key)|"*) ;; *) return 0 ;; esac
  done
  return 1
}

# One line of context when okl cannot answer: never a silence the agent reads as "no rules".
not_briefed() {
  python3 -c '
import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
    f"OKL NOT BRIEFED for {sys.argv[1]}: {sys.argv[2]}. Lessons may govern this file that you "
    "cannot see; check before relying on what you read."}}))' "$file" "$1"
}

if ! resolve_okl; then
  not_briefed "okl could not be found (not as OKL_BIN, a pin in .okl/config.json, on PATH, or as python3 -m okl)"
  exit 0
fi

errf=$(mktemp 2>/dev/null || echo "")
run_check() {
  local started=$SECONDS
  out=$("${OKL[@]}" check --path "$file" --format hook --hook-event PostToolUse \
        ${session_id:+--session "$session_id"} 2>"${errf:-/dev/null}")
  rc=$?
  run_s=$((SECONDS - started))
}
run_check
# A command that resolved but could not start (a pinned okl whose interpreter is gone exits
# 126 or 127) resumes at the next layer rather than lose the briefing (#152). Only a QUICK
# failure falls through, as in the prompt hook: a launcher that ran and exited 127 would run
# again at each layer. A command that already failed is never run again.
while { [[ "$rc" -eq 126 ]] || [[ "$rc" -eq 127 ]]; } && [[ "$run_s" -lt 2 ]]; do
  failed_cmds="${failed_cmds}$(cmd_key)|"
  next_layer || break
  run_check
done
if [[ "$rc" -eq 0 ]]; then
  printf '%s' "$out"
else
  why=$( { [[ -n "$errf" ]] && tail -n 1 "$errf"; } 2>/dev/null)
  not_briefed "okl exited $rc${why:+: $why}"
fi
[[ -n "$errf" ]] && rm -f "$errf"
exit 0
