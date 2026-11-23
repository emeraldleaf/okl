#!/usr/bin/env bash
# The review docs/DEVELOPING.md asks for before a pull request, and the record that it ran.
#
#   bash ci/review-before-pr.sh            run the review CLI on this branch's commits; when it
#                                          finishes, record the commit it reviewed
#   bash ci/review-before-pr.sh --check    say whether the checked-out branch has a recorded review
#
# Why it exists. The rule was a paragraph in the developer guide, and twelve pull requests in a row
# were opened without the review: nothing looked, so nothing noticed (2026-11, #500 to #511). The
# first of them reviewed afterwards had seven real findings. `--check` is one line for a pre-push
# hook, where the push that precedes a pull request passes:
#
#   bash ci/review-before-pr.sh --check || true
#
# It reports and holds nothing: a docs-only change may wait for the next sweep (DEVELOPING.md).
#
# The record is written only by a run that ended in the CLI's own "Review completed" line: a run
# that was refused for the allowance, or cut short, records nothing. It is kept in the repository's
# git directory (shared by its worktrees, never committed), so this is a check of this machine and
# says nothing in CI, where no record exists.
#
# Exit: 0 reviewed (or nothing to review, with --check), 1 not reviewed (--check), 2 did not run.
#
# PR_REVIEW_CMD   the review command, read as words (default: coderabbit review --committed --base origin/main)
# PR_REVIEW_BASE  the base the branch is compared with (default: origin/main)
# PR_REVIEW_DONE  the line that says the review finished (default: Review completed)
set -uo pipefail

BASE="${PR_REVIEW_BASE:-origin/main}"
DONE="${PR_REVIEW_DONE:-Review completed}"
did_not_run() { echo "review-before-pr: $1" >&2; exit 2; }

command -v git >/dev/null 2>&1 || did_not_run "git is not on PATH."
tip=$(git rev-parse --verify -q 'HEAD^{commit}' 2>/dev/null) || did_not_run "no commit is checked out here."
branch=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
# Asked without --path-format: an older git prints that option back as part of its answer, and the
# record went into a folder of that name (lesson git-option-echoed-by-older-git).
common=$(git rev-parse --git-common-dir 2>/dev/null) || did_not_run "this is not a git repository."
[[ "$common" == /* ]] || common="$PWD/$common"
state="$common/okl-pr-review"

if [[ "${1:-}" == "--check" ]]; then
  # Nothing to review is not a missing review: the default branch, a detached commit, or a branch
  # with no commit of its own.
  [[ "$branch" != "HEAD" && "$branch" != "${BASE#*/}" ]] || exit 0
  git rev-parse --verify -q "$BASE^{commit}" >/dev/null 2>&1 || did_not_run "$BASE is not here to compare with, so it cannot tell."
  [[ -n "$(git rev-list -n 1 "$BASE..$tip" 2>/dev/null)" ]] || exit 0
  record="$state/$(printf '%s' "$branch" | git hash-object --stdin)"
  reviewed=""
  [[ -f "$record" && ! -L "$record" ]] && reviewed=$(head -n 1 "$record" 2>/dev/null)
  # A review of this branch at the pushed commit or one under it counts: the fixes it asked for
  # come after it. A record from before the branch was started again does not.
  if [[ "$reviewed" =~ ^[0-9a-f]{40,64}$ ]] && git merge-base --is-ancestor "$reviewed" "$tip" 2>/dev/null \
     && [[ -n "$(git rev-list -n 1 "$BASE..$reviewed" 2>/dev/null)" ]]; then
    exit 0
  fi
  echo "review-before-pr: NO REVIEW RECORDED for branch '$branch'. docs/DEVELOPING.md asks for one before the" >&2
  echo "  pull request: bash ci/review-before-pr.sh (then fix what it finds in one push). A docs-only" >&2
  echo "  change can wait for the next sweep." >&2
  exit 1
fi
[[ $# -eq 0 ]] || did_not_run "unknown argument '$1' (the one option is --check)."

[[ "$branch" != "HEAD" ]] || did_not_run "no branch is checked out, so there is nothing to record a review for."
git rev-parse --verify -q "$BASE^{commit}" >/dev/null 2>&1 || did_not_run "$BASE is not here to compare with (git fetch origin)."
[[ -n "$(git rev-list -n 1 "$BASE..$tip" 2>/dev/null)" ]] || did_not_run "branch '$branch' has no commit that $BASE lacks, so there is nothing to review."
# Read as words, never through a shell: the command comes from the environment.
read -r -a cmd <<< "${PR_REVIEW_CMD:-coderabbit review --committed --base $BASE}"
command -v "${cmd[0]}" >/dev/null 2>&1 || did_not_run "'${cmd[0]}' is not on PATH (PR_REVIEW_CMD names the review command)."

out=$(mktemp "${TMPDIR:-/tmp}/review-before-pr.XXXXXX") || did_not_run "no temporary file could be made."
trap 'rm -f "$out"' EXIT
# Everything it prints goes to stderr, with the review: stdout stays empty for a caller that reads it.
"${cmd[@]}" 2>&1 | tee "$out" >&2
status=${PIPESTATUS[0]}
if [[ "$status" -ne 0 ]] || ! grep -qF -- "$DONE" "$out"; then
  did_not_run "REVIEW NOT RECORDED: '${cmd[0]}' exited $status and $( grep -qF -- "$DONE" "$out" && echo "printed" || echo "did not print" ) \"$DONE\". Nothing counts as reviewed."
fi
# The commit read before the review began: one made while it ran was not reviewed.
mkdir -p "$state" || did_not_run "REVIEW NOT RECORDED: $state could not be made."
record="$state/$(printf '%s' "$branch" | git hash-object --stdin)"
[[ ! -L "$record" ]] || did_not_run "REVIEW NOT RECORDED: $record is a symlink."
printf '%s\n%s\n%s\n' "$tip" "$branch" "$(date -u +%Y-%m-%dT%H:%MZ)" > "$record" || did_not_run "REVIEW NOT RECORDED: $record could not be written."
echo "review-before-pr: recorded a finished review of '$branch' at ${tip:0:12}. Fix what it found, in one push." >&2
exit 0
