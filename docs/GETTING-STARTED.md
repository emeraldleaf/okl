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

Needs Python 3.10+ (and git for drift detection). Tested on macOS and Linux. **Windows is untested**: the core
should work, but the Claude Code hooks likely need fixes there
([#85](https://github.com/emeraldleaf/okl/issues/85)).

### Wire the repository

From the root of your repo:

```bash
okl init --repo shop --dry-run   # lists every file it would write, and what it detected
okl init --repo shop
```

- `--repo` names this repo in the store. Always pass the same name when you re-run `init`.
- **It detects your stack** from the files every stack keeps (`*.csproj`/`*.sln`,
  `package.json`, `pyproject.toml`/`requirements.txt`) and sets this repo's *interests* —
  the subjects its briefings cover — to that stack plus `security` and `method`. To choose
  your own, pass `--interests` from this list: `agent-safety data-quality dotnet
  eval-integrity frontend geospatial messaging method prose python python-rag react
  retrieval-design security`.
- **It fills the store** with 20 starter lessons that hold on almost any codebase (web
  security, CI, docs, verification) plus the bundled packs for your stack, so your very
  first prompt is briefed. `--no-seed` leaves it empty.
- `init` wires Claude Code when the repo has a `.claude/` folder or `claude` is on your
  PATH (`--claude` forces it, `--no-claude` skips it). It writes `.okl/` (config and the
  local store, gitignored), two hooks in `.claude/hooks/` registered in
  `.claude/settings.json`, `.mcp.json`, and a CI workflow.

**Prefer the Claude Code plugin?** Install it *before* `init` — `/plugin marketplace add
emeraldleaf/okl`, then `/plugin install okl@okl` — and `init` leaves the hooks to the
plugin. The plugin's hooks do nothing in a repo that has not run `okl init`, so installing
it for your user does not disturb your other projects.

### Add your first rule of your own

The starter lessons are generic. What makes okl pay is what only your codebase knows. Open
your agent in the repo and tell it one convention this codebase already has:

> Record an okl rule for this repo: order lookups are always scoped to the signed-in
> customer, because order ids are sequential. Governs app/orders.py.

The agent records it through okl's `okl_record` MCP tool — any agent that speaks MCP has
it — or by running `okl record`. In Claude Code, `/record` drafts the lesson, shows it to
you and records it once you confirm. Section 2 shows what a good lesson contains and the CLI
underneath.

To start from what the code already does rather than from memory, run
`/seed-from-codebase` (Claude Code): the agent reads the repo and proposes cited lessons
into a file you review before importing anything (`okl scaffold .` adds it outside the plugin). `okl seed`
lists more bundled packs; `okl seed <name>` imports one.

### Check it works

```bash
okl check --task "add an endpoint that returns an order for the signed-in customer"
okl doctor
```

You should see a briefing that leads with **FIX:** lines, your own rule among them. In
Claude Code you will also see one line per prompt, like *okl · briefed 9 lesson(s): Missing
ownership scope check…; …* — that is okl telling you what it put in front of the agent
(`OKL_QUIET=1` turns it off). If the store is empty or nothing matched, see the step above. `okl doctor` reports other agent-memory tools that would collide with okl's hooks, and
flags okl wired twice (plugin and project hooks).

### Commit the wiring

```bash
git add .claude .mcp.json .github/workflows/okl-verify.yml
git commit -m "Wire okl"
```

Not `.okl/`: it holds the local store and machine-specific paths, and `init` gitignores it.

From now on you prompt Claude Code as usual. The briefing arrives on its own.

### Using another agent

The store, the CLI, the MCP tools and the CI drift gate do not depend on Claude Code. The
automatic parts do: the per-prompt briefing and the end-of-session question are Claude Code
hooks. With any other agent that supports MCP (Cursor, Codex, Copilot, Gemini CLI…):

1. Register okl's MCP server in that agent's config — the command is `okl mcp` (stdio).
   It exposes `okl_check`, `okl_record` and `okl_search`.
2. Add one line to the agent's instruction file (`AGENTS.md`, `.cursorrules`…): *Before
   each task, call `okl_check` with the task description and follow what it returns. When
   we learn something worth keeping, record it with `okl_record`.*

That gives the same briefing and recording, triggered by the instruction file instead of a
hook. Agents without MCP can run `okl check --task "…"` and `okl record` as shell commands.

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

### While you build: say it, and your agent records it

You will not type most lessons. The moment something is worth not relearning — a choice
made on purpose, a convention the agent just broke, a bug you just fixed — say so in the
session:

> That's a decision: discount codes are single-use per customer, because reuse was
> abused in the 2025 pilot. Record it.

> Record a rule: discount amounts are computed server-side, never taken from the request.
> It governs app/checkout.py.

> Record the rounding bug we just fixed so it doesn't come back.

The agent turns each into a lesson with okl's `okl_record` MCP tool, or with `okl record`
if it has no MCP. In Claude Code, `/record` does the same with a checklist: it drafts from
the conversation, shows you the draft, and records it only when you confirm.

**When the session ends** in Claude Code, if it changed files, the Stop hook asks once:
*did this session learn anything worth recording?* It lists commands that failed during the
session as candidates. That question is the safety net for the lessons nobody stopped to say out loud;
answer it, or say explicitly that nothing was worth keeping.

### What a good lesson contains

Whoever writes it, you or the agent, a lesson is one record. Check the draft for these:

| Field | What it is | Example |
|---|---|---|
| type | **Decision** (made on purpose), **Rule** (a convention), **Defect** (a bug fixed) | Rule |
| id | a short stable key; recording the same id again updates the lesson instead of duplicating it | `discount-server-side` |
| symptom → fix | what an agent would see or do that should trigger it, and what to do instead — this is the line the briefing leads with | "a request body carries a discount amount" → "accept only the code; compute totals on the server" |
| files | the code it governs; lets CI notice when that code changes | `app/checkout.py` |
| scope | `repo` stays here; `org` reaches every repo sharing your store — only for lessons true anywhere | repo |

Leave `applies_to` unset unless the lesson is false off one stack; unset is the safe
default. Tags come from the list in section 1. Other types you will reach for: **Gate** (an
automated check, linked to what it catches with `okl link <gate-id> CATCHES <defect-id>`),
**Tombstone** (a retired name that must not come back), **Retraction** (a claim withdrawn).

### How hard to enforce it

Every lesson reaches the briefing. Beyond that, pick the softest level that holds — the
agent proposes one when it records, and you can overrule it:

| The lesson… | Enforcement | How |
|---|---|---|
| is useful context for some tasks | briefing only | nothing more to do |
| governs specific code | watched by CI | give it `files`, prove it with `okl verify`; CI's drift gate goes red when that code changes |
| has been broken before, or is costly when broken | build-breaking | a test or CI check that fails the build — a sterner lesson will not stop a repeat |
| is needed in every session, whatever the task | always-on | a line in `CLAUDE.md` / `AGENTS.md` — rare |

Move a lesson down the table only when it earns it: one that keeps being broken gets a
check, not a longer paragraph.

### Underneath: the CLI

Everything above ends up as an `okl record` call. You can run it yourself — in scripts, in
CI, or when you know exactly what you want:

```bash
okl record --type Rule --scope repo --id discount-server-side \
  --title "Discount amounts are computed server-side, never taken from the request" \
  --symptom "a request body carries a discount, amount or total field" \
  --body "cause: a client can send any amount it likes" \
  --fix "accept only the code; look the discount up and compute totals on the server" \
  --files "app/checkout.py"
```

The same record from a Decision needs only `--type Decision`, `--title` and a `--body`
starting `why:`. There is no delete command, on purpose; re-record the id to correct a
lesson.

### Store records vs. CLAUDE.md / AGENTS.md

Your agent's instruction file (`CLAUDE.md`, `AGENTS.md`, `.cursorrules`…) is loaded into
every session in full, so keep it to the few
rules that are always relevant. Everything that matters only for some tasks belongs in the
store, where the briefing picks the relevant lessons for each prompt and CI can check them.
When you are about to add a paragraph to that file, ask whether it should be a lesson
instead. It usually should.

Some things belong in neither. A procedure (how to release, migrate or set up) is read
whole and in order, so it goes in a skill, runbook or script. Formatting and style go to a
formatter or linter, which enforces them on every line. An open bug goes in your issue
tracker until it is fixed; the lesson comes after. Secrets never go in the store: it is
shared, and its lessons are copied into agent context.

### Prove it: a lesson is verified by running a check

A lesson counts as verified when a check actually ran and passed. The easy way is to ask
your agent in plain words: *"prove the discount-server-side lesson"*, or after a change,
*"re-check the stale okl lessons"*. It reads each lesson, finds or writes a test that fails
when the lesson is broken, runs it, and records the result.

Underneath, that is one command with three parts:

| Part | What it is | Where it comes from |
|---|---|---|
| the lesson's id | `discount-server-side` | the `--id` it was recorded with; `okl drift` and the briefing show it in brackets |
| `--run` | a command that fails if the lesson is broken, usually a test | a test that already exists, or one written for the lesson |
| `--expect` | a word that appears in the output when it passes | `passed` for pytest |

```bash
okl verify discount-server-side \
  --run "pytest -q tests/test_checkout.py" --expect "passed"
```

Not sure what to run? `okl verify <id>` on its own shows the lesson, the files it covers and
the tests that already mention them, and stamps nothing. If none does, that is a search
miss, not proof: a test can cover a lesson by driving the command without naming its files.
Look before writing a new check, or hand both jobs to your agent.

`okl verify` stamps the lesson only if the check exits 0 and, when you give `--expect`, its
output contains that text. Give it: exit 0 alone can come from a check that ran nothing. The command is stored as the evidence, so the next time the lesson goes
stale, `okl reverify` re-runs it with no parameters. There is no way to mark a lesson
verified without running something: `okl record --verified` is refused.

### Commit, in this order

1. Commit the code change.
2. Re-check the lessons whose governed files you touched: `okl reverify` lists each one's
   stored check and, once you confirm, re-runs them (`--yes` skips the question).
3. Commit `okl-drift.json`, which `okl verify` / `okl reverify` keep up to date.

`okl-drift.json` is what CI's drift gate reads (your store is not in git). `okl verify`
creates it the first time a lesson with `--files` is verified — commit it then. Until a
lesson governs files there is nothing to snapshot, and CI warns "Drift not checked" —
expected.

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
  --run "bash -c 'grep -q -- \"shop serve --port\" README.md && python3 -m app.cli serve --help | grep -q -- --port && echo DOC MATCHES CODE'" \
  --expect "DOC MATCHES CODE"
```

Now, when anyone edits `README.md` or `app/cli.py`:

```bash
okl drift
# OKL drift: 1 rule(s) may be stale (source changed after verification):
#   • [doc-readme-serve-port] README's 'shop serve --port' matches the real CLI
```

Locally and in CI (from the committed snapshot) that stays red until someone re-runs the
check. `okl reverify` re-runs the stored check: if it passes, commit the refreshed
`okl-drift.json`; if it fails, the doc or the code is wrong, and you fix whichever is.

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

## 4. Run the drift gate without GitHub Actions

`okl init` writes a GitHub Actions workflow, but the gate itself is one command:

```bash
okl drift --gate --snapshot okl-drift.json
```

It exits **0** when nothing has drifted, **1** when a lesson's governed code changed since
its last check (fail the build), and **2** when it could not check at all, for example when
no `okl-drift.json` is committed yet. Run it in any CI, or with no CI at all.

### Any CI system

Four things matter, whichever CI you use:

1. **Full git history in the checkout.** The gate compares each lesson's governed files at
   the commit its check passed at with the same files now. A shallow clone does not have
   that commit, so the gate falls back to comparing commit times, and in a clone with one
   commit every file looks freshly changed: okl's own `main`, cloned with `--depth 1`,
   reports all 15 of its lessons stale, and a full clone reports none (measured
   2026-10-06 at `4f830b9`).
   GitHub: `fetch-depth: 0`. GitLab: `GIT_DEPTH: 0`. Azure Pipelines: `fetchDepth: 0`.
   Jenkins: leave shallow clone off.
2. **Merge commits, not squash or rebase.** Squash and rebase replace the commits a check
   passed at with new ones, so main cannot find them, falls back to times, and goes red
   right after a green PR. This is a repository setting, not a CI one.
3. **The committed `okl-drift.json`**, or a shared store through the `OKL_SERVICE_URL` and
   `OKL_TOKEN` environment variables.
4. **Python 3.10 or newer.** Pin okl to the version you run locally, so a new release
   cannot change the gate under you. `okl --version` prints it from the release after
   0.7.9; on 0.7.9 and earlier, `pip show observed-knowledge-ledger` (or `uv tool list`)
   does.

GitLab CI:

```yaml
okl-drift:
  image: python:3.13
  variables:
    GIT_DEPTH: 0
    OKL_VERSION: "0.7.9"   # the version you run locally
  script:
    - pip install "observed-knowledge-ledger==$OKL_VERSION"
    - okl drift --gate --snapshot okl-drift.json
```

Azure Pipelines:

```yaml
steps:
  - checkout: self
    fetchDepth: 0
  - task: UsePythonVersion@0
    inputs:
      versionSpec: "3.13"
  - script: |
      pip install "observed-knowledge-ledger==0.7.9"
      okl drift --gate --snapshot okl-drift.json
    displayName: okl drift gate
```

On GitHub, a self-hosted runner can run the same workflow without using your Actions
minutes.

The GitLab and Azure snippets follow those systems' documented settings but have not been
run there yet. The shallow-clone result above and the hook below were run as shown (the hook
on 2026-10-06, against okl 0.7.9: a clean push went through, a drifted lesson blocked it,
and a repo with no store pushed). If one needs a change on your CI, an issue or PR is welcome.

### No CI: a pre-push hook

For a solo project, a git hook can run the gate against your local store before every push:

```bash
#!/usr/bin/env bash
# .git/hooks/pre-push: block the push only when lessons have actually drifted
okl drift --gate; rc=$?
if [ "$rc" -eq 1 ]; then echo "okl: lessons drifted; run 'okl reverify' first" >&2; exit 1; fi
exit 0   # 0 = clean; 2 = couldn't check (no store); don't block on that
```

Save it as `.git/hooks/pre-push` and run `chmod +x .git/hooks/pre-push`. If your repo sets
`core.hooksPath` (Husky and similar tools do), put it in that directory instead. Git runs
hooks with your shell's `PATH`; if a GUI client cannot find `okl`, use its full path
(`command -v okl` prints it). Installing this hook from `okl init` is tracked in
[#90](https://github.com/emeraldleaf/okl/issues/90).

A local hook is an early warning, not a merge gate: each developer installs it themselves,
`git push --no-verify` skips it, and a teammate without it is not checked. On a team, keep
a CI gate as well.

---

## When something is off

| You see | It means | Do |
|---|---|---|
| `OKL: not configured: no .okl/config.json here or in any parent directory…` (exit 2) | Nothing names a store here: a fresh clone, a git worktree, or the wrong directory | Run `okl init` here, `okl connect <url>`, or set `OKL_DATABASE_URL` |
| Prompts are not briefed | this repo has no `.okl/config.json`; the hooks step aside | run `okl init` here |
| A prompt is blocked with "OKL CHECK DID NOT RUN" | okl is set up here but could not run; the message says why | fix the cause, or start the session with `OKL_OFFLINE=1` |
| `claude -p` prints the answer to "what did we learn?" | the Stop hook replaced the printed answer | run headless sessions with `OKL_DISABLED_HOOKS=encode` |
| CI warns "Drift not checked" | no `okl-drift.json` committed yet | expected until a lesson with `--files` is verified; then commit the file `okl verify` creates |
| CI fails with "NOTHING CHECKED" | a snapshot with zero rules is committed | remove it, or record a lesson with `--files` and re-export |
| `okl drift` is red right after `okl record --files` | a new rule is unverified until its first `okl verify` | run its check with `okl verify` |
| `okl drift` is red after you changed code | lessons governing those files need re-checking | `okl reverify` |
| A briefed lesson is marked *STALE*, *UNVERIFIED* or *UNPROVEN* | its governed files changed after its last check, no check has passed yet, or its stamp has no observed check behind it | `okl reverify` re-runs stored checks; a lesson with none needs one first: ask your agent to re-check it, or run `okl verify <id>` to see what to run |
| `okl drift` lists lessons "last verified on a commit outside this branch's history" | one local store serves every branch, and those lessons were checked on another one | `okl reverify` re-checks them on this branch; until then their evidence depends on that branch still existing |
| Every lesson is drifted in CI, but `okl drift` is clean locally | the CI checkout is shallow, so every file looks freshly changed | fetch full history (section 4) |

More: the [README](../README.md) covers costs, scopes, the shared service and the MCP tools;
[DEPLOY](DEPLOY.md) covers running a shared store for a team.
