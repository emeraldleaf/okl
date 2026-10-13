#!/usr/bin/env bash
# Runs the story okl-anatomy.html tells, one lesson all the way round, in a throwaway repo,
# and prints okl's output at each step. The sheet's terminal lines are copied from this
# output, trimmed where they mark it (…), so when okl's wording changes, run this again and
# copy the new lines in rather than editing them by hand.
#
# Needs okl, git and pytest on PATH. Works in a fresh temp directory with its own store and
# deletes it afterwards (KEEP=1 keeps it); OKL_DATABASE_URL is cleared so no shared store is
# touched.
#
#   bash docs/overview/anatomy-story.sh
set -uo pipefail
unset OKL_DATABASE_URL
export PYTHONUNBUFFERED=1   # okl's stdout and stderr in the order a terminal shows them
W=$(mktemp -d "${TMPDIR:-/tmp}/okl-anatomy.XXXXXX")
[ "${KEEP:-0}" = 1 ] || trap 'rm -rf "$W"' EXIT
D="$W/orders-api"; mkdir -p "$D/app" "$D/tests"
TASK="Add an endpoint that returns one order by id for the signed-in customer"
step() { printf '\n===== %s\n' "$1"; }

: > "$D/app/__init__.py"
cat > "$D/app/orders.py" <<'EOF'
ORDERS = {
    1: {"id": 1, "owner": "alice", "item": "widget"},
    2: {"id": 2, "owner": "bob", "item": "gizmo"},
}


def get_order(order_id: int, user: str) -> dict | None:
    """One order, only if the signed-in customer owns it."""
    order = ORDERS.get(order_id)
    return order if order and order["owner"] == user else None
EOF
cat > "$D/tests/test_orders.py" <<'EOF'
from app.orders import get_order


def test_an_order_is_visible_to_its_owner():
    assert get_order(1, "alice")["item"] == "widget"


def test_another_customers_order_is_not_found():
    assert get_order(1, "bob") is None
EOF
printf '[tool.pytest.ini_options]\npythonpath = ["."]\n' > "$D/pyproject.toml"
printf '__pycache__/\n' > "$D/.gitignore"
git init -q --bare "$W/remote.git"
cd "$D" || exit 1
git init -q; git symbolic-ref HEAD refs/heads/main
git config user.email story@okl; git config user.name okl-story
git add -A; git commit -qm "orders api"; git remote add origin "$W/remote.git"; git push -q origin main

step "okl $(okl --version | awk '{print $2}'): init"
okl init --repo orders-api --no-claude --interests python,security

step "2 record"
okl record --type Rule --scope repo --id order_scope --files app/orders.py --tags security \
  --title "Order lookups are scoped to the signed-in customer" \
  --symptom "an order is fetched by id with no check that it belongs to the caller" \
  --fix "filter the lookup by the caller's id; another customer's order is a 404, not a 403" \
  --body "Without the owner check, any signed-in user can read any order by trying ids (IDOR, CWE-639)."

step "3 verify"
okl verify order_scope --run "pytest -q" --expect passed

step "4 brief: what the person sees, then the agent's context"
okl check --task "$TASK" --format hook \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["systemMessage"])'
okl check --task "$TASK" --format agent

step "5 the change, and the push"
perl -pi -e 's/^    return order if order and order\["owner"\] == user else None$/    return order/' app/orders.py
git diff
git commit -qam "simplify get_order"
git push origin main 2>&1

step "5 the briefing after the change"
okl check --task "$TASK" --format agent | grep -A2 'order_scope'

step "6 reverify"
okl reverify --yes

step "6 the fix, and the push"
perl -pi -e 's/^    return order$/    return order if order and order["owner"] == user else None/' app/orders.py
git commit -qam "restore the owner check"
okl reverify --yes
git push origin main 2>&1

step "6 recap: what the session-end question lists"
okl recap --since "$(git log --reverse --format=%cI | head -1)"
