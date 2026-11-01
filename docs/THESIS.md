# Thesis

What okl claims to do, how much of it holds today, measured, and how the claim has changed.
The [README](../README.md) carries the claim's first line. This page carries the rest, and okl
keeps it current like anything else a team maintains (#317): it changes when the claim changes,
when a receipt behind the baseline is replaced, or when a pre-registered measurement of the claim
lands. `tests/test_docs.py` holds the README's headline to the claim below.

## The claim

**Keeps your coding agent true to your rules, specs and docs. Keeps them true to the code. Keeps learning as you build.**

Before each task, okl briefs the agent with what applies. When something you maintain falls out
of step with what it describes, okl notices and has the agent bring it back, telling you or
asking first. Each session's lessons are recorded, so the next starts from more. Every claim is
backed by a check you choose, or marked unchecked.

Two rules hold throughout:
- **okl itself makes no model calls in its loop.** It notices mechanically, and the agent in the
  session does the work.
- **Nothing is written to the store without you knowing.**

## What holds today, and what is still direction

| the claim says | today | evidence |
|---|---|---|
| it briefs the agent with what applies | built | 42% → 7% defects reproduced on eight bait tasks, pooled over seven A/B runs ([REPORT](../evals/REPORT.md) §5 finding 7) |
| it notices when something you maintain falls out of step | built for lessons that govern files and carry a check, including docs a lesson names (this README is one); not yet for docs, diagrams, specs, reports or results in general (#317, #314) | 16 of the 155 lessons recorded here were watched at the census below, 12 after #318 moved four whose check CI runs (§4ah); of 52 patches written to break those lessons, a judge confirmed 36 as breaks, and drift caught 14 of them (§4af); after #318, it caught 16 of 24 on the nine it could break, counts only (§4ah) |
| it has the agent bring it back, telling you or asking first | partly: a drifted lesson blocks the push or fails CI, and the briefing marks it STALE; telling or asking for other artifacts is #317 | §4ae, §4af |
| each session's lessons are recorded | built: in Claude Code, the Stop hook asks once a session what was learned | — |
| every claim is backed by a check, or marked unchecked | built: a briefed lesson no observed check backs, and drift has no verdict on, is marked UNCHECKED (#222); 71 of 155 lessons have a check | census and briefing marks below |

## Baseline (2026-10-31)

Each figure names its receipt in `evals/results/`.

| measure | value | receipt |
|---|---|---|
| lessons recorded in this repo: watched by drift / checked only by CI / no check | 16 / 55 / 84 of 155; all 55 CI-left checks pass at f645d81 | `lesson-census-20261031-1409.json` |
| drift's red that was a committed break | 4 of 1,865 events (0.21%) | `drift-replay-20261101-0143.json` (§4ae) |
| judge-confirmed breaks of watched lessons (of 52 patches written to break them) that drift caught | 14 of 36 (38.9%, 95% interval 24.8–55.1%); of the 22 misses, 14 changed a file the lesson does not watch, and 8 passed a check too narrow to see them | `drift-mutate-20261031-1522.json` (§4af) |
| the same after #318, on the nine watched lessons drift can break (of 36 patches written to break them) | 16 of 24, counts only: the judge gave no verdict on 11 of the 54 patches, over the 20% that allows a rate; §4af caught 8 of 22 on the same nine | `drift-mutate-20261101-1935.json` (§4ah) |
| lessons with no check judged stale | 2 of 65 that make a claim about this repo, both confirmed and corrected; the judge let wrong details pass, so this is a count, not a rate | `stale-lessons-20261031-1527.json` (§4ag) |
| briefed lessons marked UNCHECKED, on 13 briefed prompts (eval tasks and probe prompts) | 121 of the 172 the mark could reach (all 172 briefed could); the marks add 3,466 characters to 68,673 (5.0%) | `briefing-marks-size-20261101-1110.txt` (#222) |


## History

- **2026-11-01.** The unchecked mark landed (#316, #222): a briefed lesson that no observed check
  backs is marked UNCHECKED, 121 of 172 on the measured prompts.
- **2026-11-01.** The claim became three sentences. "Keeps learning as you build" joined the two
  directions of drift, because learning is as much the point as keeping things true, at the
  maintainer's direction. The README names drift in the line beneath it.
- **2026-10-31.** The headline was "Verified memory for coding agents, and the loop that keeps
  it true." It changed to the claim above. The scope widened from lessons to everything a team
  maintains, and this page and its baseline were added (#317).
  - **Why:** the census found that drift watched 16 of the 155 lessons, and that the briefing
    marked none of the rest. The drift that mattered, in stale lessons and in docs whose prose had
    fallen behind the code, sat outside what okl watched.

## Still to align

Nothing in okl's own files. Since 0.10.0, PyPI's description, the plugin's and `okl --help` carry
the claim word for word, and the MCP Registry's carries it shortened to fit its 100-character
limit: "Keeps your agent true to your rules. Keeps them true to the code. Keeps learning as you
build." The overview and anatomy sheets in `docs/overview/` and the okl page on emeraldleaf.dev
carry it too.
