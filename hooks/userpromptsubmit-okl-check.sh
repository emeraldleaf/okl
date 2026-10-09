#!/usr/bin/env bash
# okl-fingerprint: sha256:8874c62ec095d3a54e1b083f05ddf009eb652e02658fcd2c1df05736dbe26125
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

# Switched off by name: OKL_DISABLED_HOOKS=briefing,encode. For running beside tools whose
# hooks already cover the same moment, or for debugging. Turning off the pre-task briefing is a choice
# the operator makes explicitly, never a fallback the hook takes on its own.
case ",${OKL_DISABLED_HOOKS:-}," in *,briefing,*) exit 0 ;; esac

# Not enrolled: step aside. okl's Claude Code plugin is installed per user, so these hooks
# run in EVERY repo the user opens, and most were never set up with `okl init`. There the
# pre-task hook blocked every prompt as "OKL NOT CONFIGURED" and the Stop hook asked
# "what did we learn?" of repos with no store to record into (found by a docs audit,
# 2026-09-29, before any user hit it). Only when Claude Code names the project: with no
# CLAUDE_PROJECT_DIR the hook cannot tell an unenrolled repo from a session that drifted
# out of an enrolled one, and fail-closed still wins there.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -z "${OKL_SERVICE_URL:-}${OKL_DATABASE_URL:-}" ]; then
  enrolled=0; d="$PWD"
  while [ "$d" != "/" ]; do
    if [ -f "$d/.okl/config.json" ]; then enrolled=1; break; fi
    d=$(dirname "$d")
  done
  [ "$enrolled" = 1 ] || exit 0
fi

# Resolve how to invoke okl (env → pinned config → PATH → python3 -m okl); hooks run in
# whatever environment the harness spawns, which often lacks the venv/pipx bin dir.
# A layer is used only if its command can actually run. A pinned path goes stale when the
# venv that held it is recreated; running it anyway produced the shell's own "No such file
# or directory" in this hook's stderr, and Claude Code reads that phrase as "the hook script
# is missing" and downgrades a blocking exit 2 to a warning -- the prompt went through with
# no briefing (seen 2026-09-27 on a marketplace install). So: skip what cannot run, and
# never relay that phrase.
# OKL is an array, so a path with spaces in it stays one word. The old form found the
# command with "${1%% *}" and ran it unquoted, which cut a pinned path at its first space:
# the prompt hook then blocked every prompt on an okl that existed (#140). As in the
# pre-push hook, a pinned value is a path, or a python path followed by " -m okl" (what
# okl init writes), and the python form counts only if that python can still import okl:
# a venv whose okl was uninstalled keeps its python. Anything else is one path, so a
# launcher with arguments (uv run okl) belongs in a script that OKL_BIN points at.
try_pinned() {
  case "$1" in
    *" -m okl") command -v "${1% -m okl}" >/dev/null 2>&1 \
                  && "${1% -m okl}" -c "import okl" >/dev/null 2>&1 && OKL=("${1% -m okl}" -m okl) ;;
    *) command -v "$1" >/dev/null 2>&1 && OKL=("$1") ;;
  esac
}
# Sets OKL and resolve_note in the calling shell (not via $(...): a subshell would drop the note).
resolve_note=""
OKL=()
resolve_okl() {
  if [ -n "${OKL_BIN:-}" ]; then
    if try_pinned "$OKL_BIN"; then return 0; fi
    resolve_note="OKL_BIN=$OKL_BIN cannot be run (it takes a path to okl, or \"<python> -m okl\" with a python that can import okl); "
  fi
  local d="$PWD"
  while [ "$d" != "/" ]; do
    if [ -f "$d/.okl/config.json" ]; then
      local bin
      bin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("okl_bin") or "")' \
            "$d/.okl/config.json" 2>/dev/null || true)
      if [ -n "$bin" ]; then
        if try_pinned "$bin"; then return 0; fi
        resolve_note="${resolve_note}the okl_bin pinned in $d/.okl/config.json ($bin) cannot be run -- re-run okl init to re-pin; "
      fi
      break
    fi
    d=$(dirname "$d")
  done
  if command -v okl >/dev/null 2>&1; then OKL=(okl); return 0; fi
  if python3 -c "import okl" >/dev/null 2>&1; then OKL=(python3 -m okl); return 0; fi
  return 1
}

# Everything this hook relays passes through here: a path or okl's own words can carry the
# phrases Claude Code reads as "hook script missing" (see resolve_okl).
scrub() { sed -e 's/No such file or directory/a file is missing/g' -e 's/command not found/command is absent/g'; }

if ! resolve_okl; then
  [ "${OKL_OFFLINE:-0}" = "1" ] && exit 0
  echo "okl could not be resolved — blocking (a check that can't run must not pass as clean)." >&2
  [ -n "$resolve_note" ] && printf '  %s\n' "$resolve_note" | scrub >&2
  echo "Install it: pip install observed-knowledge-ledger. Do not 'pip install okl' — PyPI refuses that" >&2
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

# "${OKL[@]}": a spaced path stays whole and "python3 -m okl" stays three words (#140).
# okl's stderr is kept: it says WHY a check did not run (unreachable, refused, not
# configured), and discarding it turned every refusal into a misreported outage.
# No guessable fallback path: a fixed name under /tmp could be pre-planted as a symlink by
# another local user. Without a private temp file the reason is lost, not the check.
errf=$(mktemp 2>/dev/null) || errf=""
# --format hook: the briefing for the model's context plus one line the person can see,
# as the JSON Claude Code reads from a UserPromptSubmit hook. Without that line nobody
# could tell okl helping from okl doing nothing.
fmt=hook
# A smaller briefing, for a model with a small context window: a full one is roughly 1,600
# tokens on every prompt. OKL_BRIEFING_LIMIT caps how many lessons it draws on (okl's
# default is 12); OKL_BRIEFING_COMPACT=1 sends only the action list. Anything that is not a
# whole number above zero is ignored, so only digits and fixed flags ever reach okl.
size_args=""
case "${OKL_BRIEFING_LIMIT:-}" in
  ''|*[!0-9]*) ;;
  *) [ "$OKL_BRIEFING_LIMIT" -gt 0 ] 2>/dev/null && size_args="--limit $OKL_BRIEFING_LIMIT" ;;
esac
[ "${OKL_BRIEFING_COMPACT:-0}" = "1" ] && size_args="$size_args --compact"
check_once() {
  [ -n "$errf" ] && : > "$errf"   # keep only the last attempt's reason
  # $size_args unquoted on purpose: empty, or validated digits and fixed flags only.
  out=$("${OKL[@]}" check --task "$TASK" --format "$fmt" $size_args 2>"${errf:-/dev/null}")
  rc=$?   # read here: after an if-block, $? is the if's own status, not okl's
}
# Retried briefly before blocking. A repo that rebuilds its gitignored store from committed
# lessons deletes and recreates the SQLite file in about a second, and a prompt landing in
# that window was refused for a fault that had already healed; the fix lived in one repo's
# hand-edited copy of this hook until it was brought back here. Three tries over ~1s still
# fails closed. A binary that cannot start (126/127) will not heal in a second: no retry.
for attempt in 1 2 3; do
  check_once
  if [ "$rc" -eq 2 ] && [ "$fmt" = hook ] && [ -n "$errf" ] && grep -q "invalid choice" "$errf" 2>/dev/null; then
    # An okl older than this hook has no --format hook. The plugin updates from main and the
    # CLI only when upgraded, so the two can differ: brief the old way rather than block.
    fmt=agent
    check_once
  fi
  if [ "$rc" -eq 2 ] && [ -n "$size_args" ] && [ -n "$errf" ] && grep -q "unrecognized arguments" "$errf" 2>/dev/null; then
    # An okl older than OKL_BRIEFING_COMPACT: brief in full rather than block the prompt.
    size_args=""
    check_once
  fi
  [ "$rc" -eq 0 ] && break
  case "$rc" in 126|127) break ;; esac
  [ "$attempt" -lt 3 ] && sleep 0.5
done
if [ "$rc" -eq 0 ]; then
  [ -n "$errf" ] && rm -f "$errf"
  printf '%s\n' "$out"      # stdout → the model's context
  exit 0
fi
# Say HOW it failed. Seen live: a block reading only "exited non-zero without a reason",
# with nothing recorded that could explain it afterwards.
case "$rc" in
  126|127) meaning="okl could not be started (absent or not executable)" ;;
  2) meaning="okl refused (its contract: 2 = did not run)" ;;
  1) meaning="okl reported an error" ;;
  *) if [ "$rc" -gt 128 ]; then meaning="okl was killed by signal $((rc - 128)) (e.g. the machine slept, or a timeout)"
     else meaning="okl failed"; fi ;;
esac
if [ -z "$errf" ]; then
  why="(okl's error output was not captured: no private temp file could be made)"
else
  # A failed read is not silence: only an empty file that read back cleanly is "nothing".
  # The relayed text must not carry the shell's ENOENT phrasing (see resolve_okl).
  if why=$(head -c 1500 "$errf" 2>/dev/null | scrub); then
    [ -n "$why" ] || why="(okl printed nothing)"
  else
    why="(okl's error output was captured but could not be read back)"
  fi
  rm -f "$errf"
fi

if [ "${OKL_OFFLINE:-0}" = "1" ]; then
  echo "OKL offline (OKL_OFFLINE=1 acknowledged) — proceeding without the layer." >&2
  exit 0
fi
echo "OKL CHECK DID NOT RUN — blocking this prompt. A check that reports 'clean' while broken is worse than no check." >&2
echo "exit $rc: $meaning." >&2
[ -n "$resolve_note" ] && printf 'resolver: %s\n' "$resolve_note" | scrub >&2
echo "okl said: $why" >&2
echo "Ran from: $PWD. Fix the cause above, or start the session with OKL_OFFLINE=1 to proceed without the layer." >&2
exit 2
