---
name: reference-reproducing-receipts
description: How to re-run an old commit's briefing or the anatomy story in scratch without side effects, to check a delta between two size receipts
metadata:
  type: reference
---

- **An old commit's briefing:** `git archive <sha> src seed | tar -x -C <scratch>/old`. The bundled packs live in the repo-root `seed/`, so `src` alone fails `okl seed --all` with exit 2. Then run `python3 -m okl` with an ABSOLUTE `PYTHONPATH=<scratch>/old/src` and `HOME` set to a temp dir. A relative PYTHONPATH under another cwd silently runs the editable install from the main checkout. On 2026-11-01 that first returned today's 6,316 characters for fd96d79 instead of its receipt's 5,572.
- **Splitting marks from the rest:** call `Client().check()` in-process, then render with `core.render_check_for_agent`. Render it once as is, and once with `proof`, `drift`, `unchecked` and `drifted` popped. This is the same split that evals/briefing_marks_size.py makes.
- **The anatomy sheet's terminal story:** `docs/overview/anatomy-story.sh` calls `okl` from PATH, which is the pinned release. To test the worktree's code, put a shim `okl` (`PYTHONPATH=<wt>/src exec python3 -m okl "$@"`) first on PATH and point HOME and TMPDIR at the scratchpad.
- Never run evals/briefing_size.py or briefing_marks_size.py while reviewing. Both write a receipt into evals/results.

**How to apply:** when a CHANGELOG or REPORT gives a cause for a size change, reproduce both ends and split the delta. Related: [[review-findings-log]].
