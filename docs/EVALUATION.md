# How okl is evaluated

Part of okl's documentation; the [README](../README.md) is the short version. This page is the
standard every evaluation of okl follows: what each claim okl makes rests on, how it is measured,
what counts as ground truth, where it runs, and where it stands today. The method and every
result in full are in [evals/REPORT.md](../evals/REPORT.md); each figure names its receipt in
[evals/results/](../evals/results/).

Written 2026-11-07, after two lessons that applied to real work reached the agent through none
of okl's retrieval arms that ran, and none of okl's own evaluations could have shown it
([REPORT §4ak](../evals/REPORT.md)). The rules below are the methods of the studies okl's docs
already cite, and of the evaluation literature behind them, applied to okl. Each names its
sources; arXiv ids are given where a paper has one.

## The claims, and what each must be measured against

okl's claim ([THESIS](THESIS.md)) breaks into five parts. Each needs its own evaluation, and none
can borrow another's: a lesson can reach the agent and be ignored, and an agent can avoid a
mistake no lesson named.

| claim | the question | ground truth | status today |
|---|---|---|---|
| **The software does what its docs say** | Do the commands, hooks and gates behave as documented, on real inputs? | Executable: tests on recorded inputs, and an end-to-end run on a fresh install | The suite runs in CI on five Python versions. Some fixtures were written by hand, the end-to-end run is manual, and part of the guard check is not yet registered |
| **The right lesson reaches the agent** | Of the lessons a piece of real work needed, how many reached the agent before the code was written, and through which channel? | Every needed lesson labelled per task before any arm runs, plus known-item cases from real misses | Pooled figures only (§4x, §4y), which are upper bounds. The real misses on file reached: 0 of 2 (§4ak) |
| **The agent then complies** | Given the lesson, does the agent write code that passes the check the eventual fix added, and does a briefing ever turn a pass into a fail? | Executable: a hidden test taken from the real fix | Only on eight authored bait tasks (§5, finding 7), whose prompts name the lesson's subject |
| **What it watches stays true** | When code a lesson governs changes, is the lesson flagged, and only then? | Executable: deliberate breaks and a replay of history (§4ae, §4af, §4ah) | Measured, with judge-confirmed breaks |
| **It keeps learning, without inventing** | Are real findings captured as lessons, and how often is a lesson recorded for a failure that never happened? | Review findings on merged PRs (`okl intake`), and sessions with nothing to learn | Not measured (#251) |

## The rules every evaluation follows

**Tasks**

1. **Tasks come from real work, and do not state the answer.** A task is a real prompt, issue or
   pull request. That its lesson can be inferred, as "add a webhook endpoint" implies signature
   verification, does not exclude it: that is ordinary work. A leak check rejects any task whose
   prompt or repository states the answer. Real-log tasks with the target
   stripped from the prompt (TellOnce, arXiv 2606.13174v2), a validator that rejects revealing
   traps (DreamBench-SWE, 2608.20664), and the rule left out of the prompt in the "native" arm
   (2607.26819) all do this. okl's eight authored tasks name their lesson's subject; they stay,
   labelled as bait, and are no evidence for this claim.
2. **The past is frozen and out of reach.** A task uses only what existed then: the prompt as
   typed, the issue, the author's own words at the commit, the repository rebuilt from the base
   commit's ancestry with later history removed, and the store without lessons recorded since. A
   run that looks the answer up is voided (2607.26819's trajectory audit; DreamBench-SWE's
   container isolation and canary; SWE-bench issue #465).
3. **Balanced, with work that needs nothing.** Every set includes tasks no lesson applies to, so a
   briefing that names too much, and a loop that records a lesson for nothing, are measured too
   (Anthropic, *Demystifying evals for AI agents*, 2026; Phantom Guardrails' pristine pool,
   2607.13083).
4. **Synthetic data is measured against a human anchor, and quoted only relatively.** Generated
   tasks and model labels shift absolute scores and favour systems built on the same model; they
   can rank arms, not report recall (Rahmani et al., CIKM 2025, 2506.10301).

**Ground truth**

5. **Every needed lesson is labelled before any arm runs.** The gold set for a task is every
   lesson it needs, not those an arm happened to return (HippoRAG 2, 2502.14802; Anthropic's
   golden chunks in *Contextual Retrieval*). Pooled judging, which labels only what some system
   returned, overestimates recall, and its bias runs toward items that share the query's words
   (Zobel, SIGIR 1998; Buckley, Dimmick, Soboroff and Voorhees, *Information Retrieval* 2007): the
   class §4ak found. okl's store holds a few hundred lessons, so every lesson can be judged for
   every task. A pooled figure is reported as recall over the pool, an upper bound.
6. **Executable oracles first.** Where a check can decide (a test the fix added, a planted break,
   a byte-exact oracle), it decides (SWE-bench, Jimenez et al., ICLR 2024; DreamBench-SWE; Phantom
   Guardrails).
7. **A model judge counts only once validated.** It is measured against human labels on a sized
   random sample, with agreement (κ) and per-class error committed as a receipt (ContextCov,
   2603.00822; Thomas et al., SIGIR 2024; Zheng et al., NeurIPS 2023). It is blind to the arm,
   cites its evidence, answers "unsure", counts unsure against the claim, and reads pairs in both
   orders (2607.26819; RAG vs GraphRAG, 2502.11371). The audit is stratified by how many words the
   task and lesson share, since judges over-label items that repeat the query (Alaofi et al.,
   SIGIR-AP 2024). It is never the generator, nor any model an arm uses.

**Arms**

8. **A floor and a ceiling beside each treatment.** No briefing; the treatment; and every lesson,
   or the needed lesson quoted. The gap between floor and ceiling is the headroom. The gap between
   treatment and ceiling cannot by itself tell "did not reach the agent" from "reached it and was
   not followed", so each task also records whether the lesson reached the agent, and outcomes are
   compared by that as well as against the ceiling (TellOnce's no, all and relevant rules; 2607.26819's native and quote arms;
   MemoryAgentBench's zero-shot floor, 2507.05257).
9. **Harm is counted.** A task the agent passes without a briefing and fails with one is reported
   on its own (Memory Transfer Learning's negative transfer, 2604.14004; DreamBench-SWE's
   harmful-memory rate). So are cost and briefing size: context files can add cost without adding
   success (Gloaguen et al., *Evaluating AGENTS.md*, 2026).

**Statistics**

10. **The task is the unit.** Seeds are replicates within it. Arms are compared on the same tasks
    with paired exact tests, corrected for the number of contrasts (Holm); a zero cell gets an
    exact or Wilson bound; results are reported per agent and model, never pooled across them
    (DreamBench-SWE; 2607.26819; Phantom Guardrails; Miller, *Adding error bars to evals*,
    2411.00640).
11. **Pre-registered, split, and replayed.** The tasks, oracles, predictions and what follows from
    each outcome are written before a run. Anything tuned (a weight, a floor, a cutoff) is tuned
    on one split and reported on another, with the per-task best as the ceiling (Bruch et al., ACM
    TOIS 2023, 2210.11934). Frozen records are committed so the analysis replays exactly.

**Retrieval, in particular**

12. **The headline is the failure rate at several cutoffs.** The share of tasks whose needed lesson
    was not reached, at the briefing's sizes, per channel, with a split of vague tasks
    (Anthropic, *Contextual Retrieval*, 2024).
13. **"Every time" is stated as a guarantee with its price.** Split conformal calibration sets the
    cutoff from real tasks so that the needed lesson is reached with probability at least 1 − α,
    whatever the retriever (Lei et al., JASA 2018, 1604.04173; Angelopoulos and Bates, 2107.07511;
    TRAQ, 2307.04642). Calibrating on each task's worst-ranked needed lesson covers all of them;
    conformal risk control bounds the share missed (2208.02814). The calibration runs on the set
    actually delivered, after every filter: a needed lesson the retriever never returns, or a
    filter removes, has no rank and counts as beyond every cutoff. When that leaves no finite cutoff
    meeting the target, the report says so and gives the reach at the largest cutoff instead of a
    guarantee. It holds only while new tasks
    resemble the calibration tasks, so it is recalibrated when the store or retriever changes. At
    α = 0.1 it needs at least 9 calibration tasks to exist and about 100 to be tight within five
    points (Angelopoulos and Bates, Table 1). Where needed lessons rank deep, as in §4ak, the
    honest cutoff is deep: the guarantee makes the briefing's cost visible instead of hiding a miss.

**Process**

14. **Every miss becomes a permanent case.** A lesson that applied and did not reach the agent is
    added to [evals/missed_lessons.jsonl](../evals/missed_lessons.jsonl), with text from the time
    only, and stays. It must fail on the version that missed it. Nothing is tuned on the cases
    that grade it: a miss is never fixed by copying its words into the lesson (Defects4J, ISSTA
    2014; SWE-bench's fail-to-pass tests; Anthropic, *Demystifying evals*).
15. **Each runs where it can, and a claim follows its evaluation.** Deterministic evaluations run in
    CI on every pull request; model-judged ones run on a schedule and before each release, and a
    release waits for them. Every public figure links its receipt. A claim with no passing
    evaluation at the release commit is marked unmeasured or removed.
16. **Tests use recorded inputs.** Fixtures are recorded from the systems they stand for, never
    written from what the author expects: a fixture written by the code's author shares its
    assumptions (the store's `qz_fixtures` lesson, and the bug it let through in #388).

## Retrieval: the channels, and what each can see

A lesson can reach the agent through five channels, and §4ak shows they are not interchangeable:
two lessons relevant to what the code did, not to what the task was about, were not even full-text
candidates for the prompt, and every rank recorded for a text written before the code ran from 54th
to 299th, of 311 to 364 candidates, with or without the semantic arms. Only a
channel that reads the code can see that class. Reach is reported per channel, and for the union
before the code merged.

| channel | what it searches | built |
|---|---|---|
| prompt | the prompt, with the reply before it for a short one | yes (the reply: not yet) |
| plan | the agent's statement of the task before it writes code | the agent can ask (`okl_check`); nothing yet makes it |
| file | the lessons governing a file as it is read | yes, `okl check --path` (§4aj) |
| change | the code as it is written | no |
| pull request | every lesson against the diff, judged one by one | no: measured next |

## Where each evaluation runs

| evaluation | instrument | runs |
|---|---|---|
| the test suite, lint, types, import contracts | `pytest`, `ruff`, `mypy`, `lint-imports` | CI, every pull request |
| guards held by tests | `ci/check-guard-mutations.py` | CI, every pull request |
| known-item replay of real misses | `evals/missed_lessons.py` | locally; in CI once the store's lessons are committed |
| drift on history and on planted breaks | `evals/drift_replay.py`, `evals/drift_mutate.py` | before a release |
| briefing reach and size on real prompts | `evals/bench/real_prompts.py` (pooled: upper bound) | before a release |
| outcome on bait tasks | `evals/ab_harness.py` (labelled bait) | before a release |
| still to build | listed below | — |

## What is being built, in order

1. **The end-to-end run in CI, and every guard registered.** A fresh install on a fixture
   monorepo, the hooks fired as the agent's harness fires them, the loop from record to re-verify,
   a branch's stamp kept from another, and the MCP server over stdio.
2. **A real-work set with complete labels.** Tasks mined from this repository's merged pull
   requests and sessions (each resolved review finding, the diff it was found on, and the text
   written before the code), leak-checked, with tasks that need nothing. Every lesson that existed
   at the time is labelled against each task. The judge is validated on a human-labelled sample
   first. Reach is then reported per channel, as failure rates at several cutoffs, with intervals.
3. **The review of every lesson against a pull request's diff,** measured on that set and on the
   ledger before it ships: how many needed lessons it names, and how many it names wrongly.
4. **A calibrated cutoff.** Conformal calibration on the real-work set, with the briefing size it
   costs reported beside the guarantee.
5. **Outcome replay.** Real tasks at their base commit, with floor, treatment and ceiling arms,
   graded by the test the real fix added; compliance, harm, success and cost reported together.
6. **Capture without invention** (#251): congruent, harmless and pristine sessions, and how often
   each records a lesson.

## Related

[evals/REPORT.md](../evals/REPORT.md) holds the method, every measurement and its threats to
validity; [Related work](RELATED-WORK.md) covers the research okl's design draws on;
[Verification](VERIFICATION.md) covers how okl verifies the lessons themselves.
