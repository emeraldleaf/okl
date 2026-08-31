#!/usr/bin/env bash
# PreToolUse hook — inject the org's relevant lessons before the first edit.
# FAILS CLOSED via exit code 2 (the current Claude Code hook-blocking convention): if the knowledge
# layer is unreachable, block rather than let the agent proceed blind. A check that reports "clean"
# while broken is worse than no check.
set -uo pipefail

# Resolve how to invoke okl. Hooks run in whatever environment the agent harness spawns,
# which often lacks the venv/pipx bin dir on PATH — so PATH lookup comes LAST, not first:
#   1. OKL_BIN env override
#   2. okl_bin pinned in .okl/config.json by `okl init` (machine-local; searched upward)
#   3. `okl` on PATH
#   4. any python3 that can import okl (`python3 -m okl`)
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
  echo "Install it (pip install okl), set OKL_BIN to its path, or re-run 'okl init' from a shell" >&2
  echo "where it works (pins okl_bin into .okl/config.json). OKL_OFFLINE=1 proceeds without the layer." >&2
  exit 2
fi

TASK="${OKL_TASK:-$(git log -1 --pretty=%s 2>/dev/null || echo 'general work')}"

# $OKL unquoted on purpose: it may be a command + args ("python3 -m okl").
if out=$($OKL check --task "$TASK" --format agent 2>/dev/null); then
  echo "$out"
  exit 0
fi

# okl unreachable or errored.
if [ "${OKL_OFFLINE:-0}" = "1" ]; then
  echo "OKL offline (OKL_OFFLINE=1 acknowledged) — proceeding without the layer." >&2
  exit 0
fi
echo "OKL UNREACHABLE — blocking. A check that reports 'clean' while broken is worse than no check." >&2
echo "Fix connectivity, or set OKL_OFFLINE=1 to explicitly proceed without the org knowledge layer." >&2
exit 2
