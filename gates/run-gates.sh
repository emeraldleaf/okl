#!/usr/bin/env bash
# run-gates.sh — the mechanical drift-gates (surface 5). Portable; stack-agnostic.
# Run locally via `/check-rules` or `bash gates/run-gates.sh`; wired into CI (see ci/).
#
# Each gate is a separate script returning non-zero on drift. This runner aggregates them so one
# red gate fails the whole check (fail-closed). Add stack-specific gates in the <<FILL>> block.
set -uo pipefail
cd "$(dirname "$0")/.."   # repo root
GATES_DIR="gates"
fail=0

run() {
  local name="$1"; shift
  echo "── gate: $name ──"
  if "$@"; then echo "   ✓ $name"; else echo "   ✗ $name FAILED"; fail=1; fi
}

run "retractions"     bash "$GATES_DIR/check-retractions.sh"
run "tombstones"      bash "$GATES_DIR/check-tombstones.sh"
run "doc-orphans"     bash "$GATES_DIR/check-doc-orphans.sh"
run "links"          bash "$GATES_DIR/check-links.sh"
run "diagram-pairs"  bash "$GATES_DIR/check-diagram-pairs.sh"
run "canon-size"      bash "$GATES_DIR/check-canon-size.sh"

# <<FILL: STACK-SPECIFIC GATES — e.g. class-path import check, analyzer, type-check, tests>>
# run "class-paths"   bash "$GATES_DIR/check-scaffold-classpaths.sh"
# run "tests"         your-test-command

if [ "$fail" -ne 0 ]; then
  echo; echo "GATES RED — do not merge. Encode the fix at the smallest surface, then re-run."
  exit 1
fi
echo; echo "All gates green."
