# Method kit — what's portable, what you fill

`okl scaffold` stamps this tree into a repo. Everything here is **portable skeleton** — it works in
any language/stack. The parts you complete per repo are marked inline with `<<FILL: ...>>`.

## What gets installed where

| Template (in package) | Installed to | Portable? |
|---|---|---|
| `root/CLAUDE.md` | `CLAUDE.md` | skeleton + FILL slots for stack rules |
| `root/METHOD.md` | `METHOD.md` | fully portable (the seven earned rules) |
| `claude/skills/encoding-loop/` | `.claude/skills/encoding-loop/` | fully portable |
| `claude/agents/architecture-reviewer.md` | `.claude/agents/` | skeleton + FILL for stack checks |
| `claude/commands/feature-spec.md`, `check-rules.md` | `.claude/commands/` | portable |
| `claude/rules/example-area.md` | `.claude/rules/` | template — copy per area, set `paths:` |
| `gates/*.sh` | `gates/` | fully portable (retractions/tombstones/orphans/canon-size) |
| `registries/*` | `registries/` | portable format; FILL entries as earned |
| `evals/*` | `evals/` | portable harness; FILL `evaluate_one()` + `cases.jsonl` |
| `ci/method-gates.yml` | `.github/workflows/` | portable |
| `hooks/*` | `.claude/hooks/` (+ plugin) | portable (fail-closed pre-task check) |
| `plugin/plugin.json` | repo root (if `--plugin`) | portable — makes the whole thing a Claude Code plugin |

## The portable / stack-specific boundary (the load-bearing decision)

- **Portable (ships as-is):** the encoding loop, the six surfaces, the seven earned rules, the
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
