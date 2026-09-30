# Getting started with okl

okl keeps what your codebase has learned — its conventions, the decisions made on purpose,
the mistakes already made once, and the claims its docs make — and puts the relevant ones
in front of Claude Code before every task. Each entry is proven by a check, and CI flags it
when the files it governs change.

This guide gets you from nothing to that loop working, then shows the two habits that make
it pay off: **adding to the canon as you build a feature**, and **putting your docs in the
canon so they cannot drift silently**. Every command here was run, in this order, in a fresh
repository. The running example is a small service called `shop`.

---

## 1. Set up (about 10 minutes)

### Install the CLI

```bash
pipx install 'observed-knowledge-ledger[mcp]'
```

The PyPI name differs (PyPI refuses `okl` as confusable with `oki`); everything you type
afterwards is `okl`.

### Wire the repository

From the root of your repo:

```bash
okl init --repo shop --interests python,security --dry-run   # lists every file; writes nothing
okl init --repo shop --interests python,security
```

- `--repo` names this repo in the store. Always pass the same name when you re-run `init`.
- `--interests` are the subjects this repo cares about, from a closed list:
  `agent-safety data-quality dotnet eval-integrity frontend geospatial messaging method
  prose python python-rag react retrieval-design security`. Shared (org) lessons whose tags
  share none of these stay out of your briefings; untagged lessons always come through.
- `init` wires Claude Code when the repo has a `.claude/` folder or `claude` is on your
  PATH (`--claude` forces it, `--no-claude` skips it). It writes `.okl/` (config and the
  local store, gitignored), two hooks in `.claude/hooks/` registered in
  `.claude/settings.json`, `.mcp.json`, and a CI workflow.

**Prefer the Claude Code plugin?** Install it *before* `init` — `/plugin marketplace add
emeraldleaf/okl`, then `/plugin install okl@okl` — and `init` leaves the hooks to the
plugin. The plugin's hooks do nothing in a repo that has not run `okl init`, so installing
it for your user does not disturb your other projects.

### Give it something to know

An empty store briefs nothing, and says so. Two ways to fill it — do both:

**Your own rules (the part that pays).** Record one convention this repo already has, right
now. Section 2 shows the full habit; one record is enough to see the loop work:

```bash
okl record --type Rule --scope repo --id order-owner-scope \
  --title "Order lookups are scoped to the signed-in customer" \
  --symptom "an endpoint fetches an order by id with no owner filter" \
  --body "cause: order ids are sequential, so any id is guessable" \
  --fix "filter by the caller's customer id in the query; return 404 on no match"
```

**Bundled packs (a head start).** `okl seed` lists them. They are real lessons from .NET,
Python RAG, React and geospatial codebases, each tagged by subject. Many are portable: the
security lessons in `dotnet-defects` (IDOR, trusting a client-supplied price) apply to any
web service, and reach you if you declared `security`.

```bash
okl seed                     # lists the packs, their subjects, and which match your interests
okl seed dotnet-defects      # import one by name
```

A pack whose subjects share nothing with your `--interests` imports fine but never shows
up in your briefings — the interest filter is doing its job. If `okl seed` marks nothing as
a match for your stack, rely on your own records and the portable packs. With `okl scaffold .`
you also get a `/seed-from-codebase` command: your agent proposes cited records from this
repo's own code, for you to review before importing.

### Check it works

```bash
okl check --task "add an endpoint that returns an order for the signed-in customer"
okl doctor
```

You should see a briefing that leads with **FIX:** lines — your own rule, and the security
lessons if you seeded them. If it says the store is empty, or matches nothing, go back one
step. `okl doctor` reports other agent-memory tools that would collide with okl's hooks, and
flags okl wired twice (plugin and project hooks).

### Commit the wiring

```bash
git add .claude .mcp.json .github/workflows/okl-verify.yml
git commit -m "Wire okl"
```

Not `.okl/`: it holds the local store and machine-specific paths, and `init` gitignores it.

From now on you prompt Claude Code as usual. The briefing arrives on its own.

---

## 2. Add to the canon as you build a feature

The store is only as useful as what you put in it. The habit is small: **when something is
worth not relearning, record it the moment you learn it.** Here is one feature, start to
finish — adding discount codes to `shop`.

### Before you start

Just prompt. The pre-task hook runs `okl check` on what you typed and puts the matching
lessons in the agent's context. To see what it will get, run it yourself:

```bash
okl check --task "add discount codes to checkout"
```

### While you build: record decisions, rules and bugs as they happen

**A decision** — something chosen on purpose that should not be quietly reversed:

```bash
okl record --type Decision --scope repo --id discount-single-use \
  --title "Discount codes are single-use per customer" \
  --body "why: marketing budgets per customer; reuse was abused in the 2025 pilot"
```

**A rule** — a convention, with the symptom that should trigger it and the fix. Add
`--files` when it governs specific code; that is what lets CI notice when the code moves:

```bash
okl record --type Rule --scope repo --id discount-server-side \
  --title "Discount amounts are computed server-side, never taken from the request" \
  --symptom "a request body carries a discount, amount or total field" \
  --body "cause: a client can send any amount it likes" \
  --fix "accept only the code; look the discount up and compute totals on the server" \
  --files "app/checkout.py"
```

**A defect** — a bug you just fixed, so the next session does not reintroduce it:

```bash
okl record --type Defect --scope repo --id discount-rounding \
  --title "Percentage discounts rounded per line, not per order" \
  --symptom "order totals off by a cent on multi-line orders with a percent code" \
  --body "cause: round() applied inside the line loop" \
  --fix "sum unrounded line amounts, round the order total once"
```

Three choices to make each time:

- **`--id`** — a short stable key. Recording the same id again updates that record instead
  of adding a near-duplicate (there is no delete command, on purpose).
- **`--scope repo`** stays in this repo. **`--scope org`** reaches every repo that shares
  your store — use it for lessons true anywhere, and add `--tags` from the list above.
- **`--applies-to`** — leave it unset unless the lesson is false off one stack. Unset is
  the safe default.

Other record types you will reach for: **Gate** (an automated check, linked to what it
catches with `okl link <gate-id> CATCHES <defect-id>`), **Tombstone** (a retired name that
must not come back), **Retraction** (a claim withdrawn).

### When the session ends

If the session changed files, the Stop hook asks once: *did this session learn anything
worth recording?* It lists commands that failed during the session as candidates. Record
what is worth keeping, or say explicitly that nothing was.

### Prove it: a lesson is verified by running a check

```bash
okl verify discount-server-side \
  --run "pytest -q tests/test_checkout.py" --expect "passed"
```

`okl verify` runs the check and stamps the lesson only if it exits 0 **and** its output
contains the `--expect` text. The command and result are stored as the evidence. There is
no way to mark a lesson verified without running something: `okl record --verified` is
refused.

### Commit, in this order

1. Commit the code change.
2. Run `okl verify` for any lesson whose governed files you touched (`okl drift` lists them).
3. Commit `okl-drift.json`, which `okl verify` refreshes.

**The first time** a lesson has `--files`, create that file once, then commit it:

```bash
okl export --drift
git add okl-drift.json && git commit -m "okl: drift snapshot"
```

CI's drift gate reads this committed snapshot (your store is not in git). Until the first
lesson governs files there is nothing to snapshot, and CI warns "Drift not checked" —
expected. Do not commit a snapshot with zero rules in it; CI treats that as broken.

---

## 3. Put your docs in the canon, so they cannot drift silently

A README, an architecture doc or a diagram is a set of claims about code. When the code
moves, the claims go stale and nothing says so. okl cannot read a paragraph and judge it —
but it can hold a claim to a check. The pattern:

> **A doc claim is a Rule that governs both the doc and the code it describes, verified by a
> check that fails if the claim is false.**

Govern **both** files: then editing either one re-opens the question.

### Example: the README documents a flag

The README says `shop serve --port` exists. Record that claim against the README and the
code that defines the flag, with a check that fails if either side stops matching:

```bash
okl record --type Rule --scope repo --id doc-readme-serve-port \
  --title "README's 'shop serve --port' matches the real CLI" \
  --symptom "a README command or flag that the CLI no longer has" \
  --fix "update the README in the same change as the CLI, then re-verify" \
  --files "README.md,app/cli.py"

okl verify doc-readme-serve-port \
  --run "bash -c 'grep -q -- \"shop serve --port\" README.md && python -m app.cli serve --help | grep -q -- --port && echo DOC MATCHES CODE'" \
  --expect "DOC MATCHES CODE"
```

Now, when anyone edits `README.md` or `app/cli.py`:

```bash
okl drift
# OKL drift: 1 rule(s) may be stale (source changed after verification):
#   • [doc-readme-serve-port] README's 'shop serve --port' matches the real CLI
```

Locally and in CI (from the committed snapshot) that stays red until someone re-runs the
check. If the check passes, `okl verify` again and commit the refreshed `okl-drift.json`. If
it fails, the doc or the code is wrong, and you fix whichever is.

### Writing checks that mean something

- **Test the claim, not the words.** "The README contains `--port`" passes forever. "The
  README says `--port` *and* the CLI accepts `--port`" fails the day they disagree.
- **Prefer checks that fail on the bad state:** run the documented command, compare a
  documented number with the one the code produces, grep code for what an architecture doc
  says must never happen.
- **Existing tests are often the best check.** An architecture decision ("handlers never
  import the database module") is usually one test away from being provable.

### Diagrams and orphaned docs

`okl scaffold .` adds repo gates you can run in CI (`bash gates/run-gates.sh`): broken
internal links, docs or images nothing links to, and retracted claims or retired names
reappearing. For a diagram, record a Rule that governs the diagram's source and the code it
depicts, exactly as above — and if a diagram states numbers, generate it from the system
rather than drawing it by hand.

### What this does not do

okl does not read your docs and decide they are wrong. A claim nobody wired to a check is
not watched — which is exactly how docs drift in a repo that uses okl everywhere else. Wire
the claims that would hurt most if they were wrong: install steps, commands, flags, security
statements, architecture rules, published numbers.

---

## When something is off

| You see | It means | Do |
|---|---|---|
| Prompts are not briefed | this repo has no `.okl/config.json`; the hooks step aside | run `okl init` here |
| A prompt is blocked with "OKL CHECK DID NOT RUN" | okl is set up here but could not run; the message says why | fix the cause, or start the session with `OKL_OFFLINE=1` |
| `claude -p` prints the answer to "what did we learn?" | the Stop hook replaced the printed answer | run headless sessions with `OKL_DISABLED_HOOKS=encode` |
| CI warns "Drift not checked" | no `okl-drift.json` committed yet | expected until a lesson has `--files`; then `okl export --drift` |
| CI fails with "NOTHING CHECKED" | a snapshot with zero rules is committed | remove it, or record a lesson with `--files` and re-export |
| `okl drift` is red right after `okl record --files` | a new rule is unverified until its first `okl verify` | run its check with `okl verify` |

More: the [README](../README.md) covers costs, scopes, the shared service and the MCP tools;
[DEPLOY](DEPLOY.md) covers running a shared store for a team.
