#!/usr/bin/env bash
# review-agent.sh — run the architecture reviewer over a PR diff, headless.
#
# Closes the gap the store names as "an enforcement surface that only runs on-demand runs
# never": .claude/agents/architecture-reviewer.md is listed as a review surface but nothing
# triggers it, so in practice it runs when someone remembers, which is never.
#
# OFF BY DEFAULT, AND VENDOR-NEUTRAL. Set REVIEW_CMD to any CLI that reads a prompt on
# stdin and writes the model's reply to stdout:
#
#   REVIEW_CMD="claude -p --model sonnet"
#   REVIEW_CMD="llm -m gpt-4o"
#   REVIEW_CMD="ollama run qwen2.5-coder"        # local, no API cost at all
#
# Unset, the step soft-passes and says how to switch it on. okl is harness-agnostic —
# hard-coding one vendor's CLI here would contradict that, and would hand every consumer
# an API bill they never asked for. This mirrors GENERATOR_CMD/JUDGE_CMD in evals/.
#
# Self-owned on purpose: no third-party review SaaS holds a token for your source, and the
# reviewer reads YOUR encoded rules (it calls `okl check` itself) rather than generic advice.
set -uo pipefail
cd "$(dirname "$0")/.."

# Located, not assumed: `okl scaffold --claude-dir` lets a repo name that directory
# something other than .claude, and a hard-coded path silently skips the review in exactly
# those repos — a gate that quietly does nothing is the failure this whole file exists to
# fix. AGENT_FILE overrides for anything unusual.
AGENT="${AGENT_FILE:-}"
if [ -z "$AGENT" ]; then
  AGENT="$(find . -maxdepth 3 -path ./.git -prune -o \
           -name architecture-reviewer.md -print 2>/dev/null | head -1)"
fi
BASE="${REVIEW_BASE_REF:-origin/main}"

if [ -z "${REVIEW_CMD:-}" ]; then
  echo "review-agent: REVIEW_CMD not set — skipping (soft pass)."
  echo "  Set it to any CLI that takes a prompt on stdin to turn this into a blocking gate,"
  echo "  e.g. REVIEW_CMD=\"claude -p --model sonnet\" or REVIEW_CMD=\"ollama run qwen2.5-coder\"."
  exit 0
fi
if [ ! -f "$AGENT" ]; then
  echo "review-agent: no $AGENT — skipping (the reviewer ships with \`okl scaffold\`)."
  exit 0
fi
# shellcheck disable=SC2086 — REVIEW_CMD is a command line, so word splitting is intended
if ! command -v ${REVIEW_CMD%% *} >/dev/null 2>&1; then
  echo "review-agent: '${REVIEW_CMD%% *}' from REVIEW_CMD is not on PATH — skipping (soft pass)." >&2
  exit 0
fi

diff_text="$(git diff "$BASE"...HEAD 2>/dev/null)"
if [ -z "$diff_text" ]; then
  echo "review-agent: no diff against $BASE — nothing to review."
  exit 0
fi

# Truncate: a very large diff would blow the context budget and produce a worse review than
# a focused one. Reviewing the first N lines and saying so beats silently reviewing a
# truncated diff as though it were whole.
max_lines=4000
total_lines=$(printf '%s' "$diff_text" | wc -l | tr -d ' ')
if [ "$total_lines" -gt "$max_lines" ]; then
  diff_text="$(printf '%s' "$diff_text" | head -n "$max_lines")"
  echo "review-agent: diff is $total_lines lines; reviewing the first $max_lines."
fi

# The checklist lives in the agent file — one source of truth for the rules. Only the OUTPUT
# CONTRACT is supplied here, because the agent is written for interactive use and returns
# prose, which CI cannot act on.
prompt="$(cat <<EOF
You are the architecture reviewer defined below. Apply its checklist to the diff.

$(cat "$AGENT")

--- DIFF UNDER REVIEW ---
$diff_text
--- END DIFF ---

Reply with STRICT JSON and nothing else:
{"findings":[{"severity":"must-fix|consider","file":"path","line":0,"rule":"which checklist item","finding":"one sentence"}]}

Rules for your reply:
- "must-fix" is reserved for a violation of an encoded rule: a restated retraction, a
  resurrected tombstoned identifier, a speculative abstraction, an assert-from-memory claim.
  Style preferences and suggestions are "consider".
- Only report what this diff introduces. Pre-existing issues are out of scope.
- An empty findings list is a valid and common answer. Do not invent findings to seem useful.
EOF
)"

echo "review-agent: reviewing $(printf '%s' "$diff_text" | wc -l | tr -d ' ') lines of diff against $BASE"
raw="$(printf '%s' "$prompt" | $REVIEW_CMD 2>/dev/null)"

# Strip any markdown fence the model adds around the JSON.
json="$(printf '%s' "$raw" | sed -e 's/^```json//' -e 's/^```//' -e '/^```$/d')"

if ! printf '%s' "$json" | python3 -c "import json,sys; json.load(sys.stdin)" 2>/dev/null; then
  # Fail OPEN on an unparseable reply, loudly. A reviewer that cannot be understood has not
  # found anything; blocking every merge on a malformed model response would train people to
  # bypass the gate, which is worse than the gate not firing.
  echo "review-agent: could not parse the reviewer's reply as JSON — not blocking." >&2
  printf '%s\n' "$raw" | head -20 >&2
  exit 0
fi

printf '%s' "$json" | python3 -c '
import json, sys

# %-formatting rather than f-strings: this is embedded in a shell single-quoted string, so
# the keys need double quotes, and a backslash inside an f-string EXPRESSION is a SyntaxError
# before Python 3.12 — which this must survive, since it runs on whatever interpreter the
# consumer has. The first version hit exactly that and exited 1 on every run. A gate that
# always blocks looks identical to a gate that works until someone notices nothing has ever
# passed it.
findings = json.load(sys.stdin).get("findings", [])
must = [f for f in findings if f.get("severity") == "must-fix"]
for f in findings:
    mark = "MUST-FIX" if f.get("severity") == "must-fix" else "consider"
    print("  [%s] %s:%s  %s" % (mark, f.get("file"), f.get("line"), f.get("rule")))
    print("            %s" % f.get("finding"))
if not findings:
    print("  no findings")
print()
print("review-agent: %d must-fix, %d to consider" % (len(must), len(findings) - len(must)))
sys.exit(1 if must else 0)
'
