#!/usr/bin/env bash
# Run the okl loop on this example, for real, with a coding agent: one scratch copy per arm
# (control: no okl; briefed: okl init + the matching seed packs), the same task in each,
# then the diffs and transcripts land in receipts/<task>/ for a person to read.
#
# Every arm is a real model call. Declare the budget first: N tasks x 2 arms.
#
#   examples/python-fastapi/run_demo.sh [task_id ...]      # default: every task in tasks.jsonl
#
# Requires: the okl CLI on PATH (pipx install observed-knowledge-ledger), the claude CLI,
# git. Runs from anywhere; writes only under e2e/ (gitignored) and receipts/.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd)
E="$ROOT/e2e/examples-python-$(date -u +%Y%m%d)"; R="$HERE/receipts"
MODEL="${OKL_DEMO_MODEL:-sonnet}"
PACKS="${OKL_DEMO_PACKS:-dotnet-defects dotnet-decisions dotnet-canon rag-defects geospatial-enforcement-defects}"
TOOLS='Read,Glob,Grep,Write,Edit,Bash(git *),Bash(okl *),Bash(python *),Bash(pytest *)'
ids=("$@"); [ ${#ids[@]} -gt 0 ] || ids=($(python3 -c 'import json,sys;[print(json.loads(l)["id"]) for l in open(sys.argv[1]) if l.strip()]' "$HERE/tasks.jsonl"))
echo "budget: ${#ids[@]} task(s) x 2 arms = $(( ${#ids[@]} * 2 )) model calls ($MODEL)"

task_text() { python3 -c 'import json,sys;[print(json.loads(l)["task"]) for l in open(sys.argv[1]) if l.strip() and json.loads(l)["id"]==sys.argv[2]]' "$HERE/tasks.jsonl" "$1"; }

fresh_copy() {  # $1 = arm dir
  rm -rf "$1"; mkdir -p "$1"; cp -R "$HERE/app" "$HERE/tests" "$HERE/pyproject.toml" "$1/"
  mkdir -p "$1/.claude"
  git -C "$1" init -q; git -C "$1" -c user.email=demo@okl -c user.name=okl-demo add -A
  git -C "$1" -c user.email=demo@okl -c user.name=okl-demo commit -qm "example app" >/dev/null
}

for id in "${ids[@]}"; do
  task=$(task_text "$id"); [ -n "$task" ] || { echo "no task '$id' in tasks.jsonl" >&2; exit 2; }
  out="$R/$id"; mkdir -p "$out"
  for arm in control briefed; do
    d="$E/$id-$arm"; fresh_copy "$d"
    if [ "$arm" = briefed ]; then
      ( cd "$d" && okl init --repo orders-api --interests python,security,method >/dev/null 2>&1
        for p in $PACKS; do okl seed "$p" >/dev/null 2>&1; done
        # pre-flight, no model call: the briefing this arm will get, kept as a receipt
        okl check --task "$task" --format agent > "$out/briefing.md" 2>/dev/null )
      git -C "$d" -c user.email=demo@okl -c user.name=okl-demo add -A >/dev/null
      git -C "$d" -c user.email=demo@okl -c user.name=okl-demo commit -qm "okl init" >/dev/null
    fi
    echo "== $id / $arm"
    ( cd "$d" && printf '%s' "$task" | OKL_DISABLED_HOOKS=encode \
        perl -e 'alarm 900; exec @ARGV' -- claude -p --model "$MODEL" --allowedTools "$TOOLS" \
        > "$out/session-$arm.txt" 2>/dev/null ) || echo "  (session exited non-zero)"
    git -C "$d" add -A >/dev/null; git -C "$d" diff --cached -- . ':!okl-drift.json' > "$out/diff-$arm.patch"
    echo "  $(wc -l < "$out/diff-$arm.patch" | tr -d ' ') diff lines"
  done
done
echo "receipts in $R"
