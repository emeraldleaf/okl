#!/usr/bin/env bash
# okl-fingerprint: sha256:ef34a0bb5f0c0eb2213dd5231a2340514a909784bc807afb65a8d6152396f38e
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

# The .okl/config.json okl reads here: the nearest at or above this folder, or else, in a git worktree
# with none (git ignores .okl/, so a worktree beside the checkout never has one), its main checkout's,
# as okl itself resolves it since #492. Walking up alone, a session started in such a worktree found
# no config, and every hook stepped aside as if the repo had never been set up.
okl_config() {
  local d="$PWD" common
  while [[ "$d" != "/" ]]; do
    if [[ -f "$d/.okl/config.json" ]]; then printf '%s\n' "$d/.okl/config.json"; return 0; fi
    d=$(dirname "$d")
  done
  # Asked for plainly and made absolute here. --path-format is git 2.31's, and an older git prints
  # an option it does not know back as a line of its answer: in a worktree under git 2.30 this
  # read two lines, found no config, and the hook stepped aside as if okl had never been set up.
  common=$(git rev-parse --git-common-dir 2>/dev/null) || return 1
  [[ "$common" == /* ]] || common="$PWD/$common"
  [[ "${common##*/}" == ".git" && -f "${common%/.git}/.okl/config.json" ]] || return 1
  printf '%s\n' "${common%/.git}/.okl/config.json"
}

# Not enrolled: step aside, as the other hooks do. The plugin's hooks run in every repo the user
# opens, and most were never set up with `okl init`.
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]] && [[ -z "${OKL_SERVICE_URL:-}${OKL_DATABASE_URL:-}" ]]; then
  okl_config >/dev/null || exit 0
fi

# python3 reads the payload below. Without it the hook cannot tell which file was read, and
# exiting silent reads to the agent as "no lessons here": say so instead, in JSON built
# without python (a fixed text, so nothing needs escaping).
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "OKL NOT BRIEFED: python3 is not on PATH, so the read hook could not tell which file was read. Lessons may govern it that you cannot see; check before relying on what you read."}}'
  exit 0
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
  local cfg
  if [[ "$from" -le 2 ]] && cfg=$(okl_config); then
    local bin
    bin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("okl_bin") or "")' \
          "$cfg" 2>/dev/null || true)
    if [[ -n "$bin" ]] && try_pinned "$bin"; then okl_layer=2; return 0; fi
  fi
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
