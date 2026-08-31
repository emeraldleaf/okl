# {{REPO}} — agent instructions (canon, surface 2)

> New session? Read `.claude/rules/` (loaded by path) and run `/feature-spec` before non-trivial work.
> This file is the **always-on canon**. Keep it lean — target ~60–150 lines. Detail lives in
> `.claude/rules/*.md` (path-scoped), `.claude/skills/` (on-demand), and `docs/` (deep reference).
> CI enforces a size budget (warn 200 / fail 300 lines). This is surface 2 of the encoding loop.

## The method (portable — do not delete)

This repo runs the **encoding loop**: a trigger (planning, a bug, a review finding, an audit)
produces a rule; the response is always **pick the smallest surface → encode it → promote down the
spectrum as it earns its keep**. Five surfaces, softest→strongest (1→5 *is* moving down):

1. Deep reference — `docs/` + diagrams (passive)
2. Always-on canon — this file + `.claude/`
3. Procedure rituals — `.claude/skills/` + `.claude/commands/` (user-invoked)
4. PR-review automation — `.coderabbit.yaml` + `.claude/agents/architecture-reviewer.md`
5. Mechanical gates — CI, tests, hooks (build fails if violated)

**Before starting work, the pre-task hook injects the org's relevant lessons** via `okl check`
(surface 6 — the cross-repo layer). Read them. Retractions, tombstones, and armed gates in that
briefing are binding. If it says a claim is retracted, do not restate it as fact.

**When you learn something worth keeping** ("never write this again" / "always do this when"),
encode it the same session at the smallest sufficient surface, and `okl record` it — `scope=org`
if it is a fact about the world (prior art, an API contract, a data gotcha), `scope=repo` if it is
a quirk of this codebase only. A merged fix without the encoded rule is a half-finished job.

## Always-on rules (keep few; most rules belong in `.claude/rules/` or skills)

- Never commit secrets, `.env` files, or credentials.
- Every non-trivial change starts with `/feature-spec` (value gate + significance check).
- Any spec/plan/scaffold **assertion** ("these paths are correct", "this config is valid") earns a
  mechanical `validate` step before it is trusted — never assert from memory. (SDD's one load-bearing rung.)
- Report the result that came out, especially when it disproves your own hypothesis.
- Verify a gate by making it FAIL on real drift before trusting it to pass.

<!-- <<FILL: STACK-SPECIFIC ALWAYS-ON RULES>>
     Add the handful of rules every session in THIS repo needs (language, framework, house style).
     Keep each to one bolded headline + one paragraph; move the rationale to docs/ or a rule file.
     Delete this comment when filled. Examples of what belongs here vs. a path-scoped rule file:
       - belongs here: "All money math is server-computed, never trusted from the client."
       - belongs in .claude/rules/db.md (paths: **/*.sql): EF/query conventions.
-->

## Build & test

<!-- <<FILL: BUILD/TEST COMMANDS>>  e.g. `make test`, `dotnet build`, `pytest -q`, `npm run ci` -->

## Encoding surfaces in this repo (auto-maintained)

- Registries: `registries/RETRACTIONS.md`, `registries/tombstones.txt`
- Gates: `gates/` (run via `gates/run-gates.sh`; required in CI)
- Evals: `evals/` (golden set from real failures; gates on measured behavior)
- Knowledge layer: `okl check` / `okl record` (see `.okl/config.json`)
