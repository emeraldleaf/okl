#!/usr/bin/env bash
# Fail if a tracked doc restates a retracted claim without retracting it.
# Each retraction entry declares a quoted claim; if that exact quote appears in a doc OTHER than the
# retraction registry, flag it. (A restated claim needs its own retraction note or removal.)
set -uo pipefail
cd "$(dirname "$0")/.."
REG="registries/RETRACTIONS.md"
[ -f "$REG" ] || { echo "no RETRACTIONS.md — skipping"; exit 0; }
rc=0
tmp="$(mktemp)"
grep -oE '"[^"]{12,}"' "$REG" | sed 's/^"//;s/"$//' > "$tmp" || true
while IFS= read -r claim; do
  [ -z "$claim" ] && continue
  hits="$(grep -RnF "$claim" . --include='*.md' 2>/dev/null | grep -v "$REG" || true)"
  if [ -n "$hits" ]; then
    echo "  ✗ retracted claim restated: \"$claim\""
    echo "$hits" | sed 's/^/      /'
    rc=1
  fi
done < "$tmp"
rm -f "$tmp"
exit $rc
