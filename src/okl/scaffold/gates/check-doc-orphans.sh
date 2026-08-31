#!/usr/bin/env bash
# Fail if a doc under docs/ is not reachable (linked) from a hub file or another doc.
# A doc nobody links to drifts unseen — this is the doc-orphan reachability gate.
set -uo pipefail
cd "$(dirname "$0")/.."
[ -d docs ] || { echo "no docs/ — skipping"; exit 0; }
HUBS="$(ls docs/README.md docs/index.md CLAUDE.md METHOD.md 2>/dev/null || true)"
[ -z "$HUBS" ] && { echo "no hub file — skipping"; exit 0; }
rc=0
for doc in docs/*.md; do
  [ -e "$doc" ] || continue
  base="$(basename "$doc")"
  # skip hub files and kit-shipped reference docs (not project docs to link)
  case "$base" in README.md|index.md|method-kit-manifest.md) continue;; esac
  if ! grep -RqlF "$base" $HUBS docs/ --include='*.md' 2>/dev/null; then
    echo "  ✗ orphan doc (unlinked from any hub or sibling): $doc"; rc=1
  fi
done
exit $rc
