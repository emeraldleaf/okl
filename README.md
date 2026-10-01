<div align="center">

# okl — Observed Knowledge Ledger

**A learning loop that keeps coding agents — and your docs — from drifting.**<br>
Engineering rules, architecture decisions, documentation and diagrams: recorded once, briefed to
Claude Code before every task, proven by checks, and flagged in CI when what they govern changes.

[![PyPI](https://img.shields.io/pypi/v/observed-knowledge-ledger?color=blue&label=PyPI)](https://pypi.org/project/observed-knowledge-ledger/)
[![Python](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](pyproject.toml)
[![ci](https://github.com/emeraldleaf/okl/actions/workflows/ci.yml/badge.svg)](https://github.com/emeraldleaf/okl/actions/workflows/ci.yml)
[![okl-verify](https://github.com/emeraldleaf/okl/actions/workflows/okl-verify.yml/badge.svg)](https://github.com/emeraldleaf/okl/actions/workflows/okl-verify.yml)
[![Claude Code plugin](https://img.shields.io/badge/Claude_Code-plugin-D97757)](#install-as-a-claude-code-plugin)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

🚀 [Quickstart](#quickstart) · 📘 [Getting started guide](docs/GETTING-STARTED.md) · 🔬 [How it works](#how-it-works) · 📊 [Results](#measured-effect-and-its-limits) · 🧪 [Eval report](evals/REPORT.md) · 🧩 [Plugin](#install-as-a-claude-code-plugin)

</div>

> A small store of what a codebase knows — its conventions, architecture decisions and
> why they were made, the checks that catch mistakes already made once, and the claims its
> docs and diagrams make — plus a hook that hands the relevant ones to a coding agent (or a
> person) **before** they start a task. Each session can record what it learned, so the store
> grows with the work; it survives past a session and can be shared across a team. And it
> stays true: an entry is verified by running a check, and flagged when the files it governs
> change, whether those are code, docs or diagrams.

## Quickstart

> New here? **[docs/GETTING-STARTED.md](docs/GETTING-STARTED.md)** walks through setup, the
> habit of adding to the canon as you build a feature, and keeping your docs from drifting.

**1. Install the CLI** (the PyPI name differs — PyPI refuses `okl` as confusable with
`oki` — but everything you type afterwards is `okl`):

```bash
pipx install 'observed-knowledge-ledger[mcp]'
```

**2. Wire your repo.** From the repository root:

```bash
okl init --repo my-repo --dry-run   # lists every file it would write; writes nothing
okl init --repo my-repo             # config, Claude Code hooks, MCP server, CI workflow, starter lessons
```

`init` detects your stack (`*.csproj`, `package.json`, `pyproject.toml` …), sets the repo's
interests from it, and fills the store with 20 starter lessons that hold on almost any
codebase plus the bundled packs for your stack, so the first prompt is already briefed
(`--interests` chooses your own subjects; `--no-seed` leaves the store empty).

`init` wires Claude Code when the repo has a `.claude/` directory or `claude` is on your
PATH; `--claude` forces it and `--no-claude` skips it. **Prefer the plugin?** Install it
*before* running `init` — `/plugin marketplace add emeraldleaf/okl`, then
`/plugin install okl@okl` in Claude Code — and `init` leaves the hooks to the plugin, so
nothing is wired twice. (Installed after? `okl doctor` reports the double wiring, and
`okl init --uninstall` removes the project copy.)

**3. Add a rule of your own.** The starter lessons are generic; what pays is what only your
codebase knows. Tell your agent — *"record an okl rule for this repo: order lookups are
scoped to the signed-in customer; governs app/orders.py"* — and it records the lesson with
okl's `okl_record` MCP tool (in Claude Code, `/record` drafts it and asks you first).
Underneath, that is one CLI call you can also run yourself:

```bash
okl record --type Rule --scope repo --id order-owner-scope \
  --title "Order lookups are scoped to the signed-in customer" \
  --symptom "an endpoint fetches an order by id with no owner filter" \
  --fix "filter by the caller's customer id in the query; return 404 on no match"
```

More: `okl seed` lists every bundled pack; `okl scaffold .` stamps the method kit, which
includes a `/seed-from-codebase` command that has your agent propose cited records from
your own code ([Seed it](#seed-it-so-the-very-first-check-returns-something)).

**4. Check it works:**

```bash
okl check --task "add an endpoint that returns an order for the logged-in user"
okl doctor                  # flags other agent-memory tools and double wiring
```

### What a normal day looks like

- **You prompt as usual.** The pre-task hook runs `okl check` on what you typed and puts
  the relevant lessons in the agent's context before it starts, and shows you one line —
  *okl · briefed 9 lesson(s): …* — so you can see it working (`OKL_QUIET=1` hides it).
- **When you learn something worth keeping** — a decision, a convention the agent broke,
  a bug you fixed — say so and the agent records it (`okl_record`, or `okl record`), with
  the files it governs. In Claude Code the Stop hook also asks once, at the end of a
  session that changed files, what was learned.
- **Using another agent?** The briefing and recording are MCP tools (`okl mcp`); register
  them and add one line to your `AGENTS.md`: *before each task call `okl_check`*. The hooks
  that do this automatically are Claude Code's; see
  [Getting started](docs/GETTING-STARTED.md#using-another-agent).
- **Proving a lesson is true** is a check you run, not a flag you set:
  `okl verify <id> --run "pytest -q tests/test_orders.py" --expect "passed"`.
- **When code a lesson governs changes,** `okl drift` goes red until someone re-runs its
  check (a lesson recorded with `--files` is also red until its first `okl verify`).
  `okl reverify` re-runs each drifted lesson's stored check after you confirm. CI reads a
  committed snapshot, `okl-drift.json`, which `okl verify` creates the first time a lesson
  with `--files` is verified and keeps current after that: commit it after the code change
  it verifies. Until then CI warns "Drift not checked", which is expected.
- **Headless runs** (`claude -p`, scripts, CI agents) set `OKL_DISABLED_HOOKS=encode`,
  or the end-of-session question replaces the printed answer.

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

  It is worth being precise about what that store fills up with, because "lessons a
  codebase has learned" invites the picture of a bug database. In the 161-record corpus
  in [seed/](seed/) it is mostly not that: **90 Rules, 20 Decisions and 7 Gates against
  34 Defects** — conventions the code follows and trade-offs already settled, not a
  ledger of things that broke. Count it yourself:

  ```bash
  python3 -c "import json,glob,collections; c=collections.Counter(
    n['type'] for f in glob.glob('seed/*.json') for n in json.load(open(f))['nodes']); print(c)"
  ```
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
| **A rule vs. the code it governs** | `okl drift --gate` | a record declares the path globs it governs; git is asked for the last commit touching them | that commit is newer than the record's last verification — or the rule has never been verified at all, so a new `--files` rule is red until its first `okl verify` |
| **A retired identifier reappearing in prose** | `check-tombstones.sh` | greps the working tree's source, docs, comments and config for every tombstoned name | any non-allowlisted hit |
| **A withdrawn claim being restated** | `check-retractions.sh` | greps the working tree's markdown for the exact quoted claim from the retraction registry | the quote appears outside the registry |
| **A doc nobody links to** | `check-doc-orphans.sh` | checks that each top-level `docs/` doc or image is named by a hub file or a `docs/*.md` (one hop, not transitive) | nothing names it, so it drifts unread |
| **A link pointing at a file that moved** | `check-links.sh` | reads every markdown file listed by `git ls-files` and checks each local link's target exists in the working tree | the target does not exist |
| **A diagram source with no rendered image** | `check-diagram-pairs.sh` | pairs each editable source with its export; format-agnostic via `OKL_DIAGRAM_SRC_EXT`/`OUT_EXT` | reviewers would see nothing. A hand-authored image with no source is noted, never failed, and a repo with no diagram sources is a clean no-op |
| **Verification going quietly stale** | TTL + `verified_by` | records carry when they were last verified and by which observed check; a TTL applies only to records given `--ttl-days` (none by default) | past its TTL, a record is shown demoted rather than deleted |

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
  something breaks — which is why the mechanical gates above scan the whole repo (the
  tombstone and retraction gates grep the working tree) rather than only what is enrolled.

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
   teeth — is mostly served by hand-edited rules files, and inside Copilot by its
   repository memory. That gap is real even if the category isn't new.
2. **The bet: memories are treated like tests, not notes.** okl is not alone in tying
   memory to code: GitHub Copilot's memory (2026) cites the code lines behind each
   memory and has the agent re-read them before use, and driftlint fails CI when an
   instruction file names a path or command that no longer exists. okl's version is
   stricter for the lessons that matter. A lesson cites the source it governs and
   carries a verification receipt from a check you choose (`okl verify` — the CLI will
   not stamp without a run), can decay on a TTL, and goes stale *loudly*:
   `okl drift --gate` fails CI when governed code changed after the lesson was last
   verified, or it was never verified. Most tools in the table below accumulate; the
   ones that do invalidate do it by re-reading code or checking references, not by
   running your check. The whole repo is plumbing to get that bet in front of an agent
   before the first line of code is written.
3. **Building it was the point.** This repo exists to make a working method concrete —
   and the things it surfaced would not have come from adopting a product: the eval
   receipts in `evals/`, the store carrying its own failure log, and the end-to-end
   test that caught the briefing being delivered to a channel the model never reads
   (`evals/REPORT.md` §8). Wiring a vendor SDK would have taught none of that.

| Tool / convention | What it remembers | What invalidates a memory |
|---|---|---|
| mem0 / Zep / Letta / Cognee | extracted facts, conversation graphs, agent-curated tiers | nothing tied to your code — memories accumulate |
| Cursor Memories / Devin Knowledge | per-project conventions and pinned notes | manual editing |
| GitHub Copilot Memory (2026) | repo facts the agent saves as it works, each citing the code lines behind it; shared by Copilot's coding agent, CLI and code review | the agent re-reads the cited lines before use and replaces a contradicted memory; memories expire unless re-confirmed — a model's judgment at use time, Copilot only, no CI gate |
| driftlint, agents-lint, scavi (instruction-file linters) | nothing of their own: they check the claims already in CLAUDE.md / AGENTS.md (driftlint also syncs approved facts into them) | a referenced path, command, link or import that no longer exists; driftlint fails CI — they check references, not whether a rule still holds |
| AGENTS.md / CLAUDE.md / rules files | hand-written canon, loaded whole | hand-editing; no per-task selection |
| claude-mem / agentmemory (Claude Code plugins) | every tool call, compressed into observations by a model; agentmemory adds confidence and decay | file age (claude-mem skips a note when its file changed); time-based decay (agentmemory) — nothing re-checks a memory |
| ECC (skills + "instincts") | instincts learned from observed tool use, weighted by a model-scored confidence | confidence decay, applied by prompt — no check proves an instinct |
| beads | work items and short `bd remember` notes — a task tracker, not a lesson store | closing the issue |
| **okl** | **typed, scoped lessons (Defect / Rule / Decision …), selected per task, fail-closed** | **the drift gate: a lesson whose governed source changed after its last verification (or that was never verified) fails CI** |

**Read against the Claude Code memory plugins** (claude-mem, agentmemory, ECC, beads — their
source, September 2026): they are ahead on capture, retrieval engineering, install polish
and reach across agents, and okl is not trying to catch them there. None re-checks that a
memory is still true, ties one to the code it describes, or measures whether memory
improves outcomes — claude-mem's "~10x" is a 5-query code-search benchmark, agentmemory's
evals are retrieval-only. Their capture also costs model calls (claude-mem runs a model per
tool call; agentmemory's lessons need an API key); okl requires none. claude-mem remembers
what happened; okl keeps what must stay true, and proves it.

**Running one of them alongside okl** works, with three known collisions: okl's Stop hook
blocks the first stop, so their Stop hooks run twice; capture-everything tools record
`okl record` too, so a lesson lands in two stores; and each injects its own context beside
okl's briefing. `okl doctor` names whichever is installed and what to do about it.

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

- Same model, briefed vs not: in the first 3-sample runs (2026-08-30), defect
  reproduction fell **33% → 4%** (sonnet) and **38% → 12%** (haiku). Later sonnet runs, as
  the retrieval pipeline changed, read **35–50% → 4–8%** (REPORT §4b–§4i, excluding the
  reverted §4d and the opus-judged §4f; the latest, §4i, 43% → 8%). The unbriefed arm
  alone has moved 17 points between runs with nothing changed, so that is the noise floor
  (§2b). Every "reproduced" is a defect class this store had already paid to learn — an
  IDOR, a price-tamper fallback, tokens in web storage, an unpinned CI gate — not lint
  noise.
- The result worth remembering, from those first runs: **briefed haiku (12%) beat
  unbriefed sonnet (33%)**. It suggests the briefing is a cost lever, not just a quality
  lever — it can hold a cheaper model above a frontier model's unbriefed floor on the
  org's known failure modes. Two caveats: the haiku run was never repeated, and it was
  judged by sonnet where the sonnet runs were judged by haiku.
- Every run above predates the briefing's **Decisions** section: until recently a
  Decision that won a slot was silently dropped; it now appears under its own heading.
  No eval task's briefing held one, so the eight measured briefings are byte-identical
  either way.

What this does **not** show: the tasks were authored to invite defect classes the store
encodes, so it measures what a briefing does when a directly relevant lesson exists —
not general code quality, and not retrieval at scale. n is small; treat it as a pilot
with receipts, not a benchmark.

## How it works

<img src="docs/okl-how-it-works.svg" alt="One repo records a lesson; every other repo is briefed on it before its next task. The store is typed, scoped and tagged; every verification stamp carries the check that earned it." width="100%">

### How a briefing is actually built

`okl check` is a retrieval pipeline: seven stages turn a task sentence and the whole corpus
into the twelve records an agent reads. Two stages can drop a record, and only one of them
is entitled to — the distinction that this project got wrong once and measured its way out
of ([REPORT §4d](evals/REPORT.md)).

<img src="docs/okl-retrieval-pipeline.svg" alt="Seven stages: the corpus, a BM25 fetch of three times the limit, a scope gate, the exclusive applies_to filter, the inclusive tags-times-interests filter, a top-12 cutoff, bucketing by type, and rendering. Each stage shows how many records survive it." width="100%">

Every count in that diagram is **traced**, not transcribed — `docs/render_pipeline_diagram.py`
runs the real `store.search` and `core._in_scope` against a store seeded from `seed/`, and
`test_pipeline_diagram_is_current` fails if the committed render is not what the generator
produces today. Change a BM25 weight or a filter predicate and the diagram goes red with it.

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
   before you finish."* Records that are not actions follow under their own headings,
   including the Decisions already made on purpose. An AI agent reads this at the top of
   its context; a person reads it in the terminal.

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

## Install as a Claude Code plugin

```
/plugin marketplace add emeraldleaf/okl
/plugin install okl@okl
```

The plugin carries the two hooks, the MCP tools and the seeding commands. It does not
carry okl itself: install the CLI first, **with the MCP extra**, because the plugin
registers the `okl mcp` server (`pipx install 'observed-knowledge-ledger[mcp]'`), then run
`okl init` in the repo for the store and the CI workflow — with the plugin enabled, `init`
skips the hooks and MCP registration, because registering them twice would brief every
prompt twice. `okl doctor` reports a repo where both the plugin and the project hooks are
active. To load the plugin from a checkout for one session: `claude --plugin-dir <path>`.

## Install

```bash
pipx install observed-knowledge-ledger   # provides the `okl` command
pip install -e .                   # or from a clone of this repo
```

The core (local + client + CLI) is **stdlib-only** — zero required dependencies.
Extras are opt-in:

```bash
pip install "observed-knowledge-ledger[service]"    # FastAPI shared service
pip install "observed-knowledge-ledger[postgres]"   # Postgres backend (psycopg)
pip install "observed-knowledge-ledger[mcp]"        # MCP server for Claude Code / Cursor / Copilot
pip install "observed-knowledge-ledger[all]"
```

## What it costs, and how to turn it down

Installing okl is not free. It is worth knowing exactly what you are signing up for
before you wire it into every prompt. Every number below was measured rather than
estimated — on a fresh store holding the 161 bundled seed records, with one representative
task ("add an endpoint that returns an order for the logged-in user"; tokens ≈ characters
÷ 4). Your store and your tasks will differ.

**Per prompt, once the hook is installed:**

| | |
|---|---|
| Latency | **~0.1s** for the whole `okl check` process (0.07s median warm) — one local SQLite query, no network in local mode |
| Context | **~1,650 tokens** at the default `--limit 12`, down to **~230** at `--format actions --limit 3` |

**Per session:** the Stop hook interrupts once at the end to ask what was learned. It
blocks the first stop only, and answering it is the whole write side of the loop. With
the question it lists up to five commands that failed during the session, read from the
session's own transcript — candidates, not records: no hook runs on every tool call, and
no model is called to summarise anything.

**In your repo:** `okl init` writes `.okl/` (config, the local database, a `.gitignore`
covering both) and, when it wires Claude Code, two hook scripts plus their registration. It
also installs `.github/workflows/okl-verify.yml`, which runs the drift gate on every PR.
CI has no store of its own (the local one is gitignored), so give it one: once a lesson
governs files, commit `okl-drift.json` (`okl verify` refreshes it; `okl export --drift`
writes it; a snapshot of the rules drift reads, no lesson bodies), or set the
`OKL_SERVICE_URL` secret. Without either, the step warns "Drift not checked" rather than
passing as if it had. Do not commit a snapshot holding zero rules: CI reads a configured
store that checked nothing as broken, and fails.
`okl scaffold` is separate and optional — nothing installs it unless you ask.

### The knobs, cheapest first

```bash
okl check --task "..." --format actions   # imperatives only, about half the size
okl check --task "..." --format json      # the raw result, for scripts
okl check --task "..." --format hook      # what the Claude Code hook prints: the briefing plus
                                            #   the one-line notice you see (OKL_QUIET=1 drops it)
okl check --task "..." --limit 3          # fewer records; the briefing says how many it trimmed
okl init --interests "python,security"    # drop records tagged for stacks you do not use
```

- **`--format actions`** is the single biggest saving and loses the least: you keep every
  "when you see X → do Y" and drop the explanatory prose.
- **`--limit N`** caps how many records are drawn on. The full briefing reports how many
  it trimmed; `--format actions` does not, so a short actions list can hide a miss
  without saying so.
- **`interests`** is the one to reach for on a mature shared store. Tags filter
  inclusively — an org record passes when it is untagged or shares any one tag with your
  interests, so declaring `python` keeps out a record tagged only `dotnet`, but not one
  tagged `dotnet,security` when you also declared `security`. Only a record's
  `applies_to` excludes by stack.
- **Scope records `repo:` rather than `org`** when a lesson is local. Org scope is a claim
  that every project in the organization should see it, and it costs every project's
  budget to be wrong about that.

### Turning parts off

`OKL_QUIET=1` keeps the briefing but hides the one-line *okl · briefed …* notice. Switch a
hook off by name with `OKL_DISABLED_HOOKS=briefing` (the pre-task read),
`OKL_DISABLED_HOOKS=encode` (the end-of-session question), or both, comma-separated.
**Set `OKL_DISABLED_HOOKS=encode` for headless runs (`claude -p`, CI agents, scripts):**
print mode emits only the final message, and a blocked stop makes the reply to "what did
we learn?" that final message — the answer you asked for is then only in the transcript.
Hooks inherit the caller's environment, so the variable set on the `claude` command is
enough (`evals/REPORT.md` §10). The
pre-task hook is the read side and the Stop hook is the write side, and they are
independent — running the read without the write is a reasonable way to start, and turning
off `encode` is the usual choice beside a tool whose own Stop hooks already run.

Nothing is load-bearing on the hooks: `okl check` and `okl record` work from the terminal,
from CI, and through the MCP server whether or not any hook is installed.

To remove okl from a repo: `okl init --uninstall` (add `--dry-run` to preview). It removes
the two hook scripts, their exact entries in `.claude/settings.json`, okl's `.mcp.json`
server and `.github/workflows/okl-verify.yml` — and nothing else: another tool's hooks in
the same events stay, a file you edited is kept and named, and `.okl/` (your store) is
never touched; delete it yourself if you mean to. Nothing outside the repo was ever written.

The two hook scripts and the CI workflow each carry a `# okl-fingerprint:` line, the hash
of the rest of the file (settings and `.mcp.json` are merged entry by entry instead). That
is how `init` and `--uninstall` tell an untouched okl file (of any fingerprinted version:
upgraded or removed freely) from one you edited. Files installed before 0.7 carry no
fingerprint, so unless one is byte-identical to the current version, `init` keeps it and
`okl init --force` is what upgrades it. `init` keeps an edited file unless you pass
`--force`; `--uninstall` always keeps it. There is no local state, so this works the
same for a teammate who cloned the repo. okl never writes through a symlink: a hook,
settings or workflow path that is a link, or sits under one, is refused and named.

### Architecture review in CI (off by default)

The kit ships a reviewer that reads a PR diff against your encoded rules and fails the
build on a must-fix finding. It is **off unless you ask for it**, and it is not tied to any
vendor. Set the `REVIEW_CMD` repository variable to any CLI that reads a prompt on stdin:

```bash
gh variable set REVIEW_CMD --body "claude -p --model sonnet"   # Claude Code CLI, installed on the runner
gh variable set REVIEW_CMD --body "ollama run qwen2.5-coder"   # local model, no API cost
gh variable set REVIEW_CMD --body "llm -m gpt-4o"              # any other CLI
```

Two things worth knowing:

- **In CI, the runner needs the CLI and a credential.** The scaffolded job does not install
  whatever `REVIEW_CMD` names, and if that command is not on the runner's PATH the step
  skips with a soft pass. Install it in the workflow and give it the secret it needs (the
  job passes `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` through when set). Your personal
  Claude Code login does not reach a hosted runner.
- **Run locally, `claude -p` needs no separate API key.** It authenticates with the Claude
  Code login you already have. Verified headless with `ANTHROPIC_API_KEY` unset.
- **Locally you do not need this at all.** The reviewer is a subagent
  (`.claude/agents/architecture-reviewer.md`); ask your agent to run it on your changes and
  it costs nothing beyond the session you are already in. The CI job exists for the case
  where no human and no agent is in the loop — a PR nobody reviewed.

Unset, the step prints one line saying it is off and exits 0. Every other gate in the kit is
deterministic and free; this is the only one that calls a model, which is why it is the only
one that is opt-in.

## Wire a repo

```bash
cd my-repo
okl init --repo my-repo        # writes .okl/config.json; wires Claude Code if .claude/ exists or `claude` is on PATH (--claude / --no-claude)
okl connect https://okl.myorg.dev   # optional: point at the shared service (else local file)
```

### What `okl init` writes to your repo

Run `okl init --dry-run` first: it lists every path and writes nothing. In full, `init`
touches only the current directory, and only these:

| Path | What it is |
|---|---|
| `.okl/config.json` | repo name, subject interests, and the path to your `okl` binary |
| `.okl/.gitignore` | keeps `.okl/` (config and store) out of git, with no edit to your own `.gitignore` |
| `.okl/okl.db` | the local store (local mode only; seeded with the starter lessons and your stack's packs unless `--no-seed`) |
| `.claude/hooks/userpromptsubmit-okl-check.sh` | **executable**; runs when you submit a task, injects the briefing |
| `.claude/hooks/stop-okl-encode.sh` | **executable**; runs at session end, asks what was learned |
| `.claude/settings.json` | registers those two hooks (merged in place; your existing keys are preserved) |
| `.mcp.json` | registers the okl MCP server — only when the `mcp` extra is installed |
| `.github/workflows/okl-verify.yml` | **a CI workflow** running the drift gate on pull requests — only in a git repository |

Re-running `init` is safe as long as you pass the same `--repo` (without it, the repo name
resets to the directory's name): it upgrades okl's own files, keeps any you edited (say so
with `--force` to replace them), and merges settings without duplicating entries.

Two of those deserve a second look before you run it: the hooks are shell scripts that
execute automatically during agent sessions (the check hook can *block* a task when the
store is unreachable — that is the fail-closed design), and the CI workflow will run in
your Actions. Both are plain text you can read first, in
[`src/okl/scaffold/hooks/`](src/okl/scaffold/hooks/) and
[`src/okl/scaffold/ci/`](src/okl/scaffold/ci/). Nothing executes at install time; nothing
is written outside the directory you run `init` in; nothing contacts a network unless you
run `okl connect` and point it somewhere yourself.

`init` writes `.okl/config.json`. When it wires Claude Code (the repo has a `.claude/`
directory, `claude` is on PATH, or you passed `--claude`), it also installs two hooks:
a `UserPromptSubmit` hook that runs `check` on
the prompt you actually typed and puts the briefing into the model's context (the
enforced read — it must be this event: `PreToolUse` stdout never reaches the model,
which an end-to-end test caught the hard way), and a session-end hook that blocks the first stop
of a session that changed files with one question — *did this session learn anything
worth `okl record`ing?* — so the write side of the loop gets a mechanical prompt too,
not just a convention. It fires once per session and never loops.

**Other agents (AGENTS.md):** `okl scaffold` (not `init`) writes the repo canon to both
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
#   add --format actions --limit 3 for a ~230-token version (subagents, CI)

# 2. RECORD a lesson after you learn it, with an actionable symptom/cause/fix
okl record --type Defect --scope org --tags "security" \
  --title  "Trusting a client-supplied price lets the client set it to anything" \
  --symptom "a request body carries a price/amount/status/isAdmin field" \
  --body    "cause: the handler saved the client's value instead of computing it" \
  --fix     "drop those fields from the request; compute them server-side" \
  --files   "**/orders/*.py"         # prints the new record's id

# ...then prove it with a check, rather than asserting it
okl verify <id> --run "pytest -q tests/test_orders.py" --expect "passed"

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
                     #   exit code alone can't self-certify. (`record --verified` is
                     #   refused; historical receipts import through `okl seed`.)
okl reverify         # re-run the stored check of every drifted lesson and re-stamp the passes;
                     #   lists the commands first and runs them only after you confirm
                     #   (or --yes), because they come from the store; --dry-run lists only
okl drift --gate     # flag lessons whose governed source changed after they were last verified
                     #   (exit 1 in CI — a stale rule is a rule nobody's re-checked)
okl export --drift   # write okl-drift.json, the committed snapshot CI's drift gate reads
                     #   when it has no store; `okl verify` creates it for the first lesson
                     #   with --files and refreshes it after that.
                     #   CI reads the COMMITTED copy, and refuses an entry whose timestamp
                     #   does not match its verify evidence, so editing the timestamp alone
                     #   cannot clear it (editing both fields can; review is the guard).
okl doctor           # names other agent-memory tools installed beside okl (claude-mem,
                     #   agentmemory, ECC, beads) and how each collides with okl's hooks;
                     #   reads settings only, changes nothing. `okl init` says the same.
okl coverage         # ratio of encoded-knowledge lines to code lines — a health signal
okl bootstrap        # cold-start a new repo: propose starter notes from its own
                     #   git history + docs into a reviewable file you edit, then seed
okl metric           # recurrence: defect classes that came back, split by whether a
                     #   gate existed, with how many defects the number can speak for
```

## Subagents and small context budgets

A full briefing costs roughly **1,650 tokens** on the measurement above — fine for a main session with a large
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

**Measured on the 161 bundled seed records, one representative task:** ~230 tokens at
`--limit 3`, ~380 at `--limit 5`, ~520 at `--limit 8` and ~830 at `--limit 12`, against
~1,650 for the full briefing. Cheap enough to call per subtask.

The full briefing is itself capped: `check` keeps the top `--limit` records (12 by
default) from the ranked, filtered set and says how many it trimmed. Historically, before
that cutoff existed, one task on this repo's store at the time returned 20 records and
~4,400 tokens. The cutoff did
cost one retrieval: `exit_code_trust`'s governing rule ranks below the top 12 for that
task's wording. Run outcomes hid it (the briefing still prevented the defect, through
other records); `evals/preflight.py` found it by asking directly whether each task's rule
is in its briefing, and it is kept in a named register rather than silently. See
[evals/REPORT.md](evals/REPORT.md) §4b's correction.

What it drops: the bucketed sections (Decisions among them), the prose bodies explaining *why* each record
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

1. **Assertion is refused at the CLI.** `okl record --verified` (a bare claim, no
   evidence) exits 2 and points at `okl verify`. Two doors stay open: `okl seed` imports
   historical, already-verified stamps, and the shared service's API still accepts
   `verified: true` on a record. What closes the loop is CI: its snapshot reader rejects
   any stamp that carries no `okl verify` evidence.
2. **Observed check with a stored trail** — `okl verify <id> --run "pytest -q"
   --expect "passed"` runs the check itself, reads the real outcome, requires the
   positive signal (exit 0 alone can't self-certify), and stores command + result +
   timestamp on the node (`verified_by`). Every stamp is inspectable and re-runnable;
   a lazy check becomes a visible artifact instead of an invisible belief.
3. **An independent actor re-checks** — CI runs `okl drift --gate` and the method
   gates on every PR: a mechanical grader with no stake in the original claim. Nothing
   shipped writes `VERIFIED_ON` receipts by default; a gate script can emit one with
   `okl link <gate_id> VERIFIED_ON <defect_id>` when it watches a gate prove itself.
4. **Time attacks every stamp** — `drift` re-grades verifications the moment governed
   files change after `verified_at`; a record given `--ttl-days` decays into `STALE` when
   nobody re-earns it (there is no TTL by default);
   and `okl metric` scores the whole system on outcomes — defect classes that came
   back — the one number it can't flatter itself on. It earns that by stating its own
   coverage (how many defects have a gate it could speak for) and by counting
   recurrences with no gate separately: lessons written down that came back anyway.
   Until issue #31 it printed a bare "0 ✓" while the store held three recurrences.

## Seed it (so the very first `check` returns something)

An empty store returns nothing, and says so — a check against an empty store reports
that it proved nothing rather than reporting "no rules apply". Three ways to fill it:

**1. See what ships, then choose.** A bare `okl seed` imports nothing; it lists the
bundled packs with their record counts and subject tags, marking the ones that match
this repo's declared interests:

```bash
okl seed                              # list the packs, import nothing
okl seed rag-defects                  # import one, by name (a path to any pack file works too)
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
best maintained in third-party collections, so `.claude/skills/RECOMMENDED-COMPANIONS.md`
points at those instead of vendoring someone else's work and its cross-references.

The scaffold runs with no store at all; the store works in a repo that never scaffolded.
They are complementary, not a package deal.

**Storage is swappable** via one environment variable — your commands never change:

```bash
# default: no variable at all — the store is .okl/okl.db beside the repo's config
# an explicit SQLite file, e.g. one several local repos share
export OKL_DATABASE_URL="sqlite:///path/to/okl.db"
# a shared database when several repos need one store
export OKL_DATABASE_URL="postgresql://user:pass@host/okl"
okl serve --port 8080
```

## Run the shared service

```bash
pip install "observed-knowledge-ledger[service]"
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
pip install "observed-knowledge-ledger[mcp]"
okl mcp     # register in your coding agent's tool config
```

Exposes three tools to a coding agent: `okl_check` (read lessons before a task),
`okl_record`, `okl_search`. `okl_check` **reports an outage loudly** — if a configured
shared instance is unreachable it says so rather than returning a reassuring
"nothing found," because those two look identical from the agent's side and only one
is safe. Unlike the hook, a tool result cannot block the agent; it can only warn it.

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
  ownership.py    # okl-fingerprint lines: which installed files are okl's, and untouched
  coexist.py      # `okl doctor`: detects other agent-memory plugins and double wiring
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
pip install -e ".[dev]"   # from a clone of this repo
pytest -q                 # full suite
```

Some tests skip rather than fail where git is unavailable (or `git init` is blocked) or
an optional extra such as `service` is not installed.

## License

MIT.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for setup, the repo's own rules (mirror files,
drift, evidence-based verification), and where help is most useful. Security policy and
the deployment threat model: [SECURITY.md](SECURITY.md).
