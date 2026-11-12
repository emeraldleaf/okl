#!/usr/bin/env bash
# okl-fingerprint: sha256:56d97f5e88caf5e8ff7d806658d2ebe267aa39bd6d93c81218618b3b822d3ad9
# PostToolUse hook on Edit|Write|MultiEdit|NotebookEdit — after the agent edits a file, run the
# checks of the lessons that govern it, the ones the person approved, and hand any failure back
# beside the edit (#435).
#
# A lesson can carry the command that proves it, but nothing ran it while the agent worked: the
# gates only notice that a governed file changed. A lesson handed over on its own changed the
# code where the same lesson in a list mostly did not (REPORT §4ax), and a failing check is not a
# list item. This hook asks `okl on-edit run <file>`, which runs only checks approved with
# `okl on-edit add` (each command shown and confirmed, and pinned by its hash), each with its own
# short timeout. A pass says nothing. It never blocks and never stamps a lesson verified. With no
# check approved it returns before starting okl, so an edit costs one small read of the config.
set -uo pipefail

# Anchor to the project, as the other hooks do: from a directory a `cd` drifted to, okl finds
# no config. Claude Code sets CLAUDE_PROJECT_DIR for every hook; without it, stay where we are.
if [[ -n "${CLAUDE_PROJECT_DIR:-}" ]] && [[ -d "$CLAUDE_PROJECT_DIR" ]]; then
  cd "$CLAUDE_PROJECT_DIR" 2>/dev/null || exit 0
fi

# Switched off by name: OKL_DISABLED_HOOKS=edit (or briefing,encode,read,edit).
case ",${OKL_DISABLED_HOOKS:-}," in *,edit,*) exit 0 ;; esac

# The approvals live in .okl/config.json: no config, nothing approved, nothing to run. The plugin's
# hooks run in every repo the user opens, and most were never set up with `okl init`.
config=""; d="$PWD"
while [[ "$d" != "/" ]]; do
  if [[ -f "$d/.okl/config.json" ]]; then config="$d/.okl/config.json"; break; fi
  d=$(dirname "$d")
done
[[ -n "$config" ]] || exit 0
grep -q '"on_edit"' "$config" 2>/dev/null || exit 0

# python3 reads the payload below. Checks were approved here, so a silence would read as "they
# passed": say they did not run instead, in JSON built without python (a fixed text).
if ! command -v python3 >/dev/null 2>&1; then
  printf '%s\n' '{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "OKL CHECKS NOT RUN: python3 is not on PATH, so the edit hook could not tell which file was edited. Lesson checks approved in this repository did not run on this edit; run them before relying on it."}}'
  exit 0
fi

# The edit: which file. Edit, Write and MultiEdit name file_path; NotebookEdit names
# notebook_path. Anything unreadable is no file, and no check.
payload=$(cat 2>/dev/null || true)
file=$(printf '%s' "$payload" | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
t = d.get("tool_input") or {}
print(t.get("file_path") or t.get("notebook_path") or "")
' 2>/dev/null) || file=""
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
  if [[ "$from" -le 2 ]]; then
    local bin
    bin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("okl_bin") or "")' \
          "$config" 2>/dev/null || true)
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
# Resolve the next layer whose command has not already failed this edit.
failed_cmds="|"
next_layer() {
  while resolve_okl $((okl_layer + 1)); do
    case "$failed_cmds" in *"|$(cmd_key)|"*) ;; *) return 0 ;; esac
  done
  return 1
}

# One line of context when okl cannot answer: never a silence the agent reads as "they passed".
not_run() {
  python3 -c '
import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext":
    f"OKL CHECKS NOT RUN for {sys.argv[1]}: {sys.argv[2]}. Lesson checks approved in this "
    "repository may govern this file; run them before relying on the edit."}}))' "$file" "$1"
}

if ! resolve_okl; then
  not_run "okl could not be found (not as OKL_BIN, a pin in .okl/config.json, on PATH, or as python3 -m okl)"
  exit 0
fi

errf=$(mktemp 2>/dev/null || echo "")
run_checks() {
  local started=$SECONDS
  out=$("${OKL[@]}" on-edit run --format hook -- "$file" 2>"${errf:-/dev/null}")
  rc=$?
  run_s=$((SECONDS - started))
}
run_checks
# A command that resolved but could not start (a pinned okl whose interpreter is gone exits
# 126 or 127) resumes at the next layer, as in the read hook. Only a QUICK failure falls
# through: a launcher that ran its checks and then exited 127 would run them again.
while { [[ "$rc" -eq 126 ]] || [[ "$rc" -eq 127 ]]; } && [[ "$run_s" -lt 2 ]]; do
  failed_cmds="${failed_cmds}$(cmd_key)|"
  next_layer || break
  run_checks
done
# 0: every check passed or none applied; 1: a check failed, and the JSON says which.
if [[ "$rc" -eq 0 ]] || [[ "$rc" -eq 1 ]]; then
  printf '%s' "$out"
else
  why=$( { [[ -n "$errf" ]] && tail -n 1 "$errf"; } 2>/dev/null)
  not_run "okl exited $rc${why:+: $why}"
fi
[[ -n "$errf" ]] && rm -f "$errf"
exit 0
