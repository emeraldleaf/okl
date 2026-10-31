#!/usr/bin/env bash
# okl-fingerprint: sha256:275a8587025902a5cf0ac29655f2c50ca96b1caf0faad1e84ceb89585ec0ec79
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
okl_layer=0
resolve_note=""
try_pinned() {
  case "$1" in
    *" -m okl") command -v "${1% -m okl}" >/dev/null 2>&1 \
                  && "${1% -m okl}" -c "import okl" >/dev/null 2>&1 && OKL=("${1% -m okl}" -m okl) ;;
    *) command -v "$1" >/dev/null 2>&1 && OKL=("$1") ;;
  esac
}
# Sets OKL and okl_layer to the first layer from $1 on whose command exists.
resolve_okl() {
  local from="${1:-1}"
  OKL=()
  if [ "$from" -le 1 ] && [ -n "${OKL_BIN:-}" ]; then
    if try_pinned "$OKL_BIN"; then okl_layer=1; return 0; fi
    resolve_note="OKL_BIN=$OKL_BIN cannot be run; "
  fi
  local d="$PWD"
  while [ "$from" -le 2 ] && [ "$d" != "/" ]; do
    if [ -f "$d/.okl/config.json" ]; then
      local bin=""
      if command -v python3 >/dev/null 2>&1; then
        bin=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("okl_bin") or "")' \
              "$d/.okl/config.json" 2>/dev/null || true)
      else
        # No python3 on the PATH an IDE gives, which is where the pinned path matters most, as in
        # the pre-push hook. okl writes one key per line; a value holding a JSON escape is skipped.
        bin=$(sed -n 's/^ *"okl_bin": *"\([^"\\]*\)",\{0,1\} *$/\1/p' "$d/.okl/config.json" 2>/dev/null || true)
      fi
      if [ -n "$bin" ]; then
        if try_pinned "$bin"; then okl_layer=2; return 0; fi
        resolve_note="${resolve_note}the okl_bin pinned in $d/.okl/config.json ($bin) cannot be run; "
      fi
      break
    fi
    d=$(dirname "$d")
  done
  if [ "$from" -le 3 ] && command -v okl >/dev/null 2>&1; then OKL=(okl); okl_layer=3; return 0; fi
  if [ "$from" -le 4 ] && python3 -c "import okl" >/dev/null 2>&1; then OKL=(python3 -m okl); okl_layer=4; return 0; fi
  return 1
}

# A command can exist and still not serve: a pinned script whose interpreter went with its
# venv, or an okl installed without the [mcp] extra. exec cannot come back to try another, so
# each starts the server once on an empty stdin first (it builds, reads the end of input and
# exits 0, about half a second; without the extra it exits 2), and one that fails gives way to
# the next layer, as in the prompt hook (reviews on #310).
while resolve_okl $((okl_layer + 1)); do
  if "${OKL[@]}" mcp </dev/null >/dev/null 2>&1; then
    exec "${OKL[@]}" mcp
  fi
  resolve_note="${resolve_note}${OKL[*]} could not serve MCP (not started, or no [mcp] extra); "
done
echo "okl MCP server: no okl to run (${resolve_note}none on PATH, and python3 cannot import okl)." >&2
echo "Run \`okl init\` from a shell where okl works, which pins its path, or set OKL_BIN." >&2
exit 1
