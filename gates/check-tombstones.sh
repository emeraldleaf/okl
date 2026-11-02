#!/usr/bin/env bash
# Fail if a retired identifier (tombstones.txt) reappears in tracked source/docs/config.
# In a git repository it reads the committed tree, the registry included, so an uncommitted
# edit can neither pass nor fail it and a local run answers as CI will (#352); outside one, it
# reads the files on disk.
set -uo pipefail
cd "$(dirname "$0")/.."
TS="registries/tombstones.txt"
GLOBS=('*.md' '*.py' '*.ts' '*.tsx' '*.cs' '*.yaml' '*.yml' '*.json' '*.sh')
if git rev-parse --verify -q HEAD >/dev/null 2>&1; then
  in_repo=1
  registry="$(git show "HEAD:./$TS" 2>/dev/null)" || { echo "no tombstones.txt committed — skipping"; exit 0; }
else
  in_repo=0
  [ -f "$TS" ] || { echo "no tombstones.txt — skipping"; exit 0; }
  registry="$(cat "$TS")"
fi
search() {  # each line holding $1, as path:line:text
  if [ "$in_repo" = 1 ]; then
    git grep -nF -e "$1" HEAD -- "${GLOBS[@]}" 2>/dev/null | sed 's/^HEAD://'
  else
    local inc=(); for g in "${GLOBS[@]}"; do inc+=(--include="$g"); done
    grep -RnF -e "$1" . "${inc[@]}" 2>/dev/null
  fi
}
rc=0
while IFS= read -r line; do
  case "$line" in ''|'#'*) continue;; esac
  id="$(printf '%s' "$line" | cut -f1)"
  [ -z "$id" ] && continue
  hits="$(search "$id" | grep -v 'registries/' || true)"
  if [ -n "$hits" ]; then
    echo "  ✗ tombstoned identifier '$id' resurrected:"
    echo "$hits" | sed 's/^/      /'
    rc=1
  fi
done <<< "$registry"
exit $rc
