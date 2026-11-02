#!/usr/bin/env bash
# Fail if a tracked doc restates a retracted claim without retracting it.
# Each retraction entry declares a quoted claim; if that exact quote appears in a doc OTHER than the
# retraction registry, flag it. (A restated claim needs its own retraction note or removal.)
# In a git repository it reads the committed tree, the registry included, so an uncommitted
# edit can neither pass nor fail it and a local run answers as CI will (#352); outside one, it
# reads the files on disk.
set -uo pipefail
cd "$(dirname "$0")/.."
REG="registries/RETRACTIONS.md"
if git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  in_repo=1
  registry="$(git show "HEAD:./$REG" 2>/dev/null)" || { echo "no RETRACTIONS.md committed — skipping"; exit 0; }
else
  in_repo=0
  [ -f "$REG" ] || { echo "no RETRACTIONS.md — skipping"; exit 0; }
  registry="$(cat "$REG")"
fi
search() {  # each markdown line holding $1, as path:line:text
  if [ "$in_repo" = 1 ]; then
    git grep -nF -e "$1" HEAD -- '*.md' 2>/dev/null | sed 's/^HEAD://'
  else
    grep -RnF -e "$1" . --include='*.md' 2>/dev/null
  fi
}
rc=0
tmp="$(mktemp)"
printf '%s\n' "$registry" | grep -oE '"[^"]{12,}"' | sed 's/^"//;s/"$//' > "$tmp" || true
while IFS= read -r claim; do
  [ -z "$claim" ] && continue
  hits="$(search "$claim" | grep -v "$REG" || true)"
  if [ -n "$hits" ]; then
    echo "  ✗ retracted claim restated: \"$claim\""
    echo "$hits" | sed 's/^/      /'
    rc=1
  fi
done < "$tmp"
rm -f "$tmp"
exit $rc
