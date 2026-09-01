#!/usr/bin/env bash
# Every figure the architecture diagram publishes must trace to a committed receipt.
#
# The diagram rendered "50% → 6%" and "75% → 8%" under a heading reading
# "MEASURED (held-fixed A/B, blind judge≠generator)" for weeks, on the repo README and on
# a public site. Those are the 2026-07-17 numbers that REPORT.md §7 quarantines as
# historical: the raw artifacts were never checked in, so they are not reproducible. The
# site's own prose cited the receipted figures right beside the image, so the page
# contradicted itself and a reader had no way to tell which was real.
#
# It survived because the drift stamp on the diagram record was earned by grepping for a
# couple of expected strings. "Some expected text is present" is not "no unsupported
# claim is present" — only the second is worth a verification stamp.
#
# Reads the repo, not the working tree, per the audit rule in CLAUDE.md: an uncommitted
# edit must not be able to pass or fail an audit that main would answer differently.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

src="docs/okl-sixth-surface.excalidraw"
svg="docs/okl-sixth-surface.svg"
fail=0

# 1. Every receipt the diagram names is actually committed.
named=$(git show "HEAD:$src" | grep -oE 'ab-[0-9]{8}-[0-9]{4}' | sort -u || true)
if [ -z "$named" ]; then
  echo "FAIL: the diagram cites no receipt at all — a MEASURED card must name its evidence"
  fail=1
fi
for r in $named; do
  if git ls-files --error-unmatch "evals/results/$r.json" >/dev/null 2>&1; then
    echo "ok: $r has a committed receipt"
  else
    echo "FAIL: the diagram cites $r, which is not committed under evals/results/"
    fail=1
  fi
done

# 2. The figures REPORT.md §7 marks as historical must never appear as current claims.
for q in '50% → 6%' '75% → 8%'; do
  if git show "HEAD:$src" | grep -qF "$q"; then
    echo "FAIL: the diagram publishes '$q', quarantined as historical in REPORT.md §7"
    fail=1
  fi
done

# 3. The SVG is a render of the source, so it must carry the same receipts. This is what
#    catches an edited .excalidraw whose SVG was never re-rendered — the published image
#    is the one people actually read.
for r in $named; do
  if ! git show "HEAD:$svg" | grep -qF "$r"; then
    echo "FAIL: $svg is missing $r — re-render it from the .excalidraw"
    fail=1
  fi
done

if [ "$fail" -eq 0 ]; then
  echo "DIAGRAM_FIGURES_RECEIPTED"
fi
exit "$fail"
