#!/usr/bin/env bash
# Fail if an editable diagram source has no rendered sibling.
# Reviewers read the rendered image; contributors edit the source. A source with no render
# means reviewers see nothing (source files do not display inline on most forges), so that
# direction FAILS. The reverse is only reported: a rendered file with no source is often a
# hand-authored image, which is legitimate — this kit will not presume every diagram comes
# from one editor. This is the cheap mechanical floor: it proves the render EXISTS. It does
# NOT prove the render matches the source; re-rendering after a source edit stays human.
#
# Reads the REPO, not the working tree. Silent no-op in repos with no diagrams.
set -uo pipefail
cd "$(dirname "$0")/.."
command -v git >/dev/null 2>&1 || { echo "no git — skipping"; exit 0; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "not a git repo — skipping"; exit 0; }

SRC_EXT="${OKL_DIAGRAM_SRC_EXT:-excalidraw}"   # editable source
OUT_EXT="${OKL_DIAGRAM_OUT_EXT:-svg}"          # rendered output

rc=0
n=0
while IFS= read -r src; do
  n=$((n + 1))
  [ -e "${src%.$SRC_EXT}.$OUT_EXT" ] || { echo "  ✗ diagram source with no rendered $OUT_EXT: $src"; rc=1; }
done < <(git ls-files "*.$SRC_EXT")

# Informational only: a hand-authored image is a legitimate source of its own.
while IFS= read -r out; do
  n=$((n + 1))
  [ -e "${out%.$OUT_EXT}.$SRC_EXT" ] || echo "  · note: $out has no .$SRC_EXT source (fine if hand-authored)"
done < <(git ls-files "*.$OUT_EXT")

[ "$n" -eq 0 ] && echo "no .$SRC_EXT/.$OUT_EXT diagrams tracked — nothing to check"
exit $rc
