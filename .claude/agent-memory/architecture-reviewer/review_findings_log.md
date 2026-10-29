---
name: review-findings-log
description: Recurring architecture-review finding classes in okl, with counts, to decide when to promote one to a mechanical gate
metadata:
  type: project
---

Tally of finding classes seen in okl reviews. At 3 occurrences, propose a gate via encoding-loop.

- **_Backend Protocol method added without a behavioural clause in its docstring** — 1 (PR #35, `edges()`, 2026-09-24). Related record: "A port is defined by behaviour, not by its signatures".
- **Old and new computation of one metric both served (two sources of truth)** — 1 (PR #35: `recurrence_after_arming` SQL kept beside `core.recurrence_report`).
- **Postgres-backend change reaches CI untested** — 2 (PR #35; PR #300 fix commit 3fc6c65 added `_PostgresBackend.has_embeddings`, 2026-10-29). CI has no Postgres service; `test_postgres_backend_conformance` is skipped unless OKL_TEST_POSTGRES_URL is set. One more sighting: propose a Postgres service container in CI.
- **Probe-by-exclusive-lock races the real holder** — 1 (PR #300 warm.py: start()/revive() take the server's flock for a moment; a server starting in that instant exits 0 silently).
- **Figure cited to a receipt that does not contain it** — 1 (PR #300, 2026-10-28: REPORT §4z "95 ms a prompt against 174" cites the int8 bench receipt, which says 170.7 ms). ci/check-diagram-figures.sh only covers diagrams, not REPORT/docs prose. A gate candidate: for each "N ms/N%" next to a backticked receipt name, grep that receipt for N.
- **Receipt code stamp unreachable after a rebase** — 1 (PR #300: 815a148, ada6f2a, c1cba7f, c1f340b). Main's late-Oct receipts were 44/44 reachable from main. Gate candidate: every `code <sha>` in evals/results/*.txt is an ancestor of HEAD.
- **New package module outside the import-linter layers** — 1 (PR #300: okl.warm imported by core, unlisted; contract comment says unlisted modules import nothing from okl). Gate candidate: a test that every src/okl/*.py importing `from .` is listed in a layer.
- **Constant hand-transcribed from a receipt with no test (assert-from-memory)** — 1 (PR #300 warm.LINE; decide.py's CALIBRATED_LINE comment quotes 2.0017172944, the receipt says ...2954).
- **Control flow keyed on a substring of a human-readable error message** — 1 (PR #300 client.py: auto-start on "not running" in warm_unavailable).
- **Cherry-picked change citing evidence that lives only in another open PR** — 1 (PR #300 preflight.py cites §4aa / ab-20261029-0318.json from #303).
- **Judge boolean contradicts the judge's own reason, counted as scored** — 1 in my reviews, 3 in the repo: §4j (plan scored clean, fixed by #164), §4r receipt ab-20261023-1303 (2 rows, never corrected), PR #303 §4aa (2 full-arm rows, 2026-10-28). Gate proposed on #303: JUDGE_PROMPT puts "reason" before the booleans, plus a test over committed receipts requiring every contradictory row to sit in a named corrections list with its REPORT section. GATED in #303 fix 1aa2618: tests/test_docs.py CONTRADICTED + NEGATED regex (heuristic; JUDGE_PROMPT order left for its own issue).
- **Eval harness run from a worktree executes the editable install (main checkout), not the worktree** — 1 (PR #303: `python -m okl` from cwd=REPO and `from okl.client import Client` resolve /Users/joshuadell/Dev/okl/src via a .pth; tree_state() fingerprints the worktree that did not render). GUARDED in 1aa2618: code_outside_checkout()/startup_refusal() exit 7 (checks cwd=REPO only; a relative PYTHONPATH still leaves the generator's shim in its temp cwd on the editable install).
- **Ablation arm removes one lesson but leaves a sibling carrying the same fix in full** — 1 (PR #303 ci_linter: d_unpinned_linter "pin the exact tool version" stays in full in the line arm).
- **Docs sentence still says "not yet measured" after the measurement lands** — 1 (PR #303: docs/RETRIEVAL.md:72-73).

**Why:** the agent brief asks to promote a finding class to a gate at its third sighting.
**How to apply:** bump the count when a class recurs; at 3, recommend a gate (e.g. a test that every _Backend method is named in the Protocol docstring).
