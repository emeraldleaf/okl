# Developing okl

How okl is built, tested, measured and released, end to end. It is for contributors and
for the maintainer six months from now.

The rules the build enforces are in [CONTRIBUTING.md](../CONTRIBUTING.md), and the short
contract every agent working here follows is [CLAUDE.md](../CLAUDE.md). This guide doesn't
repeat them. It puts them in the order you meet them. The evaluation method and every
result live in [evals/REPORT.md](../evals/REPORT.md).

## The shape of the code

```text
src/okl/
  store.py        the port: Node/Edge, the SQLite and Postgres backends, append-only logs
  core.py         the domain: check, record, update, retire, verify, get, log_check
  drift.py        which lessons' governed files changed since their check passed
  recap.py        the lessons a session touched (read from its transcript)
  client.py       one entry point, local store or remote service
  cli/            the okl command (one module per area)
  service.py      the shared FastAPI service
  mcp_server.py   the MCP tools for agents
  seed.py         loading the packs in seed/
  scaffold/       what okl init and okl scaffold write into other repos
```

- **Dependencies point one way.** The order is cli, then service, mcp_server and seed, then
  client, recap, core and drift, then store. `lint-imports` fails the first import that
  points up (the contract is in `pyproject.toml`).
- **The core is stdlib-only.** Every third-party import lives behind an extra (`[mcp]`,
  `[service]`, `[postgres]`).
- **Both store backends meet one contract.** It is written in the `_Backend` docstring, and
  one conformance test runs against SQLite and, when `OKL_TEST_POSTGRES_URL` is set,
  against Postgres.

## The everyday loop

1. **Branch from main.** Use a git worktree if the main checkout is busy, for example
   during an A/B run. A worktree has no store, so re-verify from the main checkout (step 6).
2. **Write the test first, and watch it fail on the old code.** A test that passes on both
   versions proves nothing. When a change touches shell hooks, run the tests under macOS's
   `/bin/bash` 3.2 as well: the hooks must work there.
3. **Make the change, then run what CI runs:**

   ```bash
   pytest -q --cov=okl               # strict, and enforces the coverage floor (66%)
   ruff check .
   mypy src/okl
   lint-imports
   bash gates/run-gates.sh           # links, doc orphans, diagram pairs, tombstones, canon size
   ./ci/check-diagram-figures.sh     # every figure in a diagram names a committed receipt
   ```

4. **Keep mirrored files identical.** If you edit a hook, re-stamp its ownership line and
   copy it to its twins:

   ```bash
   python3 -m okl.ownership --stamp hooks/<file>.sh
   cp hooks/<file>.sh src/okl/scaffold/hooks/ && cp hooks/<file>.sh .claude/hooks/
   ```

5. **Change the docs in the same PR.** That means the README, `docs/GETTING-STARTED.md`,
   the CHANGELOG's `## Unreleased` section, and the diagram if what it shows changed. The
   diagram is edited in the `.excalidraw` source and re-rendered to SVG. The website's okl
   page and its copy of the diagram follow each release.
6. **Commit, then re-verify, then commit the snapshot** (maintainer). This order matters:

   ```bash
   git commit ...                          # the code change first
   okl reverify --yes                      # re-runs each drifted lesson's stored check
   git commit -am "Re-verify ..."          # the refreshed okl-drift.json
   okl drift --gate --snapshot okl-drift.json   # exits 0: what CI will see
   ```

   CI's drift gate reads the committed `okl-drift.json`, not the store. Verifying before
   the code commit records the old commit, so the lesson drifts again.

## The loop runs on this repo

okl is developed with its own hooks switched on:

- **Before every prompt,** the UserPromptSubmit hook briefs the agent with the lessons that
  match the prompt.
- **At the end of a session,** the Stop hook asks what was learned and lists the lessons
  the session touched (`okl recap`). Answer it.
- **Recording:** `okl record` with a stable `--id`, a deliberate `--scope` (`org` if true
  in any repo, `repo` if true only here), and tags from the closed vocabulary.
- **Correcting:** `okl update <id>` changes a lesson and keeps its proof, unless its
  governed files change.
- **Retiring:** `okl retire <id> --reason "..." [--by <new-id>]` takes a wrong or replaced
  lesson out of use. Nothing is ever deleted.
- **Never export `OKL_DATABASE_URL`.** Set it per command. An exported one once made a test
  run write fixtures into the real store.

## CI: what runs, and why

| Workflow | Job | What it checks |
|---|---|---|
| `ci.yml` | lint-and-test (Python 3.12) | ruff, mypy, lint-imports, pytest with a coverage floor (66%), diagram figures, the method gates, gitleaks, and an architecture review that runs only when `REVIEW_CMD` is set |
| `ci.yml` | tests-other-pythons | the suite on 3.10, 3.11, 3.13 and 3.14 |
| `okl-verify.yml` | drift gate | the committed `okl-drift.json`: a rule whose governed files changed since its check passed fails the build |
| CodeQL | Analyze | GitHub's code scanning |
| `publish.yml` | build, publish | on a `v*` tag only (see Releasing) |

A PR that changes a governed file turns `okl-verify` red until the maintainer re-verifies.
That is expected; see CONTRIBUTING.

## Pull requests and issues

- **Name the issue.** Write `Closes #N` (or `Part of #N` for a slice) in every PR, so
  merging closes it. The roadmap is the
  [`loop-review` issues](https://github.com/emeraldleaf/okl/issues?q=is%3Aopen+label%3Aloop-review).
- **Resolve every review thread.** CodeRabbit reviews each PR, and `main` requires every
  conversation resolved. Fix the finding, reply on the thread with the fixing commit, then
  resolve it.
- **Check that CodeRabbit actually reviewed.** Its plan allows a few reviews an hour. When
  it posts "Review limit reached", its check still shows as passed, but it reviewed
  nothing.
- **Get an independent review for risky changes:** hooks, retrieval, storage, anything
  that fails open. Ask a reviewer, human or agent, to try to break the change. Several
  real bugs in this repo were found that way before review bots saw them.
- **Merge commits only.** Squash and rebase are disabled, because drift reads commit
  history. Head branches delete themselves on merge.

## Releasing

1. **On a `release-X.Y.Z` branch,** set the version in `pyproject.toml`, in `server.json`
   (twice), in `.claude-plugin/plugin.json` and in `docs/GETTING-STARTED.md` (twice).
   Rename the CHANGELOG's `## Unreleased` to `## X.Y.Z`. Reinstall the editable package so
   the version test passes: `pip install --no-deps -e .`.
2. **Commit, re-verify, open the PR, merge.**
3. **Tag the merge commit:**
   `gh release create vX.Y.Z --target <sha> --title X.Y.Z --notes-file <that CHANGELOG section>`.
   The tag starts `publish.yml`. It builds, checks that the tag matches `pyproject.toml`,
   then waits at the `pypi` environment for the maintainer's approval.
4. **Publish to the MCP Registry** from the repo, in a regular terminal (it asks for a
   GitHub device code): `mcp-publisher login github && mcp-publisher publish`.
5. **Check what was published.** PyPI should list the version. Then launch the server the
   way a registry client would,
   `uvx --with 'mcp>=1.2' observed-knowledge-ledger==X.Y.Z mcp`, and confirm it answers
   `initialize` with `serverInfo.version` X.Y.Z and lists its tools.
6. **If the hooks changed,** refresh them in repos set up with `okl init`: run
   `okl init --repo <name> --no-seed`, or copy the scaffold hook byte for byte. Then
   update the website's okl page.

## Evaluations

Read [evals/REPORT.md](../evals/REPORT.md) first, and
[evals/README.md](../evals/README.md) for the harness. The rules that keep the numbers
honest:

- **Pre-register before any live run.** Write a REPORT section with what changed, the
  prediction, and the result that would falsify it.
- **The judge is never the generator.** The harness refuses the same command string, and
  the same resolved model.
- **More than 20% failures means RESULTS NOT USABLE.** Never quote a number from such a
  run.
- **Every cited figure has a committed receipt** in `evals/results/`.
- **A changed instrument starts a new series.** That covers a different judge, judge
  prompt or resolved model, and the new run is not pooled with older ones.

### Run the deterministic checks first

They take seconds and call no model:

| Script | What it answers |
|---|---|
| `evals/preflight.py` | Recall: does each eval task still receive the rule it tests? |
| `evals/precision.py` | Noise: does a prompt with no subject ("ok go") brief at most 3 lessons? It uses a store built only from the seed packs. |
| `evals/layout_preflight.py --old-ref main` | Rendering: does a change to the briefing's layout lose any content? It renders one retrieval twice, so it cannot see a retrieval change. |
| `evals/briefing_size.py` | Briefing size in tokens. |

### When an A/B run is required

Run one for any change to what the briefed arm receives: retrieval, ranking, filtering or
rendering. To skip it, show the eight bait briefings are byte-identical before and after
the change. Then:

```bash
python3 evals/ab_harness.py --samples 3 --dry-run
OKL_BRIEF_INTERESTS="python,method,security,agent-safety,retrieval-design,eval-integrity,data-quality" \
  python3 evals/ab_harness.py --samples 3
```

- **Cost:** 48 generations and 48 judgments, about an hour and a half.
- **Keep the checkout still.** It must stay on the committed branch for the whole run: the
  harness briefs from whatever code is checked out, and stamps that commit on the receipt.
- **The receipt** records the commit, the resolved models, each sample's code length, and
  any sample with no code to judge, marked unevaluable.
- **Afterwards,** write the result under its pre-registration in REPORT, against the
  prediction, and commit the receipt with it.

## Observability: what you can see today

| Command | What it shows |
|---|---|
| `okl metric` | Which lessons briefings showed, and which were never shown (candidates to retire); the lessons shown most that have no check; recurrence: lessons that came back after a check guarded them, and without one |
| `okl show <id>` (MCP `okl_get`) | One lesson: its proof, why it was retired, and every run of its check, with pass and fail counts and its last failure |
| `okl drift` | Lessons whose governed files changed since their check passed |
| `okl recap --transcript <path>` | The lessons a session was briefed on and those whose files it changed |
| `okl dedup` | Near-duplicate lessons, for review |
| `okl doctor` | Other agent-memory tools beside okl, how they collide, and where drift is gated |
| `okl coverage` | How much of the code the store's lessons govern |

`metric`, `show`, `drift` and `coverage` also take `--format json`. Not built yet: which
session saw which lesson, a log of every change to a lesson and why, `okl log`,
`okl explain`, and a weekly sampled review. Those are
[#129](https://github.com/emeraldleaf/okl/issues/129).

## Where decisions are written down

| Where | What it holds |
|---|---|
| [CLAUDE.md](../CLAUDE.md) | The always-on rules |
| [CONTRIBUTING.md](../CONTRIBUTING.md) | What the build enforces, and why |
| [docs/decisions/](decisions/) | ADRs: decisions with their alternatives and triggers |
| [evals/REPORT.md](../evals/REPORT.md) | Every measurement, its method and its limits |
| [CHANGELOG.md](../CHANGELOG.md) | What each release changed, for users |
| Issues | Open work, including the roadmap (`loop-review`) |
| The store | Lessons, briefed to agents as they work |

When you learn something here, ask which of these it belongs in. Usually it's the store.
