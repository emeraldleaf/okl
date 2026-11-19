# The method kit (`okl scaffold`) and the shared service, both optional

Part of okl's documentation; the [README](../README.md) is the short version. Neither is installed unless you ask; the store and the gate work without them.

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

The kit's scripts read these environment variables, each optional:

| Variable | Read by | What it sets |
|---|---|---|
| `CANON_WARN`, `CANON_FAIL` | `gates/check-canon-size.sh` | the line counts above which `CLAUDE.md` warns and fails: 200 and 300 unless set |
| `OKL_DIAGRAM_SRC_EXT`, `OKL_DIAGRAM_OUT_EXT` | `gates/check-diagram-pairs.sh` | the extensions of a diagram's source and its render: `excalidraw` and `svg` unless set |
| `REVIEW_CMD` | `ci/review-agent.sh` | the reviewer: any CLI that reads a prompt on stdin. Unset, the review is skipped ([COSTS-AND-KNOBS.md](COSTS-AND-KNOBS.md) has what it costs) |
| `REVIEW_BASE_REF` | `ci/review-agent.sh` | what the diff is taken against: `origin/main` unless set. The kit's workflow passes the pull request's base |
| `AGENT_FILE` | `ci/review-agent.sh` | the reviewer's instructions. Unset, the first `architecture-reviewer.md` within three directories of the root |
| `REVIEW_REPO_DIR` | `ci/review-agent.sh` | the checkout, so a reviewer that can read files is told where it is. With `GIT_DIR` set as well, it is also told that git already points there |
| `REVIEW_PR_TITLE`, `REVIEW_PR_BODY` | `ci/review-agent.sh` | what the change says it does (the body's first 4,000 bytes) |
| `REVIEW_BRIEFING_FILE` | `ci/review-agent.sh` | a file holding `okl check`'s briefing for the change (its first 20,000 bytes) |
| `REVIEW_CI_RESULTS_FILE` | `ci/review-agent.sh` | a file holding what the change's tests, linters and type checks reported (its first 30,000 bytes), so a reviewer that runs nothing still reads them |
| `REVIEW_EXCLUDE` | `ci/review-agent.sh` | git globs left out of the diff the reviewer reads, as data, and listed for it to open: lockfiles unless set |
| `REVIEW_MAX_LINES`, `REVIEW_MAX_PARTS` | `ci/review-agent.sh` | the diff is reviewed in parts of at most 4,000 lines, one fresh call each, at most 4 parts; files past the last part are named as not reviewed, on the PR and in the log |
| `GENERATOR_MODEL`, `JUDGE_MODEL` | `evals/run_evals.py` | the models that answer and grade. The harness refuses to run when both are set and the same |

It also stamps two **first-party method skills** — `encoding-loop` (turn a finding
into a promoted, recorded lesson) and `verify-before-claiming` (evidence before you
assert a result) — and `okl-review`, the review after writing that the Stop hook names
(`okl init` installs that one too, since it needs the okl CLI). The broader engineering-discipline skills (systematic debugging,
TDD, plan writing/execution, git-worktree isolation) are **not bundled** — they're
best maintained in third-party collections, so `.claude/skills/RECOMMENDED-COMPANIONS.md`
points at those instead of vendoring someone else's work and its cross-references.

The scaffold runs with no store at all; the store works in a repo that never scaffolded. okl's own drift gate is
`okl init`'s job (a pre-push hook, or the GitHub workflow with `--ci`), so scaffold leaves it alone.
They are complementary, not a package deal.

**Storage is swappable** via one environment variable — your commands never change:

```bash
# default: no variable at all — the store is .okl/okl.db beside the repo's config
# an explicit SQLite file, e.g. one several local repos share
export OKL_DATABASE_URL="sqlite:///path/to/okl.db"
# a shared database when several repos need one store
export OKL_DATABASE_URL="postgresql://user:pass@host/okl"
okl serve --port 8080   # off loopback it needs OKL_TOKEN: see the next section
```

## Run the shared service

```bash
pip install "observed-knowledge-ledger[service]"
export OKL_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
OKL_DATABASE_URL="postgresql://user:pass@host/okl" okl serve
# repos then: okl connect https://your-host --token "$OKL_TOKEN"
```

**Set `OKL_TOKEN`.** With it, every route requires the bearer token except `/health`
(left open so schedulers can probe it). Without it, every route would be open — including
`GET /nodes`, which hands the whole store to anyone who can reach the port — so `okl serve`
refuses to start off loopback, and `uvicorn okl.service:app` anywhere, unless you opt in:
`okl serve` takes `--allow-no-token` or `OKL_ALLOW_NO_TOKEN=1`, and `uvicorn` only the
variable. A mature
store is a catalogue of your known defects and internal architecture, which is a map of
where you are weak. It is a single shared secret with no per-repo scoping or rotation;
put a real authenticating proxy in front if you need more.

Full instructions, including a throwaway Postgres for trying it locally and what the
failure modes look like: **[docs/DEPLOY.md](DEPLOY.md)**.
