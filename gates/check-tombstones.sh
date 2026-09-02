#!/usr/bin/env bash
# Fail if a retired identifier (tombstones.txt) reappears in tracked source/docs/config.
set -uo pipefail
cd "$(dirname "$0")/.."
TS="registries/tombstones.txt"
[ -f "$TS" ] || { echo "no tombstones.txt — skipping"; exit 0; }
rc=0
while IFS= read -r line; do
  case "$line" in ''|'#'*) continue;; esac
  id="$(printf '%s' "$line" | cut -f1)"
  [ -z "$id" ] && continue
  hits="$(grep -RnF "$id" . \
          --include='*.md' --include='*.py' --include='*.ts' --include='*.tsx' \
          --include='*.cs' --include='*.yaml' --include='*.yml' --include='*.json' --include='*.sh' \
          2>/dev/null | grep -v 'registries/' || true)"
  if [ -n "$hits" ]; then
    echo "  ✗ tombstoned identifier '$id' resurrected:"
    echo "$hits" | sed 's/^/      /'
    rc=1
  fi
done < "$TS"
exit $rc
