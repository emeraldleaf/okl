# How okl is evaluated

Part of okl's documentation; the [README](../README.md) is the short version. This page is the
standard every evaluation of okl follows: what each claim okl makes rests on, how it is measured,
what counts as ground truth, where it runs, and where it stands today. The method and every
result in full are in [evals/REPORT.md](../evals/REPORT.md); each figure names its receipt in
[evals/results/](../evals/results/).

Written 2026-11-07, after two lessons that applied to real work reached the agent through none
of okl's retrieval arms, and none of okl's own evaluations could have shown it
([REPORT §4ak](../evals/REPORT.md)). The standard below is what would have.

## The claims, and what each must be measured against

okl's claim ([THESIS](THESIS.md)) breaks into five parts. Each needs its own evaluation, and none
can borrow another's: a lesson can reach the agent and be ignored, and an agent can avoid a
mistake no lesson named.

| claim | the question | ground truth | status today |
|---|---|---|---|
| **The software does what its docs say** | Do the commands, hooks and gates behave as documented, on real inputs? | Executable: tests, and an end-to-end run on a fresh install | The suite runs in CI on five Python versions. Some fixtures were written by hand, the end-to-end run is manual, and part of the guard check is not yet registered |
| **The right lesson reaches the agent** | Of the lessons that applied to a piece of real work, how many reached the agent before the code was written, and through which channel? | Every lesson judged against each case, never only those an arm returned, plus known-item cases from real misses | Pooled figures only (§4x, §4y), which are upper bounds. The two real misses reached on file: 0 of 2 (§4ak) |
| **The agent then avoids the mistake** | Given the briefing, does the agent write code that passes the check the eventual fix added? | Executable: a hidden test taken from the real fix | Measured only on eight authored bait tasks (§5, finding 7), not on real tasks |
| **What it watches stays true** | When code a lesson governs changes, is the lesson flagged, and only then? | Executable: deliberate breaks and a replay of history (§4ae, §4af, §4ah) | Measured |
| **It keeps learning, without inventing** | Are real findings captured as lessons, and are lessons invented for failures that never happened? | Review findings on merged PRs (`okl intake`), and a control with nothing to learn | Not measured (#251) |

## The rules every evaluation follows

1. **Ground truth comes from outside okl.** A lesson is judged relevant without asking any of
   okl's arms. Pooled judging, which labels only what some system returned, overestimates
   recall, and its bias runs toward items that share words with the query (Zobel, SIGIR 1998;
   Buckley, Dimmick, Soboroff and Voorhees, *Information Retrieval* 2007; Voorhees, Craswell and
   Lin, SIGIR 2022). That is exactly the class §4ak found. okl's collection is small, a few hundred
   lessons, so every lesson can be judged for every case. Where a pool is used, its figure is
   reported as recall over the pooled set: an upper bound, never recall.
2. **Real work first, and failures before successes.** Cases come from real sessions and real
   pull requests, starting from real failures. Authored tasks are kept, and labelled as bait
   (Anthropic, *Demystifying evals for AI agents*, 2026; Just, Jalali and Ernst, *Defects4J*, ISSTA
   2014). The sets are balanced: they include work no lesson applies to, so a briefing that names
   too much is measured too.
3. **The past is frozen.** A case uses only what existed at the time: the prompt as typed, the
   issue, the agent's own words at the commit, the repository at its base commit with later
   history removed, and the store without lessons recorded afterwards. A query reworded by
   someone who knows the miss finds it; a fix left reachable in the history leaks the answer
   (SWE-bench issue #465; Aleithan et al., *SWE-Bench+*, 2024).
4. **Outcomes, not only proxies.** Retrieval figures correlate weakly with what the agent then
   does (Salemi and Zamani, *eRAG*, 2024), and context files can add cost without adding success
   (Gloaguen et al., *Evaluating AGENTS.md*, 2026). The claim that the agent avoids the mistake is
   measured on real tasks at their base commit, okl on and off, graded by a check the agent never
   sees, as SWE-bench grades (Jimenez et al., ICLR 2024). Success and cost are reported together.
5. **Every judge is validated before its numbers count.** A model judge is checked against a
   human-labelled audit set, with agreement and per-class error reported as a receipt, and
   checked again whenever its model or prompt changes (Thomas et al., SIGIR 2024; Zheng et al.,
   NeurIPS 2023; Saad-Falcon et al., *ARES*, NAACL 2024). The audit is stratified by how many words
   the work and the lesson share, since judges over-label items that repeat the query's words
   (Alaofi et al., SIGIR-AP 2024). The judge is never the generator, nor any model an arm uses,
   and it can answer "unsure".
6. **Pre-registered, held out, with intervals.** Each measurement is written down before it runs:
   the prediction, what would falsify it, and what follows from each outcome. Tuning and grading
   use different cases. Arms are compared on the same cases, with paired differences, intervals
   clustered by case, and a noise floor from an arm the change cannot reach (Miller, *Adding error
   bars to evals*, 2024; [REPORT §2b](../evals/REPORT.md)).
7. **Every miss becomes a permanent case.** A lesson that applied and did not reach the agent is
   added to [evals/missed_lessons.jsonl](../evals/missed_lessons.jsonl), with text from the time
   only, and stays there. A case must fail on the version that missed it. Regression cases and
   capability measurements are kept apart, and nothing is tuned only on the cases it is graded by.
8. **Each runs where it can.** Deterministic evaluations run in CI on every pull request. Model-judged
   ones run on a schedule and before each release, and a release waits for them. Every public figure
   links its receipt, and a claim with no passing evaluation at the release commit is marked
   unmeasured or removed.
9. **Tests use real inputs.** Fixtures are recorded from the systems they stand for, never written
   from what the author expects them to say: a fixture written by the code's author shares its
   assumptions (this repository's `qz_fixtures` lesson, and the bug it let through in #388).

## Retrieval: the channels, and what each can see

A lesson can reach the agent through five channels, and §4ak shows they are not interchangeable.
Two lessons relevant to what the code did, not to what the task was about, ranked between 54th and
299th of 364 for every text written before the code, with or without the semantic arms. Only a
channel that reads the code can see that class.

| channel | what it searches | built |
|---|---|---|
| prompt | the prompt, with the reply before it for a short one | yes (the reply: not yet) |
| plan | the agent's statement of the task before it writes code | the agent can ask (`okl_check`); nothing yet makes it |
| file | the lessons governing a file as it is read | yes, `okl check --path` (§4aj) |
| change | the code as it is written | no |
| pull request | every lesson against the diff, judged one by one | no: measured next |

Reach is reported per channel and for the union, and for the union counted before the code merged.

## Where each evaluation runs

| evaluation | instrument | runs |
|---|---|---|
| the test suite, lint, types, import contracts | `pytest`, `ruff`, `mypy`, `lint-imports` | CI, every pull request |
| guards held by tests | `ci/check-guard-mutations.py` | CI, every pull request |
| known-item replay of real misses | `evals/missed_lessons.py` | locally; in CI once the store's lessons are committed |
| drift on history and on planted breaks | `evals/drift_replay.py`, `evals/drift_mutate.py` | before a release |
| briefing reach and size on real prompts | `evals/bench/real_prompts.py` (pooled: upper bound) | before a release |
| outcome on bait tasks | `evals/ab_harness.py` (labelled bait) | before a release |
| still to build | the end-to-end run in CI; a real-work reach set judged in full; the review of every lesson against a diff; outcome replay on real tasks; the capture and fabrication measure | tracked below |

## What is being built, in order

1. **The end-to-end run in CI, and every guard registered.** A fresh install on a fixture
   monorepo, the hooks fired as the agent's harness fires them, the loop from record to re-verify,
   a branch's stamp kept from another, and the MCP server over stdio.
2. **A real-work reach set, judged in full.** Cases from this repository's merged pull requests:
   each resolved review finding, the diff it was found on, and the text written before the code.
   Every lesson that existed at the time is judged against each case. The judge is first validated
   on a human-labelled audit set. Recall is then reported per channel, with intervals.
3. **The review of every lesson against a pull request's diff,** measured on that set and on the
   ledger before it ships: how many applying lessons it names, and how many it names wrongly.
4. **Outcome replay.** Real tasks at their base commit, okl on and off, graded by the test the
   real fix added, with success and cost reported together.
5. **Capture without invention** (#251): how often a session with nothing to learn records a
   lesson anyway.

## Related

[evals/REPORT.md](../evals/REPORT.md) holds the method, every measurement and its threats to
validity; [Related work](RELATED-WORK.md) covers the research okl's design draws on;
[Verification](VERIFICATION.md) covers how okl verifies the lessons themselves.
