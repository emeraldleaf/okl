# The Method — portable engineering discipline (the encoding loop)

> This is the method in its entirety, distilled from three repositories that run it across three
> different stacks: **the .NET platform** (.NET microservices), **the geospatial pipeline** (geospatial /
> rslearn / OlmoEarth), and **the RAG service** (Python / FastAPI / RAG). A rule is in this file — the
> *portable* skeleton — only if it showed up in more than one of them independently. Stack-specific
> rules live in `.claude/rules/*.md` and the `<<FILL>>` slots, not here.

## The core (the whole method in four sentences)

1. **AI-assisted work fails by producing output that is fast, fluent, plausible, and wrong.** Every
   rule merely *documented* drifts; every rule *mechanized* holds. So the method is not exhortation —
   it is surfaces that make the right thing automatic and the wrong thing fail loudly.
2. **The encoding loop:** a trigger (planning, a bug, a review finding, an audit, an incident)
   surfaces a rule. The response is always *pick the smallest sufficient surface → encode it →
   promote it down the spectrum (toward mechanical) only as it earns its keep.* It is a ratchet: it
   does not slip back.
3. **Six surfaces, softest→strongest:** (1) deep reference `docs/`, (2) always-on canon `CLAUDE.md`
   + `.claude/rules/`, (3) procedure rituals `.claude/skills/` + commands, (4) PR-review automation
   `.coderabbit.yaml` + `architecture-reviewer`, (5) mechanical gates CI/tests/hooks, (6) the
   cross-repo org knowledge layer (`okl`). 1–2 are Tier 1, 3–4 Tier 2, 5 Tier 3; 6 spans repos.
4. **A surface nobody runs is documentation, not enforcement.** If a rule is not read or executed on
   the path where it matters, it will drift — so the method's own defects are dated, receipted, and
   registered, and the gates are verified by making them *fail* on real drift before trusting them.

## The seven portable rules (each earned in ≥2 of the three repos)

1. **Don't ask a model to infer what you can look up.** Assertions written from memory (class paths,
   entity identities, config validity) are the single most common defect class across all three
   repos. Every such assertion earns a mechanical `validate` step. *Let the model choose the
   constraint; make code satisfy it.*
2. **A signal that cannot report its own failure is not a signal.** An exit code of 0 with zero
   outputs; a judge that averages only the runs that didn't crash; a "PASS" with no fixture behind
   it. Every gate and every metric must be able to say when it is unreliable, and say it first.
3. **Verify the layer before you build on it.** Confirm the thing you depend on actually works —
   with a real, non-trivial input — before you stack more on top. (A graph planned on a 0%-populated
   entity layer; a model trained on a 0-file materialized dataset.)
4. **Fixtures you invented cannot falsify assumptions you hold.** Test against real data sampled from
   the actual corpus/inputs, not fixtures written by the same person who wrote the code under test.
   The adversarial audit (`/paper-audit`) exists to attack your own confident claims.
5. **Report the result that came out** — especially when it disproves your hypothesis. When a result
   turns out wrong, *retract it in a registry*, don't quietly delete it. The retraction is a receipt.
6. **Record decisions, including the ones you rejected and why.** "Options considered and rejected"
   is as valuable as what you built. An ADR is append-only: supersede, never edit-to-erase.
7. **Use the instrumentation you already have.** The trace, the metric, the log, the cross-tab —
   build the observability once and then actually read it, instead of debugging by `grep`.

## What is deliberately NOT in this file (stack-specific — goes in FILL slots / rule files)

- Framework rules (VSA vs Clean, Wolverine handler discovery, EF outbox) → the .NET platform's canon.
- Domain rules (spatial cross-validation, class-scheme crosswalks, GDAL temp dirs) → the geospatial repo.
- Pipeline rules (reranker config, Qdrant pre-filter, corpus-aggregate vs ranked retrieval) → the RAG service.

Each of those is *real method* — but it is fill, not skeleton. The kit ships the slots; you drop the
stack rules in per repo (`.claude/rules/<area>.md` with a `paths:` glob), and `okl record --scope repo`
them so they are enforced without polluting another repo's `okl check`.

## Sources

Ported verbatim from the three repositories' own method documents:
`the geospatial pipeline/docs/method.md`; the .NET platform `CLAUDE.md` + `CONTEXT.md` + `.github/AI_WORKFLOW.md`;
the RAG service `docs/agent-contract.md` + `docs/findings-log.md`. Current-tool practices (Claude Code
plugins, subagent memory frontmatter, `.claude/rules` path-scoping, hook exit-code-2 blocking) verified
against the official Claude Code docs.
