#!/usr/bin/env bash
# Fail if a markdown link points at a local file that does not exist.
# A doc citing a moved or deleted file is drift the compiler cannot see: the prose still
# reads as true, and the reference silently stops resolving. Catches the fallout of
# renames and refactors. External URLs (http/https), anchors-only (#section) and mailto:
# are skipped; a #L42 line anchor is stripped before resolving.
#
# Reads the REPO, not the working tree: it iterates `git ls-files`, so an uncommitted
# scratch file cannot make the audit pass or fail differently than main would.
set -uo pipefail
cd "$(dirname "$0")/.."
command -v git >/dev/null 2>&1 || { echo "no git — skipping"; exit 0; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repo — skipping"; exit 0; }

rc=0
checked=0
while IFS= read -r md; do
  [ -f "$md" ] || continue
  dir=$(dirname "$md")
  # pull the target out of every ](...) link on the page
  while IFS= read -r target; do
    case "$target" in
      ""|\#*|http://*|https://*|mailto:*|\<*) continue ;;
    esac
    target=${target%%#*}          # drop #anchor / #L42
    target=${target%%\?*}         # drop ?query
    [ -z "$target" ] && continue
    case "$target" in
      /*) path=".${target}" ;;    # repo-absolute
      *)  path="$dir/$target" ;;  # relative to the doc
    esac
    checked=$((checked + 1))
    if [ ! -e "$path" ]; then
      echo "  ✗ broken link: $md -> $target"
      rc=1
    fi
  done < <(grep -oE '\]\([^)]+\)' "$md" 2>/dev/null | sed -E 's/^\]\(//; s/\)$//' | awk '{print $1}')
done < <(git ls-files '*.md')

[ "$checked" -eq 0 ] && echo "no local markdown links found — nothing to check"
exit $rc
