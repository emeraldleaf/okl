#!/usr/bin/env bash
# Warn/fail on CLAUDE.md size (keep the canon lean; detail belongs in rules/skills/docs).
set -uo pipefail
cd "$(dirname "$0")/.."
[[ -f CLAUDE.md ]] || { echo "no CLAUDE.md — skipping"; exit 0; }
WARN="${CANON_WARN:-200}"; FAIL="${CANON_FAIL:-300}"
# Whole numbers only: [[ ]] reads -gt's operands as arithmetic, which would run a command hidden
# in a value and read a leading 0 as octal. Under [ ] a bad value made the test fail quietly.
for v in "$WARN" "$FAIL"; do
  [[ "$v" =~ ^(0|[1-9][0-9]*)$ ]] || { echo "  ✗ CANON_WARN and CANON_FAIL must be whole numbers, not '$v'"; exit 2; }
done
n=$(wc -l < CLAUDE.md)
if [[ "$n" -gt "$FAIL" ]]; then echo "  ✗ CLAUDE.md is $n lines (> $FAIL). Split into .claude/rules/*.md."; exit 1; fi
if [[ "$n" -gt "$WARN" ]]; then echo "  ⚠ CLAUDE.md is $n lines (> $WARN soft budget). Consider splitting."; fi
echo "   CLAUDE.md: $n lines"
exit 0
