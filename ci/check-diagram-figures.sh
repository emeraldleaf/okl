#!/usr/bin/env bash
# Every figure a committed diagram publishes must trace to a committed receipt.
#
# The sixth-surface diagram rendered "50% → 6%" and "75% → 8%" under a heading reading
# "MEASURED (held-fixed A/B, blind judge≠generator)" for weeks, in the repo and on a
# public site. Those are the 2026-07-17 numbers that REPORT.md §7 quarantines as
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

# A marker file, because the checks run inside a `while read` subshell and a variable set
# there cannot reach this scope.
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT

# Every diagram under docs/, rather than a hard-coded path: a diagram added later is
# covered the day it lands, not the day someone remembers to extend this file.
#
# `while read` rather than `mapfile`, which is bash 4+. macOS ships bash 3.2, so mapfile
# would have passed on ubuntu CI and failed for anyone running it locally — the shape of
# bug this repo already keeps a rule about.
git ls-files 'docs/*.excalidraw' | while IFS= read -r src; do
  svg="${src%.excalidraw}.svg"
  echo "-- $src"

  # 1. Every receipt the diagram names is committed. A diagram that shows a percentage
  #    while naming no receipt at all is the original failure and fails here too.
  named=$(git show "HEAD:$src" | grep -oE 'ab-[0-9]{8}-[0-9]{4}' | sort -u || true)
  if [ -z "$named" ]; then
    if git show "HEAD:$src" | grep -qE '[0-9]+ ?%'; then
      echo "   FAIL: shows a percentage but names no receipt"
      touch "$work/fail"
    else
      echo "   ok: publishes no figures"
    fi
  fi
  for r in $named; do
    if git ls-files --error-unmatch "evals/results/$r.json" >/dev/null 2>&1; then
      echo "   ok: $r has a committed receipt"
    else
      echo "   FAIL: cites $r, which is not committed under evals/results/"
      touch "$work/fail"
    fi
  done

  # 2. The figures REPORT.md §7 marks as historical must never appear as current claims.
  for q in '50% → 6%' '75% → 8%'; do
    if git show "HEAD:$src" | grep -qF "$q"; then
      echo "   FAIL: publishes '$q', quarantined as historical in REPORT.md §7"
      touch "$work/fail"
    fi
  done

  # 3. The SVG is a render of the source, so it must carry the same receipts. This is
  #    what catches an edited .excalidraw whose SVG was never regenerated — the image is
  #    what people actually read, and it is the artifact that ships to the site.
  if git ls-files --error-unmatch "$svg" >/dev/null 2>&1; then
    for r in $named; do
      if ! git show "HEAD:$svg" | grep -qF "$r"; then
        echo "   FAIL: $svg is missing $r — re-render it from the source"
        touch "$work/fail"
      fi
    done
  else
    echo "   FAIL: $svg is not committed; the source has no published render"
    touch "$work/fail"
  fi
done

if [ -e "$work/fail" ]; then
  exit 1
fi
echo "DIAGRAM_FIGURES_RECEIPTED"
