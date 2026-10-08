# Method kit — what's portable, what you fill

`okl scaffold` stamps this tree into a repo. Everything here is **portable skeleton** — it works in
any language/stack. The parts you complete per repo are marked inline with `<<FILL: ...>>`.

## What gets installed where

| Template (in package) | Installed to | Portable? |
|---|---|---|
| `root/CLAUDE.md` | `CLAUDE.md` and `AGENTS.md` (same file, two names) | skeleton + FILL slots for stack rules |
| `root/METHOD.md` | `METHOD.md` | fully portable (the seven earned rules) |
| `claude/skills/encoding-loop/`, `verify-before-claiming/` | `.claude/skills/` | fully portable |
| `claude/skills/RECOMMENDED-COMPANIONS.md` | `.claude/skills/` | reference — third-party skills worth pairing |
| `claude/agents/architecture-reviewer.md` | `.claude/agents/` | skeleton + FILL for stack checks |
| `claude/commands/feature-spec.md`, `check-rules.md`, `record.md`, `seed-from-codebase.md`, `seed-from-docs.md` | `.claude/commands/` | portable |
| `claude/rules/example-area.md` | `.claude/rules/` | template — copy per area, set `paths:` |
| `gates/*.sh` | `gates/` | fully portable (retractions/tombstones/doc-orphans/links/diagram-pairs/canon-size) |
| `registries/*` | `registries/` | portable format; FILL entries as earned |
| `evals/*` | `evals/` | portable harness; FILL `evaluate_one()` + `cases.jsonl` |
| `ci/method-gates.yml` | `.github/workflows/` | portable |
| `ci/okl-verify.yml` | `.github/workflows/okl-verify.yml` | not copied by scaffold — okl's drift gate in CI, installed by `okl init --ci` |
| `ci/dependabot.yml` | `.github/dependabot.yml` | portable — keeps the workflows' SHA-pinned actions current |
| `ci/review-agent.sh` | `ci/review-agent.sh` | portable, opt-in (see below) |
| `hooks/*` | `.claude/hooks/` | UserPromptSubmit briefing (fail-closed in repos set up with okl) + Stop encode reminder; copied by scaffold, registered by `okl init` |
| `git-hooks/pre-push` | git's hooks directory (honours `core.hooksPath`) | portable; not copied by scaffold — installed by `okl init` (the default in a git repo without okl's CI workflow; `--git-hook` forces it, `--no-git-hook` skips it) |
| `MANIFEST.md` (this file) | `docs/method-kit-manifest.md` | reference |
| `plugin/plugin.json` | `.claude-plugin/plugin.json` (if `--plugin`) | portable — packages the skills, agent and commands as a Claude Code plugin (hooks stay with `okl init`) |

## The portable / stack-specific boundary (the load-bearing decision)

- **Portable (ships as-is):** the encoding loop, the five in-repo surfaces (a sixth, okl, spans repos), the seven earned rules, the
  drift-gate *scripts*, the eval *invariants* (failure-count-first, no self-grading judge, cross-tab),
  the fail-closed pre-task hook, the registries *format*.
- **Stack-specific (you fill):** the actual coding rules that make an agent code *your* way — framework
  choices, domain constraints, pipeline conventions. These go in `.claude/rules/<area>.md` (with a
  `paths:` glob) and the `<<FILL>>` slots, and are recorded to okl at `--scope repo` so they never
  leak into another repo's `okl check`.

Grep for `<<FILL` after scaffolding to find every slot you still need to complete:
`grep -rn '<<FILL' .`

## Stack profiles — real canon, not FILL slots

The `<<FILL>>` slots above are the empty path. If your repo's stack matches one the kit already knows,
skip the FILL work and stamp a **profile** — verbatim canon lifted from a real repo, dropped straight
into `.claude/rules/` as path-scoped rule files:

| `--profile` | Source repo | Rule files | Path scope |
|---|---|---|---|
| `dotnet` | the .NET platform | architecture, security, performance-and-data, messaging | `**/*.cs`, endpoints, features |
| `geospatial` | the geospatial pipeline | geospatial-ml | `**/*.py`, `**/*.yaml` |
| `python-rag` | the RAG service | rag-pipeline, fastapi-backend, project-structure | `**/*.py`, `**/main.py` |
| `react` | the .NET platform storefront | frontend | `frontend/**`, `**/frontend/**` |

**Profiles compose** — `react` is backend-agnostic, so stack it onto any backend:

```
okl scaffold --profile dotnet --profile react        # .NET + React storefront
okl scaffold --profile python-rag --profile react    # FastAPI backend + React SPA
okl scaffold --profile geospatial                     # rslearn/OlmoEarth pipeline
```

Each profile also writes a `_PROFILE_<name>.md` into `.claude/rules/` documenting what it installed.
Profile rules are the *static* half; the *cross-repo* half (defects, gates, retractions that move
between repos) lives in okl and surfaces via `okl check`.

## Architecture review (opt-in)

`ci/review-agent.sh` runs `.claude/agents/architecture-reviewer.md` over a PR diff and
fails on must-fix findings. **Off unless the `REVIEW_CMD` repository variable is set** to
a CLI that reads a prompt on stdin — `claude -p` (uses your existing Claude Code login,
no separate API key), `ollama run <model>` (local, free), or any other. Unset, it prints
one line and passes. It is the only gate in this kit that calls a model.
