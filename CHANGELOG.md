# Changelog

## Unreleased

- **A Python canon: `okl seed python-canon`.** 17 lessons that translate the .NET packs'
  engineering rules to Python. Each one cites the sources that agree on it (PEPs 20, 257,
  544 and 735; the mypy, pytest and import-linter docs; Google's Python style guide; the
  Scientific Python development guide) and the okl change that adopted it. It covers the
  dependency rule as an import-linter contract, docstrings, type hints, size limits, strict
  pytest, errors, mocks, and two dated defects. Nothing in it claims verification: verify
  each lesson against your own repo. `okl init` in a Python repo now imports it with the
  other packs that match the stack.
- **A command run where okl was never set up now refuses (exit 2) instead of writing to a
  stray `./okl.db`** (#117). `okl record` and `okl seed` used to exit 0 having saved their
  lessons where no hook, check or CI job looks, and `okl coverage` reported a clean zero.
  Every command that needs a store now says so and stops: run `okl init` first, or name a
  store with `OKL_DATABASE_URL` or `okl connect <url>`. Listing packs (`okl seed`) still
  works anywhere.
- **A shared service answers an unknown link relation with a 400**, not a 500 the client
  reported as an outage (#119).
- **More "could not run" cases exit 2**, as the CLI's contract says: `okl seed <dir>` when the
  directory holds no packs, and `python -m okl.ownership --stamp` on a file it cannot read
  (it raised a traceback). The MCP `okl_check` tool reports a refused request (a 401, or no
  store named) as "OKL REFUSED THE CHECK" rather than a raw tool error.
- **`okl serve` and `okl mcp` without their extra exit 2** and name the install command
  (`observed-knowledge-ledger[service]` or `[mcp]`); they raised a traceback, and serve
  named a package that no longer exists.
- **The scaffolded eval runner exits 2 when it has no cases file**, as it already did for
  an empty one: nothing was measured either way.
- **okl closes its SQLite connections** (#116). Python 3.13 warns about every connection
  that is never closed, and okl opened one per command.
- **Tested on Python 3.10 to 3.14** (#116); CI had tested 3.12 alone. 3.10 reached end of
  life on 2026-10-01, and is still supported for now.
- **The shipped `okl-verify` workflow** recognises okl's own source checkout by
  `src/okl/__init__.py` instead of `src/okl/cli.py` (#120). Re-running `okl init` upgrades
  an installed copy you have not edited.
- **Contributors:** okl's own dev tools moved from the published `[dev]` extra to a PEP 735
  dependency group (#121). Install with `pip install -e . --group dev` (pip 25.1 or later)
  or `uv sync`.
- **Internals:** the CLI is now a package, `okl.cli`, with one module per command group
  (#120); `okl.cli:main` is unchanged. The MCP `okl_record` tool takes keyword arguments
  only, which is how MCP clients already call it (#118).

## 0.7.8

- **Re-seeding keeps a lesson's verification** (#110). `okl seed` replaced each row, so
  every re-seed re-stamped its lessons as verified now and wiped their evidence and
  commit. A repo that keeps its lessons in a seed file and re-seeds after an edit could
  therefore never drift, and its next drift snapshot carried stamps with no evidence. A
  re-seeded lesson now keeps its stamp, evidence and commit while its governed files are
  the same, and is cleared when they change. New lessons and `okl record` re-records
  behave as before.
- **`okl drift` names this repo's lessons whose files match nothing committed** (#109), beside the
  drift report and as `governs_nothing` in its JSON. Drift saw the deletion as the last
  change, so such a lesson watched nothing and nothing said so. Re-pointing it, dropping
  its files or retiring it is a decision, so the exit code is unchanged.
- **`okl init --no-ci`** skips the GitHub Actions workflow (#111), for a private repo that
  would pay for its minutes or one that runs another CI. The choice is recorded in
  `.okl/config.json`, so later runs keep it; `--ci` turns it back on, and `okl doctor`
  says when drift is not gated in CI.

## 0.7.7

- **The docs say what okl is not for** (#99): always-on rules and commands go in
  `CLAUDE.md` / `AGENTS.md`, procedures in a skill or runbook, style in a formatter or
  linter, open bugs in the issue tracker, secrets nowhere near the store. Everything with
  a symptom and a fix belongs in okl.
- **Drift compares the commit a check passed at, not the clock** (#102). `okl verify`
  records HEAD, and a rule has drifted when its governed files differ between that commit
  and HEAD. Comparing times missed a change committed in the same second as the check,
  since git keeps commit time to the second, and read a commit from a clock running ahead
  as a change the check never saw. A change and its revert no longer count either. The CI
  gate, `okl drift`, `okl reverify` and the briefing's STALE mark share the one verdict.
  Verifications from before this, or whose commit a clone lacks after a squash, still
  compare times. The commit is written into the evidence ahead of the time stamp, which
  binds it in `okl-drift.json` (a hand edit is refused, as an edited time already is)
  and keeps older okl versions reading the snapshot. Stores gain the column on open.
  One mixed-version limit: an older okl's `okl reverify` cannot parse the commit in this
  version's evidence when the check has an expected signal, so it lists those lessons as
  needing a first check rather than running a weaker one. Upgrade the clients that share
  a store together.
- **`okl verify` warns when the governed files have uncommitted changes**: the check saw
  them, but the record points at the commit without them, so the lesson would read as
  drifted once they are committed.
- **A STALE lesson in a briefing says what to do**: re-run its check with `okl reverify`,
  and if it fails, fix the code or change the lesson on purpose.

## 0.7.6

- **An entry for the official MCP Registry** (`server.json`, `io.github.emeraldleaf/okl`).
  Registry clients start a PyPI server as `uvx <package> <args>`, and uvx runs the command
  named after the package; okl's only command was `okl`, so that failed. The CLI now also
  installs as `observed-knowledge-ledger`, and the entry adds the MCP SDK
  (`--with mcp>=1.2`) that okl keeps in its optional `mcp` extra.
- **The PyPI page links back to the repo**, its issues, the changelog and the getting
  started guide. It had no project links.

## 0.7.5

- **Ready for the official MCP Registry.** The README carries the registry's ownership line
  (`mcp-name: io.github.emeraldleaf/okl`), which the registry checks against the PyPI
  package before it will list the server.
- **The prompt hook retries a briefly unavailable store before blocking.** Three tries over
  about a second, so a prompt that lands while a repo rebuilds its gitignored store is
  briefed instead of refused. A store that stays gone still blocks, with okl's reason; an
  okl that cannot start is not retried. The fix had lived only in one repo's edited copy
  of the hook (#91).
- **Briefings mark lessons whose code changed after their last check** (#93). A briefed
  lesson that governs files changed since its last `okl verify` is tagged *STALE*, with the
  file and dates and `okl reverify`; one that governs files but has never passed a check is
  tagged *UNVERIFIED*. The briefing's footer and the per-prompt notice count them. Only
  `okl drift` and CI said this before; the agent reading the lesson did not. Computed on
  the client, so it also works against a shared service.

## 0.7.4

- **`okl verify` / `okl reverify` treat a timeout as a failed check.** A check that
  outlived `--timeout` raised an uncaught error, so `okl reverify` stopped in a traceback
  and every later lesson went unchecked.
- **`okl_search` results lead with the lesson id**, so an agent can pass it to
  `okl_record` to update the lesson instead of adding a near-duplicate.
- `.coverage` is no longer tracked.

## 0.7.3

- **A first run that works with no choices.** `okl init` detects the stack and sets
  interests from it, and seeds an empty local store with 20 portable starter lessons plus
  the bundled packs for that stack, so the first prompt is briefed. `--no-seed` opts out.
  Starter lessons are references into the packs, so importing a full pack later updates
  the same rows.
- **You can see okl working.** Each briefed prompt shows one line, *okl · briefed N
  lesson(s): …*, via `okl check --format hook`; `OKL_QUIET=1` hides it. The hook falls back
  to the plain briefing if the installed okl predates the format.
- **Record by saying it.** The `okl_record` MCP tool takes `id` (re-recording updates the
  lesson) and `applies_to`, so any MCP agent can record what the CLI can; a new `/record`
  command drafts a lesson from the conversation and records it once you confirm. The
  getting-started guide leads with this, covers other agents, and keeps the CLI as the
  mechanism underneath.
- **Choosing how hard to enforce a lesson.** The Stop hook's question, `/record` and the
  guide now walk the same levels — briefing only, watched by CI (`--files` + `okl verify`),
  build-breaking (a test or CI check), always-on (`CLAUDE.md`/`AGENTS.md`) — and the plugin
  now ships the `encoding-loop` skill that holds the full table.
- **`okl reverify`** re-runs the stored check of every drifted lesson after listing the
  commands and getting a confirmation (or `--yes`).
- **`okl verify` creates `okl-drift.json`** the first time a lesson that governs files is
  verified, so there is no separate export step.
- **The plugin's hooks step aside in repos never set up with `okl init`**; Decisions reach
  the briefing; the service keeps `applies_to`; a getting-started guide
  (docs/GETTING-STARTED.md); a docs audit's ~74 corrections; clean example re-runs.

## 0.7.2

- **`okl record --verified` is refused.** It stamped a lesson verified with no evidence,
  while the README said live verification refused it and the shipped `encoding-loop` skill
  told agents to pass it. It now exits 2, writes nothing, and points at `okl verify`, the
  only live route to a stamp. Historical, already-verified records still import through
  `okl seed`, and CI's snapshot reader already rejected evidence-less stamps.

## 0.7.1

- **A Quickstart, and `okl init` wires Claude Code without an existing `.claude/`.**
  A fresh-install walkthrough of the README found the path spread over ~350 lines and
  one trap: `init` installed hooks only when `.claude/` already existed, which many repos
  lack, so the pre-task briefing silently never ran. `init` now also wires Claude Code
  when `claude` is on PATH, or with `--claude` (`--no-claude` opts out; okl's own plugin
  always wins, so nothing is wired twice), and `--dry-run` says which applied. The
  README gains a four-step Quickstart and "what a normal day looks like", and stops
  teaching `record --verified` (the assertion the verification section quarantines),
  seeding by file path (packs load by name), and committing a drift snapshot before any
  rule governs files (CI reads an empty one as broken, and fails).

- **The doc-orphans gate sees images** (#68). It walked `docs/*.md` only, so a diagram
  nothing linked to was invisible to it; it now checks images too and reads the committed
  tree. It found an unlinked results chart carrying unreceipted figures, now deleted,
  along with the unlinked architecture diagram (#67).
- **Docs caught up with the eval report** (#66): the diagram's figures, the README's
  top-k cutoff claim, and the Stop hook's header.

## 0.7.0

- **A dead okl path no longer turns the block into a warning** (#64). The marketplace
  E2E found the pre-task hook exiting 2 and the prompt going through anyway: the pinned
  `okl_bin` pointed into a deleted venv, bash wrote `No such file or directory` into the
  hook's stderr, and Claude Code read that phrase as "hook script missing" — a
  non-blocking configuration error. Both hooks now use a resolver layer (`OKL_BIN`, the
  pin, PATH, `python3 -m okl`) only if it can actually run, so a stale pin falls through
  instead of being executed; the block names the dead pin and never relays that phrase.
  Receipt: `evals/results/e2e-20260927-marketplace/` — install from the marketplace
  works, `okl doctor` catches the double wiring, and the A/B of old hook vs new in the
  same dead-pin repo.
- **Two worked examples, each with receipts** (#59, #62): `examples/python-fastapi/` and
  `examples/dotnet-minimal-api/` — a small orders service, three bait tasks from the eval
  set (IDOR, client-supplied price, unbounded search) and `run_demo.sh`, which plays each
  task in a control copy and a briefed copy with a real coding agent and keeps the diffs,
  final messages and the exact briefing. n=1 per arm, so illustration, not measurement:
  `price_tamper` and `rate_limiter` discriminate on both stacks (the control ships the
  defect, the briefed arm applies the recorded fix in the framework's own idiom);
  `idor_endpoint` does not, because the examples' own comments telegraph ownership.
  The .NET one is the stack most of the bundled lessons came from.
- **Coexistence receipt** (#60, `evals/results/e2e-20260927-coexist/`): okl's project
  hooks beside another memory plugin loaded for the session. okl's loop worked; the other
  tool captured `okl record` as a tool use (one lesson, two stores); `okl doctor` named
  it. It also corrected a shipped claim — that tool's Stop summariser ran **once** beside
  okl's blocked stop, not twice; doctor now says what was seen.
- **The test suite is deaf to a real store named in the environment** (#61). An exported
  `OKL_DATABASE_URL` leaked into two `pytest` runs and wrote 28 fixture records into the
  real store. An autouse fixture now strips `OKL_DATABASE_URL`, `OKL_SERVICE_URL` and
  `OKL_TOKEN` for every test; proven the way the incident happened (suite run with the
  variable exported, store count unchanged).

- **okl is a Claude Code plugin** (#45): `/plugin marketplace add emeraldleaf/okl` then
  `/plugin install okl@okl`. It carries the hooks, the MCP tools and the seeding commands;
  the CLI is still installed with pipx. `okl init` skips hook and MCP registration when the
  plugin is enabled, and `okl doctor` reports a repo wired both ways. The scaffold's
  `hooks/hooks.json` gained the top-level `hooks` key the plugin loader expects.
- **Fresh-install end-to-end run** (REPORT §10, receipt `evals/results/e2e-20260926/`):
  the whole loop from a wheel in a repo that had never seen okl. Every surface worked;
  two findings. In `claude -p` the Stop question's reply replaces the printed answer, so
  headless runs should set `OKL_DISABLED_HOOKS=encode` (README says so); and `okl init`'s
  pack recommendation is stack-keyed, so a Python repo is pointed at almost nothing (#54).

- **A blocked prompt says how okl failed.** The pre-task hook's block now names okl's exit
  code and what it usually means (not found, refused, error, killed by a signal) and
  whether okl's error output was captured at all. A live block read only "exited non-zero
  without a reason", and nothing recorded could explain it afterwards.

- **The briefing names each record once — 36% fewer characters across the 8 eval tasks.**
  Every record that became a routed action was printed twice: as the action, and again in
  full under its section. The action now carries the cause, a gate's symptom, what a gate
  catches and the stale marker, and the section skips it. A briefing with no routed
  actions is unchanged. A test holds the invariant (each record listed once, no field lost), and
  `evals/layout_preflight.py` proved the change lossless on all 8 eval tasks before any
  model call. This is the eval harness's treatment, so REPORT §4i pre-registers a new run.
  Eval receipts now record `okl_commit`.

- **`okl init` no longer overwrites your edits, and `okl init --uninstall` exists** (#49).
  `init` rewrote the hook scripts on every run, silently discarding a local change. Every
  file okl installs now carries a `# okl-fingerprint:` line (the hash of the rest of the
  file): an untouched okl file of any version is upgraded, an edited one is kept unless
  `--force`. `--uninstall [--dry-run]` removes okl's files and exact registrations and
  nothing else — another tool's hooks, edited files and `.okl/` stay.
- **`OKL_DISABLED_HOOKS=briefing,encode`** switches either hook off by name.
- **The Stop question lists what failed this session.** Up to five distinct failed tool
  calls, newest first, read from the transcript path Claude Code passes the hook; harness
  validation errors and permission denials are left out. They are candidates for the agent
  to judge, never records: capture stays deliberate, and nothing runs on every tool call
  or calls a model.
- **The hooks anchor to the project** (#48): run from wherever the session's directory had
  drifted, the pre-task hook blocked every prompt as "unreachable" when okl had in fact
  refused as not configured. Both hooks now `cd` to `$CLAUDE_PROJECT_DIR`, and a block
  prints okl's own reason.

## 0.6.0

**Renamed on PyPI: install `observed-knowledge-ledger`.** `org-knowledge-layer` 0.6.0 is a
final, code-free release that installs it and keeps the `okl` command working.

### Renamed: Observed Knowledge Ledger

- **The PyPI distribution is now `observed-knowledge-ledger`** (was `org-knowledge-layer`).
  The name says what is different about okl — knowledge proven by observed checks, kept
  with its evidence — where "knowledge layer" named the crowded category it is not
  competing in. `okl` itself is unchanged: the command, the import package, `.okl/`,
  `OKL_*` variables and `okl-drift.json`. The old name gets one final release (0.6.0,
  `packaging/org-knowledge-layer`) that contains no code and depends on the new one,
  extras included, so existing installs and CI steps keep working. A test holds the old
  name to an allowlist of files, so the rename cannot leave a check behind.
- **README positions okl against the Claude Code memory plugins** (#41): claude-mem,
  agentmemory, ECC and beads, from reading their source.

### Numbers that say what they rest on

- **`okl metric` states its coverage and counts recurrences it could not see** (#31). It
  printed `recurrence-after-arming: 0 … ✓` while the store held three recurrences: it only
  counted defects with a gate attached (7 of 66) without saying so, and it could not read
  the seed packs' `defect RECURS_IN <repo>` form at all. It now reports how many defect
  classes the number can speak for, lists recurrences that had no gate separately, and
  prints no tick. **`okl metric --format json` changed shape** to the report
  (`armed`, `unarmed`, `defects`, `defects_with_gate`). The service's
  `/metric/recurrence` keeps its original `recurrence_after_arming` and `count` keys, now
  derived from the same report, and adds `report`; `Client.recurrence()` keeps its v0.5
  rows the same way, beside the new `Client.recurrence_report()`. Only a `Gate` arms a
  defect now (a Rule that `CATCHES` one no longer counts as a gate). Against a service too
  old to send `report`, the CLI exits 2 and says coverage is unknown rather than guessing.
- **`okl drift --gate` no longer passes having checked nothing** (#21). An unconfigured
  directory is refused (and no `okl.db` is created by asking); a store with no rule
  governing any file reports "NOTHING CHECKED" and exits 2 under `--gate`; the all-clear
  states how many rules it checked. The shipped `okl-verify` workflow turns exit 2 into a
  "Drift not checked" warning when the job has no store, and fails when it had one.
- **`okl doctor` names memory tools that collide with okl** (#40). claude-mem,
  agentmemory, ECC and beads each hook the same events okl does: okl's Stop hook blocks
  the first stop, so their Stop hooks run twice; the capture-everything tools also record
  `okl record`, putting one lesson in two stores; and each injects context beside okl's
  briefing. `okl doctor` (exit 1 when any is found) and `okl init` name each tool found,
  where, how it collides and what to do. `okl doctor` only reads settings; `okl init`
  writes its own hook registration as before, keeping every other tool's entries.
- **CI can check drift without a store** (#36). `okl export --drift` writes
  `okl-drift.json`, the rules drift reads (ids, titles, globs, verification evidence, no
  lesson bodies); `okl drift --snapshot` reads the committed copy only, and refuses an
  entry whose `verified_at` does not match its `okl verify` evidence stamp. `okl verify`
  refreshes an existing snapshot. The shipped workflow uses it when no service is set,
  which also covers fork PRs. Seeding the rules in CI instead would have been a false
  all-clear: `record()` stamps them verified at load time. Drift's advice line no longer
  recommends `okl record --verified`.
- **`okl init` names an empty store and how to fill it** (#27), listing the bundled seed
  packs that fit the repo's declared stack. `okl seed`'s "matches your interests" marker
  now matches on stack too: a pack about .NET no longer matches a React repo because a few
  of its records are tagged `security`.

### Retrieval

- **Tags are searchable** (#14), weighted below every prose field, and content matches
  always rank ahead of records that only match on a tag.

### Fixed

- **The scaffold's recording instruction passes `--id`** (#19), so the same lesson recorded
  in two sessions is one record, not two.

## 0.5.0

### The vocabulary is no longer fixed in the package

- **A store can declare its own subject tags.** `KNOWN_TAGS` remains, but as the *floor*
  every store ships with rather than the whole vocabulary. Widen it by recording a
  `Vocabulary` node, whose title is the tag:

  ```bash
  okl record --type Vocabulary --scope org --title rust --body "Rust services."
  okl record --type Rule --scope org --tags rust --title "Prefer ? over unwrap in handlers"
  ```

  Before this, a Go, Rust or PowerShell team could not file a lesson under its own language
  without forking the package, which is a hard stop on adoption for a tool whose claim is
  that a lesson learned in one place reaches another. What the closed vocabulary was *for*
  survives: it catches the typo that files a record where nobody looks, and closed-per-store
  still does, so `rustt` is refused in a store that declared `rust`. What changes is who may
  grow it. `STACK_TAGS`, which gates `applies_to`, is deliberately not extended.

- **`frontend` and `prose` added to the floor.** Neither is specific to one org: any repo
  that renders markup has frontend lessons, and any repo that governs its writing has prose
  ones. `react` was the nearest existing tag for the first and is wrong, being a stack tag.

### Fixed

- **The hooks no longer tell you to run `pip install okl`, which cannot work.** PyPI refuses
  `okl` as confusable, so the distribution is `org-knowledge-layer` and `okl` is only the
  console script. The wrong name was in the `UserPromptSubmit` hook's not-found message,
  which fires *exactly* when someone has no working install and sent them to a 404 that
  reads as "this tool was never published." `okl init` stamps that hook into every repo it
  touches, so the error propagated with adoption. Re-run `okl init` to pick up the new file.
- `cli.py`'s MCP hint said `pip install okl[mcp]`; now `pip install 'org-knowledge-layer[mcp]'`,
  quoted because zsh globs unquoted brackets.


## 0.4.1

### Security — affects the CI workflow already in your repo

- **The shipped CI verifier no longer writes your bearer token to disk.** It ran
  `okl connect --token`, which persisted `OKL_TOKEN` into `.okl/config.json` on the runner
  for no reason: the client reads `OKL_SERVICE_URL` and `OKL_TOKEN` from the environment
  directly, so setting them at job level does the same work with the credential never
  touching the filesystem. Re-run `okl init` (or `okl scaffold`) to pick up the new file.
- **Both shipped workflows are hardened.** `okl-verify.yml` and `method-gates.yml` now
  declare least-privilege `permissions`, a concurrency group, `pipefail`, and
  `persist-credentials: false`, and pin their actions to commit SHAs rather than mutable
  tags. They satisfied none of that before.
- `.github/dependabot.yml` ships with the kit, because pinning to a SHA without an update
  path is how a repo ends up on a two-year-old action and calls it hardening.

### Added

- **Opt-in architecture review in CI.** `ci/review-agent.sh` runs the reviewer over a PR
  diff and fails on must-fix findings. **Off unless you set the `REVIEW_CMD` repository
  variable** to a CLI that reads a prompt on stdin — `claude -p` (authenticates with an
  existing Claude Code login, no separate API key), `ollama run <model>` (local, free), or
  any other. Unset, it prints one line and passes. It is the only gate in the kit that
  calls a model, which is why it is the only one that is opt-in. Documented in the README
  and the kit manifest.


## 0.4.0

### Behaviour changes worth reading before upgrading

- **Stack tags now filter exclusively.** A record naming a stack (`dotnet`, `react`,
  `geospatial`, `python`, `python-rag`) is only shown to a repo that declared that stack
  in its `interests`. Previously any shared tag let it through, so a rule tagged
  `dotnet,method` reached every repo interested in `method` — a subject 75 records carry.
  **If you declare `interests`, expect fewer records after upgrading.** That is the point,
  but it is a change in what your briefings contain. Repos that declare no interests are
  unaffected, and untagged records still always pass.
- **`symptom` and `fix` are now searchable.** They were not, which meant a record written
  the way the docs tell you to write it — short title, the distinguishing words in the
  symptom — could not be retrieved at all. Existing stores rebuild their index on first
  open; you do not need to re-record anything.

### Added

- **`okl dedup`** reports near-duplicate records for review. Lexical and explainable:
  per-field weighted Jaccard over title, symptom and fix, IDF-weighted from your own
  corpus. It never merges or drops anything — the measured score bands for true
  paraphrases and for distinct-but-related records overlap, so the call is a person's.
  The same check runs as an advisory when importing an agent-proposed pack.
- **`/seed-from-docs`** mines the specs, ADRs and rules files you already wrote into typed
  records. Built around one distinction: a record is a standing instruction that outlives
  the work item it came from, so "deep offsets use keyset pagination" belongs and "add
  pagination to /orders this sprint" does not.
- A pack declaring `_proposed_by` is refused unless every node carries a `found_by`
  citation, so the rule the seeding commands state is enforced at import rather than
  remembered by a reviewer.

### Fixed

- `Client._remote_url` validates the URL scheme once. A `service_url` from config could
  name `file://`, turning a remote read into a local file read.
- `OKLUnreachable` is now `OKLUnreachableError`, with the old name kept as an alias so
  existing `except` clauses still work.
- Drift timestamps are timezone-aware; `utcfromtimestamp` is deprecated from Python 3.12
  and returned a naive datetime that read as local time when compared across machines.

### Internal

- `_Backend` is a `typing.Protocol` whose docstring states the behavioural contract, with
  one conformance test both backends run — the defect it guards (Postgres satisfying every
  signature while running an unranked match) was invisible to signatures alone.
- mypy, and ruff widened from 6 rule families to 15 including security and complexity,
  both wired into CI alongside a secret scan, the method gates and a coverage floor.


## 0.3.1

### Security

- **Setting `OKL_TOKEN` now also removes `/openapi.json`, `/docs` and `/redoc`.** They
  were left serving 200 to anonymous callers by the 0.3.0 work that closed every data
  route, because FastAPI mounts them itself — they are not handlers, so the per-handler
  auth sweep could not reach them. They leak no records, but they publish the endpoint
  list, every schema, and which routes want a credential. With no token set the
  interactive docs remain available, since that case is a developer's laptop.

## 0.3.0

Everything here came from running three things that had been written but never
executed: the MCP server, the Postgres backend, and a deployment.

### Security

- **The service token now covers reads.** Previously `OKL_TOKEN` gated writes only, so
  an unauthenticated `GET /nodes` returned the entire store — every recorded defect,
  retired identifier and architecture decision. Every route now requires the token when
  it is set, except `/health`, which is left open for schedulers and returns no record
  content.
- **`okl connect --token` no longer commits your secret.** The token is stored in
  cleartext in `.okl/config.json`, and a comment claimed the directory was gitignored
  while nothing wrote a `.gitignore`. `okl init` and `okl connect` now write
  `.okl/.gitignore`.
- **A rejected check no longer reports success.** A 401 surfaced as `ValueError` rather
  than `OKLUnreachable`, so an unauthorized `okl check` exited 0 with a traceback — which
  a pre-task hook reads as "no rules apply". It now fails closed with exit 2, as does
  every other command, via a backstop in `main()`.

**Breaking:** if you run a service with `OKL_TOKEN` set, clients must upgrade too.
Clients older than 0.3.0 send no credential on `GET` requests and will get 401s from
`okl drift` and the recurrence metric. Upgrade the service and its clients together, or
unset `OKL_TOKEN` during the rollover.

### Fixed

- `uvicorn okl.service:app` served a module-level `None`: the process started, bound the
  port, passed a port-liveness check and returned 500 to every request. The app is now
  built lazily in a module `__getattr__`, so the standard ASGI entrypoint works while
  importing the module still does not touch the database.
- The MCP server could not start under `mcp` 2.x, which renamed `FastMCP` to
  `MCPServer` — and the error handler told you to install the extra you had just
  installed. Both names are tried, and the real import error is reported.
- Every MCP `okl_record` call with `scope="repo"` failed. The repo default used
  `setdefault`, which cannot replace an explicit `None`, and the MCP tools pass every
  field explicitly.
- MCP validation errors raised as an opaque "Error executing tool". They now return the
  complaint, so an agent that invents a tag is told the vocabulary.

### Added

- `docs/DEPLOY.md`: the shared-service deployment path, including a throwaway Postgres
  for trying it locally and what each failure mode looks like. Every command in it was
  run against a real Postgres and a real service.
- Tests covering the live MCP server, the ASGI entrypoint, service auth on reads, the
  fail-closed 401, and the config `.gitignore`.
- The Postgres/SQLite parity test now runs in a scratch schema it creates and drops. The
  first version opened with `DELETE FROM node` against whatever `OKL_TEST_POSTGRES_URL`
  pointed at, which would have destroyed the store of anyone who set it to their real
  service.

## 0.2.0 and earlier

See the git history.
