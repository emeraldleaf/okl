#!/usr/bin/env bash
# Fail if a doc or image under docs/ is not reachable (linked) from a hub file or a doc.
# A doc nobody links to drifts unseen — this is the doc-orphan reachability gate.
#
# Images count too. It walked docs/*.md only, so a diagram nothing embedded was
# invisible to it: okl's first architecture diagram sat unlinked for weeks, carrying a
# stale heading and figures its receipts no longer supported, while every gate reported
# clean. It was found by hand and deleted (#67).
#
# Reads the repo, not the working tree, when there is one: an uncommitted file must not
# pass or fail an audit that the committed tree would answer differently.
set -uo pipefail
cd "$(dirname "$0")/.."
[ -d docs ] || { echo "no docs/ — skipping"; exit 0; }
# The root README.md is a hub. It was missing from this list, so a doc linked from the
# most obvious index in the repository was still reported as an orphan — the gate was
# telling people to fix a doc that was already reachable. Found by running this gate
# against okl itself, which links docs/DEPLOY.md from its root README and nowhere else.
HUBS="$(ls README.md docs/README.md docs/index.md CLAUDE.md METHOD.md 2>/dev/null || true)"
[ -z "$HUBS" ] && { echo "no hub file — skipping"; exit 0; }
if git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  in_repo=1
  targets=$(git ls-tree --name-only HEAD docs/ | grep -E '\.(md|svg|png|jpe?g|gif|webp)$' || true)
else
  in_repo=0
  targets=$(ls docs/*.md docs/*.svg docs/*.png docs/*.jpg docs/*.jpeg docs/*.gif docs/*.webp 2>/dev/null || true)
fi
linked() {  # is $1 named in any hub or in any markdown under docs/?
  if [ "$in_repo" = 1 ]; then
    # shellcheck disable=SC2086
    git grep -qF "$1" HEAD -- $HUBS 'docs/*.md' 2>/dev/null
  else
    # shellcheck disable=SC2086
    grep -RqlF "$1" $HUBS docs/ --include='*.md' 2>/dev/null
  fi
}
rc=0
for doc in $targets; do
  base="$(basename "$doc")"
  # skip hub files and kit-shipped reference docs (not project docs to link)
  case "$base" in README.md|index.md|method-kit-manifest.md) continue;; esac
  if ! linked "$base"; then
    echo "  ✗ orphan (unlinked from any hub or doc): $doc"; rc=1
  fi
done
exit $rc
