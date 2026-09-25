---
name: review-findings-log
description: Recurring architecture-review finding classes in okl, with counts, to decide when to promote one to a mechanical gate
metadata:
  type: project
---

Tally of finding classes seen in okl reviews. At 3 occurrences, propose a gate via encoding-loop.

- **_Backend Protocol method added without a behavioural clause in its docstring** — 1 (PR #35, `edges()`, 2026-09-24). Related record: "A port is defined by behaviour, not by its signatures".
- **Old and new computation of one metric both served (two sources of truth)** — 1 (PR #35: `recurrence_after_arming` SQL kept beside `core.recurrence_report`).
- **Postgres-backend change reaches CI untested** — 1 (PR #35). CI has no Postgres service; `test_postgres_backend_conformance` is skipped unless OKL_TEST_POSTGRES_URL is set.

**Why:** the agent brief asks to promote a finding class to a gate at its third sighting.
**How to apply:** bump the count when a class recurs; at 3, recommend a gate (e.g. a test that every _Backend method is named in the Protocol docstring).
