#!/usr/bin/env bash
# Run the okl loop on this example, for real, with a coding agent: one scratch copy per arm
# (control: no okl; briefed: okl init + the .NET seed packs), the same task in each, then
# the diffs, final messages and the exact briefing land in receipts/<task>/.
#
# Every arm is a real model call. Declare the budget first: N tasks x 2 arms.
#
#   examples/dotnet-minimal-api/run_demo.sh [task_id ...]   # default: every task in tasks.jsonl
#
# Requires: the okl CLI on PATH (pipx install observed-knowledge-ledger), the claude CLI,
# git, the .NET SDK. Writes only under e2e/ (gitignored) and receipts/.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd); ROOT=$(cd "$HERE/../.." && pwd)
# Arms run OUTSIDE this repo, in neutrally named folders. Inside it, Claude Code loads
# okl's own CLAUDE.md into BOTH arms (it reads every CLAUDE.md above the working
# directory), and a folder named <task>-control tells the control arm what it is. Both
# happened in the first runs of this example; the receipts were redone without them.
WORK="${OKL_DEMO_WORKDIR:-${TMPDIR:-/tmp}}"
E="$ROOT/e2e/examples-dotnet-$(date -u +%Y%m%d)"; R="$HERE/receipts"
MODEL="${OKL_DEMO_MODEL:-sonnet}"
PACKS="${OKL_DEMO_PACKS:-dotnet-defects dotnet-decisions dotnet-canon dotnet-review-surfaces}"
TOOLS='Read,Glob,Grep,Write,Edit,Bash(git *),Bash(okl *),Bash(dotnet *)'
ids=("$@"); [ ${#ids[@]} -gt 0 ] || ids=($(python3 -c 'import json,sys;[print(json.loads(l)["id"]) for l in open(sys.argv[1]) if l.strip()]' "$HERE/tasks.jsonl"))
echo "budget: ${#ids[@]} task(s) x 2 arms = $(( ${#ids[@]} * 2 )) model calls ($MODEL)"

task_text() { python3 -c 'import json,sys;[print(json.loads(l)["task"]) for l in open(sys.argv[1]) if l.strip() and json.loads(l)["id"]==sys.argv[2]]' "$HERE/tasks.jsonl" "$1"; }

fresh_copy() {  # $1 = arm dir
  rm -rf "$1"; mkdir -p "$1"
  # .NET 10's `dotnet new sln` writes .slnx; older SDKs write .sln. Copy whichever exists.
  cp -R "$HERE/src" "$HERE/tests" "$HERE"/OrdersApi.sln* "$HERE/.gitignore" "$1/"
  rm -rf "$1"/src/bin "$1"/src/obj "$1"/tests/bin "$1"/tests/obj
  mkdir -p "$1/.claude"
  git -C "$1" init -q; git -C "$1" -c user.email=demo@okl -c user.name=okl-demo add -A
  git -C "$1" -c user.email=demo@okl -c user.name=okl-demo commit -qm "example app" >/dev/null
}

for id in "${ids[@]}"; do
  task=$(task_text "$id"); [ -n "$task" ] || { echo "no task '$id' in tasks.jsonl" >&2; exit 2; }
  out="$R/$id"; mkdir -p "$out"; : > "$out/arms.txt"
  for arm in control briefed; do
    d="$(mktemp -d "$WORK/tmp.XXXXXXXX")/orders-api"; fresh_copy "$d"
    echo "$arm $d" >> "$out/arms.txt"
    if [ "$arm" = briefed ]; then
      ( cd "$d" && okl init --repo orders-api --interests dotnet,security,method >/dev/null 2>&1
        for p in $PACKS; do okl seed "$p" >/dev/null 2>&1; done
        # pre-flight, no model call: the briefing this arm will get, kept as a receipt
        okl check --task "$task" --format agent > "$out/briefing.md" 2>/dev/null )
      git -C "$d" -c user.email=demo@okl -c user.name=okl-demo add -A >/dev/null
      git -C "$d" -c user.email=demo@okl -c user.name=okl-demo commit -qm "okl init" >/dev/null
    fi
    echo "== $id / $arm"
    ( cd "$d" && printf '%s' "$task" | OKL_DISABLED_HOOKS=encode \
        perl -e 'alarm 1200; exec @ARGV' -- claude -p --model "$MODEL" --allowedTools "$TOOLS" \
        > "$out/session-$arm.txt" 2>/dev/null ) || echo "  (session exited non-zero)"
    git -C "$d" add -A >/dev/null; git -C "$d" diff --cached -- . ':!okl-drift.json' > "$out/diff-$arm.patch"
    echo "  $(wc -l < "$out/diff-$arm.patch" | tr -d ' ') diff lines"
  done
done
echo "receipts in $R"
