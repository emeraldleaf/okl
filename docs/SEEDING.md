# Seed it, so the very first `check` returns something

Part of okl's documentation; the [README](../README.md) is the short version. Loading rules, ADRs, standards and specs a team already has is [LOAD-YOUR-RULES.md](LOAD-YOUR-RULES.md).

An empty store returns nothing, and says so — a check against an empty store reports
that it proved nothing rather than reporting "no rules apply". Four ways to fill it:

**1. See what ships, then choose.** A bare `okl seed` imports nothing; it lists the
bundled packs with their record counts and subject tags, marking the ones that match
this repo's declared interests:

```bash
okl seed                              # list the packs, import nothing
okl seed rag-defects                  # import one, by name (a path to any pack file works too)
okl seed --all                        # import every pack (explicit on purpose)
```

The packs hold real, dated records from production codebases (a .NET service, a
geospatial ML pipeline, a Python RAG service, a React app), plus `python-canon`: the .NET
packs' engineering rules translated to Python from cited sources (PEPs, the mypy, pytest
and import-linter docs, Google's style guide), with the okl incidents that prompted them. They are org-scoped, so
importing packs for stacks you do not use fills every briefing here with noise about
frameworks you will never touch — which is why `--all` is opt-in rather than default.

**2. Load the rules you already wrote.** `/seed-from-docs` has your agent read your rules
files (`CLAUDE.md`, `AGENTS.md`, `.cursor/rules`), ADRs, standards and specs, keep the
standing rules and drop the work items, and propose records that cite the line each came
from. It writes a reviewable file and imports nothing; review it, then `okl seed <file>`.
It comes with the Claude Code plugin or `okl scaffold .`; with another agent, give it the
prompt itself, `src/okl/scaffold/claude/commands/seed-from-docs.md`. Three things to know:

- Imported records are briefed, not watched. Give the ones that govern specific code
  `files` in the lessons file, run `okl seed` again, then prove them with `okl verify`.
- Leave superseded ADRs out, or retire an imported one with `okl retire <id> --by <new-id>`.
- Running `okl seed` on the edited file again updates the same records, but it keeps a
  record you deleted from the file, and it overwrites corrections made with `okl update`.
  Make corrections in the file.

The whole walk-through, with ADR status, teams, and keeping docs and comments current, is
[docs/LOAD-YOUR-RULES.md](LOAD-YOUR-RULES.md).

**3. Generate records from this codebase.** If you use a coding agent, the scaffold
stamps a `/seed-from-codebase` command that has the agent read your repo — the guard
rails already in the code, what CI enforces, the fix commits, the existing canon — and
propose records with a `file:line` citation each. Everything it proposes is repo-scoped
and unverified by design; it writes a reviewable file and imports nothing, because a
plausible rule no file supports is worse than an empty store.

**4. `okl bootstrap`** greps git history and file names for candidates. It is the weakest
of these and comes up empty on young repos; prefer options 2 and 3 when an agent is available.

Whichever you use, review before importing. Choosing a record's scope is the curation
step that keeps a shared layer from filling with one project's noise.
