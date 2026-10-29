#!/usr/bin/env bash
# okl-fingerprint: sha256:38feeeb18bdd489b32df87bb790cfc17aa4e16c2c36f65d696f4f74577665e1f
# The okl MCP server, started the way the hooks start okl (#206). `.mcp.json` named a bare
# `okl`, so a Claude Code session launched from an IDE, with PATH=/usr/bin:/bin and none of
# the directories uv tool or pipx install into, failed with "Executable not found in $PATH:
# okl" and had no okl tools all session, while the hooks in that same session worked: they
# resolve okl in layers. This script runs the same layers and execs `okl mcp`.
set -uo pipefail

# Anchor to the project, as the hooks do: Claude Code sets CLAUDE_PROJECT_DIR in an MCP
# server's environment, and okl finds the store's config from the working directory.
if [ -n "${CLAUDE_PROJECT_DIR:-}" ] && [ -d "$CLAUDE_PROJECT_DIR" ]; then
  if ! cd "$CLAUDE_PROJECT_DIR" 2>/dev/null; then
    echo "okl MCP server: cannot enter the project directory $CLAUDE_PROJECT_DIR" >&2
    exit 1
  fi
fi

# The layers, in the hooks' order: 1 OKL_BIN, 2 the okl_bin `okl init` pinned in
# .okl/config.json (an absolute path, so it needs no PATH), 3 okl on PATH, 4 python3 -m okl.
# A layer counts only if its command can run; a pinned value is a path, or a python path
# followed by " -m okl" whose python can still import okl.
OKL=()
resolve_note=""
try_pinned() {
  case "$1" in
    *" -m okl") command -v "${1% -m okl}" >/dev/null 2>&1 \
                  && "${1% -m okl}" -c "import okl" >/dev/null 2>&1 && OKL=("${1% -m okl}" -m okl) ;;
    *) command -v "$1" >/dev/null 2>&1 && OKL=("$1") ;;
  esac
}
resolve_okl() {
  if [ -n "${OKL_BIN:-}" ]; then
    try_pinned "$OKL_BIN" && return 0
    resolve_note="OKL_BIN=$OKL_BIN cannot be run; "
  fi
  local d="$PWD"
  while [ "$d" != "/" ]; do
    if [ -f "$d/.okl/config.json" ]; then
      local bin
      bin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("okl_bin") or "")' \
            "$d/.okl/config.json" 2>/dev/null || true)
      if [ -n "$bin" ]; then
        try_pinned "$bin" && return 0
        resolve_note="${resolve_note}the okl_bin pinned in $d/.okl/config.json ($bin) cannot be run; "
      fi
      break
    fi
    d=$(dirname "$d")
  done
  if command -v okl >/dev/null 2>&1; then OKL=(okl); return 0; fi
  if python3 -c "import okl" >/dev/null 2>&1; then OKL=(python3 -m okl); return 0; fi
  return 1
}

if ! resolve_okl; then
  echo "okl MCP server: no okl to run (${resolve_note}none on PATH, and python3 cannot import okl)." >&2
  echo "Run \`okl init\` from a shell where okl works, which pins its path, or set OKL_BIN." >&2
  exit 1
fi
exec "${OKL[@]}" mcp
