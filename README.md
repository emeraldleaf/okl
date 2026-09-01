# okl — a shared knowledge layer for AI-assisted engineering

> A small database of the specific lessons a codebase has learned — the bugs it
> keeps almost-reintroducing, the checks that catch them, the rules that must not
> be broken — plus a command that hands the relevant ones to a coding agent (or a
> person) **before** they start a task, so the same mistake isn't made twice.

```bash
pipx install org-knowledge-layer   # the distribution name on PyPI
okl --help                         # the command, the import package, and the repo are all `okl`
```

*(PyPI rejects `okl` itself as confusable with the existing `oki`, so only the install
line differs — everything you type afterwards is `okl`.)*

## The problem it solves

A team (or an AI agent) fixes a subtle bug, learns *why* it happened, and writes a
rule to prevent it. Weeks later, in a different file — or a different repository —
the same class of bug comes back, because the person or agent doing the new work
never saw that rule. The knowledge existed; it just wasn't in front of whoever
needed it, at the moment they needed it.

`okl` fixes that with one move: **the relevant lessons are read automatically at the
start of a task, not looked up if someone remembers to.** You record a lesson once;
every future task that resembles it gets the lesson injected before the first line
of code is written.

It works for a single repo on day one, and across many repos when you point them at
a shared instance — so a lesson learned in one project protects the next one.

**This is a v0 starter, not production-hardened.** It ships an end-to-end test suite
(run `pytest -q` to see the suite and its current result in your environment). The core is
stdlib-only with zero required dependencies.

---

## What okl is

**A store of your engineering rules, and the machinery that keeps them true.**

Two things ship in the package. They are not coequal:

- **The knowledge layer** is the product. Typed records (rules, architecture decisions,
  known defects, gates, tombstones, retractions) that live outside any one repo, get
  retrieved into an agent's context before a task, and go stale loudly when the code
  they describe moves on. Everything measured in [evals/REPORT.md](evals/REPORT.md)
  measures this.
- **`okl scaffold`** is a starter kit for the in-repo discipline the store assumes: a
  lean canon file, mechanical gates, registries, a review agent, and an eval harness.
  It is useful on its own and it has never been measured. Use it to get a new repo to
  the state where a shared store has something to attach to.

| Piece | What it is | Where it lives |
|---|---|---|
| **client** (`okl` CLI + agent tools) | `check` / `record` / `verify` / `drift` / `search` / `seed` | installed per-repo (this package) |
| **shared layer** (`okl serve`) | one small service owning the database, so many repos share one store | one place you run it |
| **scaffold** (`okl scaffold`) | the in-repo starter files: canon, gates, registries, evals | stamped into each repo, optional |

## What it keeps from drifting, and how

Knowledge rots in a specific way: the code changes and everything written *about* the
code silently stops being true. Five mechanisms catch five different versions of that,
and it is worth knowing which one catches what, because they do not overlap.

| Drift | Caught by | How it works | Fires when |
|---|---|---|---|
| **A rule vs. the code it governs** | `okl drift --gate` | a record declares the path globs it governs; git is asked for the last commit touching them | that commit is newer than the record's last verification |
| **A retired identifier reappearing in prose** | `check-tombstones.sh` | greps tracked source, docs, comments and config for every tombstoned name | any non-allowlisted hit |
| **A withdrawn claim being restated** | `check-retractions.sh` | greps tracked docs for the exact quoted claim from the retraction registry | the quote appears outside the registry |
| **A doc nobody links to** | `check-doc-orphans.sh` | reachability check from hub files through `docs/` | a doc is unreachable, so it drifts unread |
| **A link pointing at a file that moved** | `check-links.sh` | resolves every local markdown link against `git ls-files` | the target does not exist |
| **A diagram source with no rendered image** | `check-diagram-pairs.sh` | pairs each editable source with its export; format-agnostic via `OKL_DIAGRAM_SRC_EXT`/`OUT_EXT` | reviewers would see nothing. A hand-authored image with no source is noted, never failed, and a repo with no diagram sources is a clean no-op |
| **Verification going quietly stale** | TTL + `verified_by` | records carry when they were last verified and by which observed check | past its TTL, a record is shown demoted rather than deleted |

Two honest limits on that table:

- **Diagram *content* is still a human job.** `check-diagram-pairs.sh` proves the rendered
  image exists; nothing proves it matches the source it was exported from, or that either
  matches the code. For that, name the diagram in a record's `--files` alongside the code
  it depicts, so changing the code turns the drift gate red until someone re-verifies the
  picture. This repo does exactly that with its own architecture diagram and README.
- **Comments are covered only by the identifier and claim gates.** A stale comment that
  names no tombstoned identifier and restates no retracted claim will not be caught.
- **`okl drift` only watches what a record claims.** A file no record governs is not
  watched by anything. Coverage is a curation decision, and the gap is invisible until
  something breaks — which is why the mechanical gates above scan *everything tracked*
  rather than only what is enrolled.

## Where this sits (2026): a crowded space, entered anyway

**This is not a novel idea, and you should know that before reading further.** Agent
memory is one of the most crowded categories in the field: mem0, Zep, Letta, and Cognee
on the infrastructure side; Cursor Memories and Devin Knowledge built into the coding
agents; AGENTS.md / CLAUDE.md / rules files as the convention standard everyone already
uses; and the research literature (e.g. Codified Context, arXiv 2602.20478) arriving at
tiered knowledge + retrieval independently. "Give the agent your team's knowledge" is
the consensus position of 2026, not an insight.

**So why build it anyway?** Three honest reasons:

1. **The crowded half isn't this half.** Nearly all of that tooling solves
   *personalization* memory — facts extracted from conversations, per-user context,
   knowledge graphs of what the agent experienced. The *institutional* half — receipted
   engineering lessons with governance over who sees what, injected before work with
   teeth — is mostly served by hand-edited rules files. That gap is real even if the
   category isn't new.
2. **One bet nobody else had made: memories are treated like tests, not notes.** A
   lesson here cites the source it governs, carries a verification receipt
   (`okl verify` — no run, no stamp), decays on a TTL, and goes stale *loudly*:
   `okl drift --gate` fails CI when governed code changed after the lesson was last
   verified. Every other tool in the table below accumulates; nothing invalidates.
   The whole repo is plumbing to get that one bet in front of an agent before the
   first line of code is written.
3. **Building it was the point.** This repo exists to make a working method concrete —
   and the things it surfaced would not have come from adopting a product: the eval
   receipts in `evals/`, the store carrying its own failure log, and the end-to-end
   test that caught the briefing being delivered to a channel the model never reads
   (`evals/REPORT.md` §8). Wiring a vendor SDK would have taught none of that.

| Tool / convention | What it remembers | What invalidates a memory |
|---|---|---|
| mem0 / Zep / Letta / Cognee | extracted facts, conversation graphs, agent-curated tiers | nothing tied to your code — memories accumulate |
| Cursor Memories / Devin Knowledge | per-project conventions and pinned notes | manual editing |
| AGENTS.md / CLAUDE.md / rules files | hand-written canon, loaded whole | hand-editing; no per-task selection |
| **okl** | **typed, scoped lessons (Defect / Rule / Decision …), selected per task, fail-closed** | **the drift gate: a lesson whose governed source changed after its last verification fails CI** |

### Can I use mem0 / Zep / Letta instead? Or alongside?

**Instead — yes, if your problem is theirs.** If you want semantic recall over what an
agent has seen, per-user personalization, or conversation-scale memory, use them;
they're better at it, and this deliberately isn't that (no embeddings, by
[recorded decision](docs/decisions/2026-07-17-flat-retrieval-until-scale.md)).

**Alongside — they compose, because they're different layers.** Memory infrastructure
remembers what the agent *experienced*; this governs what the org has *verified*. A
reasonable stack runs both: mem0/Zep for recall, okl for the fail-closed pre-task
briefing, the drift gate in CI, and the record/verify loop.

**On top — the discipline is portable; the database is deliberately boring.** The parts
worth stealing are the typed schema, the org/repo scope boundary, verification-with-
receipts, and the fail-closed delivery — not the SQLite file. If your org already runs
a memory backend, reimplementing this loop on top of it is a reasonable weekend; what
you'd be adopting is the discipline, not the storage.

## Measured effect, and its limits

One held-fixed A/B (8 authored tasks, 3 samples per arm per run; generator and blind
judge are different models; method + raw receipts in [evals/REPORT.md](evals/REPORT.md)):

- Same model, briefed vs not: defect reproduction fell **33% → 4%** (sonnet) and
  **38% → 12%** (haiku). Every "reproduced" is a defect class this store had already
  paid to learn — an IDOR, a price-tamper fallback, tokens in web storage, an unpinned
  CI gate — not lint noise.
- The result worth remembering: **briefed haiku (12%) beat unbriefed sonnet (33%)**.
  The briefing is a cost lever, not just a quality lever — it can hold a cheaper model
  above a frontier model's unbriefed floor on the org's known failure modes.

What this does **not** show: the tasks were authored to invite defect classes the store
encodes, so it measures what a briefing does when a directly relevant lesson exists —
not general code quality, and not retrieval at scale. n is small; treat it as a pilot
with receipts, not a benchmark.

## How it works

<img src="docs/okl-how-it-works.svg" alt="One repo records a lesson; every other repo is briefed on it before its next task. The store is typed, scoped and tagged; every verification stamp carries the check that earned it." width="100%">

### The mental model

`okl` stores small, typed **notes** and the **links** between them.

A note (internally a "node") is one of a few kinds:

| Kind | What it captures |
|---|---|
| **Defect** | A specific bug or mistake that happened, and why. |
| **Gate** | An automated check that catches a class of defect. |
| **Rule** | A standard to follow ("do X, never Y"). |
| **Retraction** | A claim that turned out to be false and was withdrawn. |
| **Tombstone** | An identifier (name, file, endpoint) that was retired and must not come back. |
| **Decision** | A choice that was made deliberately, so it isn't silently reversed later. |

Each note can carry a **Symptom → Cause → Fix**: *when you see this symptom, the
cause is this, do this fix.* That structure is what makes a note actionable instead
of just informational.

Notes can be **linked**: a Gate `CATCHES` a Defect; a Retraction `RETRACTS` a Claim;
a Decision `SUPERSEDES` an older one. The links let a lookup pull in the connected
context ("here's the bug, and here's the check that would have caught it").

### The two things you do

Everything reduces to two actions:

1. **`check` — read before you work.** You describe the task you're about to do.
   `okl` searches the store, keeps only the notes relevant to *your* scope, ranks
   them, and returns a short briefing that **leads with concrete actions**:
   *"FIX: server-controlled price tampering — when you see a request carrying a
   Price field → compute it server-side instead,"* *"ARM: run the class-path check
   before you finish."* An AI agent reads this at the top of its context; a person
   reads it in the terminal.

2. **`record` — write after you learn.** When you fix something or decide something,
   you record it as a note (optionally with its symptom/cause/fix and the files it
   governs). From then on, every `check` whose task resembles it surfaces it.

### Scope — what stays local vs. what spreads

Every note has a **scope**, and this is the one decision that matters most:

- **`repo:<name>`** — a lesson specific to one project. It only ever shows up for
  that project. (This repo's quirky build step, a workaround for one service.)
- **`org`** — a lesson that's true everywhere. It shows up for *every* project
  connected to the same instance. (A security pattern, an API contract, a
  data-source gotcha.)

Choosing the scope when you record is the human curation step. It's what keeps a
shared layer from filling up with one project's noise: another project's `check`
never sees your repo-scoped notes, only the `org`-scoped ones worth spreading.

Orthogonal to scope, every note can carry **subject tags** from a small controlled
vocabulary (`react`, `security`, `eval-integrity`, … — see `KNOWN_TAGS` in
`store.py`): scope answers *who may see* a note, tags answer *what it's about*.
A repo declares the subjects it cares about at init time
(`okl init --interests "python-rag,eval-integrity"`), and `check` then drops
org-wide notes tagged entirely outside those interests — so a Python eval task
isn't briefed on React lessons. Untagged notes and the repo's own notes always
pass. (Decision record: `docs/decisions/2026-07-21-subject-tags-controlled-vocabulary.md`.)

### It fails closed

If `okl` is configured to talk to a shared instance and that instance is
unreachable, `check` **says so loudly and blocks** — it does not return an empty
"nothing found," because "no lessons apply" and "I couldn't reach the lessons" look
identical from the outside and the second one is dangerous. Silence is never
reported as safety.

### Where the data lives

A single local file by default (SQLite). Point it at a shared service (backed by the
same SQLite, or Postgres) when you want several repos to share one body of
knowledge. The switch is one environment variable; none of your commands change.

---

## Install

```bash
pipx install org-knowledge-layer   # provides the `okl` command
pip install -e .                   # or from a clone of this repo
```

The core (local + client + CLI) is **stdlib-only** — zero required dependencies.
Extras are opt-in:

```bash
pip install "org-knowledge-layer[service]"    # FastAPI shared service
pip install "org-knowledge-layer[postgres]"   # Postgres backend (psycopg)
pip install "org-knowledge-layer[mcp]"        # MCP server for Claude Code / Cursor / Copilot
pip install "org-knowledge-layer[all]"
```

## Wire a repo

```bash
cd my-repo
okl init --repo my-repo        # writes .okl/config.json; installs the pre-task hook if .claude/ exists
okl connect https://okl.myorg.dev   # optional: point at the shared service (else local file)
```

### What `okl init` writes to your repo

Run `okl init --dry-run` first: it lists every path and writes nothing. In full, `init`
touches only the current directory, and only these:

| Path | What it is |
|---|---|
| `.okl/config.json` | repo name, subject interests, and the path to your `okl` binary |
| `.claude/hooks/userpromptsubmit-okl-check.sh` | **executable**; runs when you submit a task, injects the briefing |
| `.claude/hooks/stop-okl-encode.sh` | **executable**; runs at session end, asks what was learned |
| `.claude/settings.json` | registers those two hooks (merged in place; your existing keys are preserved) |
| `.mcp.json` | registers the okl MCP server — only when the `mcp` extra is installed |
| `.github/workflows/okl-verify.yml` | **a CI workflow** running the drift gate on pull requests |

Two of those deserve a second look before you run it: the hooks are shell scripts that
execute automatically during agent sessions (the check hook can *block* a task when the
store is unreachable — that is the fail-closed design), and the CI workflow will run in
your Actions. Both are plain text you can read first, in
[`src/okl/scaffold/hooks/`](src/okl/scaffold/hooks/) and
[`src/okl/scaffold/ci/`](src/okl/scaffold/ci/). Nothing executes at install time; nothing
is written outside the directory you run `init` in; nothing contacts a network unless you
run `okl connect` and point it somewhere yourself.

`init` writes `.okl/config.json`. If the repo uses a coding agent with a `.claude/`
directory, it also installs two hooks: a `UserPromptSubmit` hook that runs `check` on
the prompt you actually typed and puts the briefing into the model's context (the
enforced read — it must be this event: `PreToolUse` stdout never reaches the model,
which an end-to-end test caught the hard way), and a session-end hook that blocks the first stop
of a session that changed files with one question — *did this session learn anything
worth `okl record`ing?* — so the write side of the loop gets a mechanical prompt too,
not just a convention. It fires once per session and never loops.

**Other agents (AGENTS.md):** `init` and `scaffold` write the repo canon to both
`CLAUDE.md` and `AGENTS.md` — one content, two filenames, so Codex/Cursor/anything
reading the AGENTS.md convention gets the same rules Claude Code does (byte-identity is
test-enforced). The hooks themselves are Claude Code-specific; other agents get the
canon via AGENTS.md and the store via the MCP server (`okl mcp`).

That split matters: on Claude Code the pre-task read is *enforced* (fail-closed hook);
everywhere else it is *available* (a tool call or a shell command), which is
discretionary — the thing enforcement exists to avoid. The hook scripts themselves are
plain bash reading JSON on stdin, so nothing in them is Claude-specific; what is missing
for other agents is the config that registers them, and whether the agent fires an event
early enough to matter. Codex CLI documents a `userpromptsubmit` hook, which is the right
shape; Copilot, Gemini CLI and Cursor have hook systems worth checking against your
version; OpenCode's plugin API captures tool events but, as of this writing, no
pre-prompt event — so there the read stays a tool call rather than a gate. Verify against
your agent's current docs before trusting any of that. Wiring one up is a well-shaped
contribution — see [CONTRIBUTING.md](CONTRIBUTING.md).

Hooks run in whatever environment the agent harness spawns — often without your venv or
pipx bin dir on PATH — so both hooks resolve the `okl` binary in layers: the `OKL_BIN`
env var, then the `okl_bin` path `init` pins into `.okl/config.json` (machine-local),
then PATH, then any `python3` that can `import okl` (`python3 -m okl`). If nothing
resolves, the check hook blocks with install instructions (fail closed, `OKL_OFFLINE=1`
to override) while the encode reminder silently disables (best-effort by design).
With no shared service configured it uses a local `.okl/okl.db` — single-machine
mode, good for trying it before you deploy anything.

## Use it

```bash
# 1. READ the relevant lessons before starting a task (the load-bearing move)
okl check --task "add an endpoint that returns an order for the logged-in user"
#   add --format actions --limit 3 for a ~240-token version (subagents, CI)

# 2. RECORD a lesson after you learn it, with an actionable symptom/cause/fix
okl record --type Defect --scope org --tags "security" \
  --title  "Trusting a client-supplied price lets the client set it to anything" \
  --symptom "a request body carries a price/amount/status/isAdmin field" \
  --body    "cause: the handler saved the client's value instead of computing it" \
  --fix     "drop those fields from the request; compute them server-side" \
  --files   "**/orders/*.py" --verified

# 3. SEARCH the stored lessons directly
okl search "price tampering"

# 4. LINK a check to the defect it catches (so a lookup pulls in both)
okl link <gate_id> CATCHES <defect_id>
```

`--symptom`/`--fix` are what make `check` emit a leading **"Do this"** action list
(*"FIX: … — when you see: …"*) instead of a wall of prose. `--files` tells `okl` which
source files a lesson governs, which powers drift detection (below).

### Extra commands

```bash
okl verify <id> --run "pytest -q" --expect "passed"
                     # run the named check and stamp the node verified ONLY on an observed
                     #   pass; the command + result is stored as the evidence trail.
                     #   --expect requires a positive success signal in the output, so an
                     #   exit code alone can't self-certify. (`record --verified` remains
                     #   for importing historical receipts; live verification uses this.)
okl drift --gate     # flag lessons whose governed source changed after they were last verified
                     #   (exit 1 in CI — a stale rule is a rule nobody's re-checked)
okl coverage         # ratio of encoded-knowledge lines to code lines — a health signal
okl bootstrap        # cold-start a new repo: propose starter notes from its own
                     #   git history + docs into a reviewable file you edit, then seed
okl metric           # recurrence-after-arming: defect classes that came back in a repo
                     #   where a catching check existed but wasn't turned on
```

## Subagents and small context budgets

A full briefing costs roughly **4,400 tokens** — fine for a main session with a large
window, punishing for a subagent working in a few thousand. That asymmetry matters
because subagents are exactly where org rules get lost: a focused worker handling one
subtask has the least context and the most need for "here is the mistake this codebase
already made."

`--format actions` solves it by dropping everything except the imperative list:

```bash
okl check --task "add an endpoint returning an order for the logged-in user" \
  --format actions --limit 3
```

```
OKL — 3 rule(s) apply before you start:
- FIX: Missing ownership scope check is an IDOR (CWE-639) [when: an endpoint fetches an
  entity by id with no owner/tenant predicate]
  -> add the caller's owner id to the WHERE clause; return 404 (not 403) on no match
...
```

**Measured on this repo's own store:** ~240 tokens at `--limit 3`, ~390 at `--limit 5`,
~630 at `--limit 8`, against ~2,650 for the full briefing. Cheap enough to call per subtask.

The full briefing is itself capped: `check` keeps the top `--limit` records (12 by
default) from the ranked, filtered set and says how many it trimmed. Before that cutoff
existed, one task on this store returned 20 records and ~4,400 tokens. Re-running the A/B
after adding it showed no retrieval miss — the one task that regressed still had its rule
in the briefing and the model simply did not follow it, which is a compliance problem
rather than a retrieval one. See [evals/REPORT.md](evals/REPORT.md).

What it drops: the bucketed sections, the prose bodies explaining *why* each record
exists, prior-art notes, and the stale-record footer. What it keeps is what changes
behaviour: the verb, the symptom to watch for, and the fix.

**Wiring it into a subagent.** Three ways, in order of how much enforcement you get:

1. **The MCP tool** — `okl_check(task=..., compact=True, limit=3)`. Any subagent with
   MCP access can call it. Discretionary: the agent has to choose to.
2. **In the subagent's prompt** — have the spawning agent run `okl check --format
   actions --limit 3` and paste the result into the subtask description. Not
   discretionary, and it costs the parent almost nothing.
3. **A wrapper script** that runs the check and prepends it to whatever prompt it is
   handed. This is the enforced version for orchestration you control.

**A caveat worth stating.** `--limit` caps how many records the briefing draws on, and
ranking decides which survive. If a task's most relevant rule ranks fourth and you ask
for three, you will not see it, and nothing will tell you. The full briefing exists
because it does not make that trade. Use the compact form where a token budget forces
the choice, not by default.

## Verification: don't let a step grade itself

A step reporting "I succeeded" and the work actually being done are two different facts,
and a loop that accepts the first one compounds garbage confidently. (The founding
receipt: a pipeline step that was supposed to write 238 files failed on every one,
swallowed the errors, and exited 0 — everything downstream ran happily on an empty
folder.) Two clarifications that stop the common misreadings:

- **The grader is usually `ls`, not an LLM.** Checking the work means observing the
  work product — files exist, counts match, tests ran, the output contains the success
  signal you named. Boring, deterministic checks. A second model only enters when the
  verify signal is itself a model's *judgment* (LLM-as-judge) — there, and only there,
  the judge must differ from the generator.
- **Not every step — every claim the loop acts on.** Verify at decision boundaries
  (mark done, merge, deploy), cheap invariants in between.

`okl` applies this to its own knowledge in four escalating rungs:

1. **Assertion is quarantined.** `record --verified` (bare claim, no evidence) exists
   only for importing historical receipts. Live verification refuses it.
2. **Observed check with a stored trail** — `okl verify <id> --run "pytest -q"
   --expect "passed"` runs the check itself, reads the real outcome, requires the
   positive signal (exit 0 alone can't self-certify), and stores command + result +
   timestamp on the node (`verified_by`). Every stamp is inspectable and re-runnable;
   a lazy check becomes a visible artifact instead of an invisible belief.
3. **An independent actor re-checks** — CI runs `okl drift --gate` and the method
   gates on every PR: a mechanical grader with no stake in the original claim, and
   `VERIFIED_ON` receipts are written by the job that watched a gate prove itself.
4. **Time attacks every stamp** — `drift` re-grades verifications the moment governed
   files change after `verified_at`; TTL decays stamps nobody re-earns into `STALE`;
   and `okl metric` (recurrence-after-arming) scores the whole system on outcomes —
   defect classes that came back — the one number it can't flatter itself on.

## Seed it (so the very first `check` returns something)

An empty store returns nothing, and says so — a check against an empty store reports
that it proved nothing rather than reporting "no rules apply". Three ways to fill it:

**1. See what ships, then choose.** A bare `okl seed` imports nothing; it lists the
bundled packs with their record counts and subject tags, marking the ones that match
this repo's declared interests:

```bash
okl seed                              # list the packs, import nothing
okl seed <path>/rag-defects.json      # import one
okl seed --all                        # import every pack (explicit on purpose)
```

The packs hold real, dated records from production codebases (a .NET service, a
geospatial ML pipeline, a Python RAG service, a React app). They are org-scoped, so
importing packs for stacks you do not use fills every briefing here with noise about
frameworks you will never touch — which is why `--all` is opt-in rather than default.

**2. Generate records from this codebase.** If you use a coding agent, the scaffold
stamps a `/seed-from-codebase` command that has the agent read your repo — the guard
rails already in the code, what CI enforces, the fix commits, the existing canon — and
propose records with a `file:line` citation each. Everything it proposes is repo-scoped
and unverified by design; it writes a reviewable file and imports nothing, because a
plausible rule no file supports is worse than an empty store.

**3. `okl bootstrap`** greps git history and file names for candidates. It is the weakest
of the three and comes up empty on young repos; prefer option 2 when an agent is available.

Whichever you use, review before importing. Choosing a record's scope is the curation
step that keeps a shared layer from filling with one project's noise.

---

## The method kit — `okl scaffold` (optional)

Beyond the knowledge store, `okl` can stamp a **starter set of engineering-discipline
files** into a repo, so a new project begins with the guardrails already in place
rather than accumulating them by hand:

```bash
okl scaffold .                 # stamp the starter files into the current repo
okl scaffold . --plugin        # also emit a Claude Code plugin manifest
okl scaffold new-repo --profile python-rag --profile react   # include stack rule packs
```

It writes a lean project-instructions file, a set of automated **checks** (scripts
that fail CI when a retired identifier reappears, a withdrawn claim gets restated, a
doc becomes unreferenced, or the instructions file grows too large), a small
behavior-evaluation harness, and optional **stack profiles** — ready-made rule packs
for common stacks (`dotnet`, `geospatial`, `python-rag`, `react`). Stack-specific
blanks are marked `<<FILL>>`; after scaffolding, `grep -rn '<<FILL' .` lists every
one to complete.

It also stamps two **first-party method skills** — `encoding-loop` (turn a finding
into a promoted, recorded lesson) and `verify-before-claiming` (evidence before you
assert a result). The broader engineering-discipline skills (systematic debugging,
TDD, plan writing/execution, git-worktree isolation) are **not bundled** — they're
best maintained in third-party collections, so `skills/RECOMMENDED-COMPANIONS.md`
points at those instead of vendoring someone else's work and its cross-references.

The scaffold runs with no store at all; the store works in a repo that never scaffolded.
They are complementary, not a package deal.

**Storage is swappable** via one environment variable — your commands never change:

```bash
# default: a local file (single machine)
export OKL_DATABASE_URL="sqlite:///okl.db"
# a shared database when several repos need one store
export OKL_DATABASE_URL="postgresql://user:pass@host/okl"
okl serve --port 8080
```

## Run the shared service

```bash
pip install "org-knowledge-layer[service]"
OKL_DATABASE_URL="postgresql://user:pass@host/okl" OKL_TOKEN="a-shared-secret" okl serve
# repos then: okl connect https://your-host --token a-shared-secret
```

**Set `OKL_TOKEN`.** With it, every route requires the bearer token except `/health`
(left open so schedulers can probe it). Without it, every route is open — including
`GET /nodes`, which hands the whole store to anyone who can reach the port. A mature
store is a catalogue of your known defects and internal architecture, which is a map of
where you are weak. It is a single shared secret with no per-repo scoping or rotation;
put a real authenticating proxy in front if you need more.

Full instructions, including a throwaway Postgres for trying it locally and what the
failure modes look like: **[docs/DEPLOY.md](docs/DEPLOY.md)**.

## Agent integration (MCP)

```bash
pip install "org-knowledge-layer[mcp]"
okl mcp     # register in your coding agent's tool config
```

Exposes three tools to a coding agent: `okl_check` (read lessons before a task),
`okl_record`, `okl_search`. `okl_check` **fails closed** — if a configured shared
instance is unreachable it says so loudly rather than returning a reassuring
"nothing found," because those two look identical from the agent's side and only one
is safe.

---

## Design choices, and why

- **Read before you work, automatically.** The value is entirely in the lesson being
  in front of you at the start — not in a database you *could* have searched. So the
  read is a hook / a first step, not an optional lookup.
- **It fails closed.** An unreachable store blocks or warns; it never reports "clean."
  Silence and safety are different things.
- **The scope decision is human curation.** `org` spreads everywhere; `repo:<name>`
  stays local. A person picks which when recording — that's what keeps a shared store
  from filling with one project's noise.
- **Staleness demotes, never deletes.** A note carries when it was last verified and
  how long that's good for; past that it's shown as `STALE`, not removed — deleting it
  would lose the record that it was ever true.
- **Start simple, grow on evidence.** A stdlib-only core and a single SQLite file by
  default; add the shared service, Postgres, or anything heavier only when a concrete
  symptom demands it (recorded as a decision in `docs/decisions/`).

## Layout

```
src/okl/
  store.py        # the database: note + link schema, swappable SQLite/Postgres backend
  core.py         # check / record / search / link — the logic, independent of transport
  client.py       # resolves local-file vs. shared-service; fails closed
  cli.py          # the `okl` command
  drift.py        # source-vs-spec drift detection
  bootstrap.py    # propose starter notes from a repo's git history + docs
  service.py      # the shared web service (okl[service])
  mcp_server.py   # coding-agent tools (okl[mcp])
  seed.py         # load a JSON seed file
  scaffold_cmd.py # the `okl scaffold` starter-files stamper
seed/             # starter lesson files (examples + genuinely useful defects)
docs/decisions/   # design decision records
tests/            # end-to-end tests
```

## Test

```bash
pip install "org-knowledge-layer[dev]"
pytest -q          # full suite (one drift test self-skips where git init is unavailable)
```

## License

MIT.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the repo's own rules (mirror files,
drift, evidence-based verification), and where help is most useful. Security policy and
the deployment threat model: [SECURITY.md](SECURITY.md).
