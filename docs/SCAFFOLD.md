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

It also stamps two **first-party method skills** — `encoding-loop` (turn a finding
into a promoted, recorded lesson) and `verify-before-claiming` (evidence before you
assert a result). The broader engineering-discipline skills (systematic debugging,
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
failure modes look like: **[docs/DEPLOY.md](DEPLOY.md)**.
