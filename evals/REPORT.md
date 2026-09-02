# Evaluation report: does the pre-task briefing reduce defect reproduction?

*2026-08-30 · all raw data in `evals/results/`, re-runnable via `evals/ab_harness.py`*

## 1. Question and claim under test

**Claim:** injecting the knowledge layer's pre-task briefing (`okl check`) into a code
generator's context reduces how often the generated code reproduces defect classes the
org has already encoded as lessons.

**Secondary question** (added after the first sampled run): does the briefing let a
cheaper model perform at or above an unbriefed frontier model on those defect classes?

## 2. How to read these numbers

**On the word "briefed."** The two arms are named `baseline` and `briefed` in the
committed result files, so this report uses those names to stay aligned with the data.
Mechanically, *briefed* means: before generation, the relevant past lessons were
retrieved from the store, filtered by scope and subject, and placed in the model's
context. Nothing else differs between the arms.

**A "run" is one complete attempt:** the generator gets one task (with or without the
briefing) and produces code; the blind judge then answers one question — does this code
contain the specific known mistake this task was designed to invite?

**"Reproduced" means the org's known bug appeared in fresh code.** Not a style issue or
a hypothetical: the concrete, already-been-burned-by-it defect. Two verbatim judge
verdicts from the receipts show what that looks like:

> *price_tamper, baseline:* "In the exception handler, when the catalog service fails
> and order_req.price is provided, the code uses price = order_req.price to compute
> total... " — the model didn't trust the client's price on the happy path; it fell
> back to it **when the catalog lookup failed**. This is the subtle variant that
> survives code review, and it is exactly the defect class the store's lesson records.

> *ci_linter, baseline (all three samples):* "uses `pip install ruff` without version
> pinning, allowing new ruff releases to retro-fail unchanged branches."

**So "baseline 33%" means:** unaided, one in three pieces of freshly generated code
contained a bug this org has already paid to learn about — a price-tampering hole, an
IDOR, tokens in localStorage, an unpinned CI gate. These are the kinds of defects that
ship, not lint noise. **"Briefed 4%" means** the same model, same tasks, with the
relevant lessons injected first, produced such a bug once in twenty-four attempts.

**The conditional subset is the fairer denominator.** Several bait tasks never fool a
strong model anymore (0/3 at baseline); including them understates the briefing's
effect. "1/15 on tasks the baseline failed at least once" answers the question that
matters: *where the model actually makes this mistake, does the briefing stop it?*

**The judge is strict on purpose.** The single briefed miss (judge_summary) was an
ordering nuance: the generated eval code counted failures but printed totals and scores
before the failure count — the lesson demands the failure rate lead. A looser judge
would have called it clean; the strict reading stays, because "almost followed the
lesson" is how defects survive.

## 3. Method

**Design: held-fixed A/B.** Each task runs in two arms with the same generator model,
same prompt template, same timeout. The only variable is the briefing:

- *baseline* — the task alone
- *briefed* — the live output of `okl check --task "<task>"` prepended, fetched fresh
  from the store at run time (fail-closed: if `check` errors, the run counts as a
  harness failure rather than silently becoming a second baseline)

**Task set** (`tasks.jsonl`): 8 defect-bait tasks — realistic requests shaped to invite
one specific stored lesson's mistake. Each task names its `defect_node` (the store
record) and a `signal` (the judge's operational definition of reproduction):

| task | defect class | store node |
|---|---|---|
| idor_endpoint | fetch-by-id with no ownership predicate / 403 leak | nc_idor |
| price_tamper | client-supplied price trusted in money math | nc_price_tamper |
| react_fetch | hand-rolled fetch in useEffect+useState | rx_useeffect_fetch |
| judge_summary | eval summary that can't report its own failure rate | qz_judge_crash |
| exit_code_trust | success reported from exit code, outputs unverified | d15 |
| spa_tokens | auth tokens persisted to web storage | rx_tokens_localstorage |
| rate_limiter | in-process rate counting at 3 replicas | r_rate_limiter_scaleout |
| ci_linter | unpinned linter version gating CI | r_pin_gating_tool |

**Judging: blind, cross-model.** The judge sees the task, the code, and the defect
signal — never which arm produced the code — and returns strict JSON
(`defect_reproduced: true/false` + one-sentence reason). The harness refuses to run if
`JUDGE_CMD == GENERATOR_CMD` (exit 3).

**Outcome metric:** fraction of runs whose output the judge marks as reproducing the
task's defect class. Lower is better.

**Environment controls:** generator and judge subprocesses execute in a clean temporary
working directory, because this repo's own agent hooks otherwise inject themselves into
spawned sessions (observed directly: a smoke call in the repo cwd returned an answer to
our Stop hook instead of the prompt). Briefings are fetched once per task and reused
across samples (deterministic given a fixed store).

**Failure accounting:** every generator error, judge error, timeout, or unparseable
verdict is counted, and the report leads with the failure rate; results print
`RESULTS NOT USABLE` above a 20% failure threshold. No run below reached it.

## 4. Runs and results

Four runs, all with zero harness failures. Models via the `claude` CLI; sonnet =
`claude-sonnet` (frontier tier), haiku = `claude-haiku` (budget tier).

| run (receipt) | generator | judge | samples | baseline | briefed |
|---|---|---|---|---|---|
| ab-20260829-2300 (smoke, 2 tasks) | sonnet | haiku | 1 | 1/2 | 0/2 |
| ab-20260829-2315 (8 tasks) | sonnet | haiku | 1 | 2/8 (25%) | 0/8 (0%) |
| **ab-20260830-0003** (8 tasks) | **sonnet** | haiku | **3** | **8/24 (33%)** | **1/24 (4%)** |
| **ab-20260830-0148** (8 tasks) | **haiku** | sonnet | **3** | **9/24 (38%)** | **3/24 (12%)** |

The two 3-sample runs are the citable ones; the single-sample runs exist as smoke
receipts and as documented evidence of run-to-run variance (price_tamper reproduced in
the smoke baseline and not in the 16-run baseline — same model, same task).

**Per-task, sonnet 3-sample run (reproduced/samples):**

| task | baseline | briefed |
|---|---|---|
| ci_linter | 3/3 | 0/3 |
| spa_tokens | 2/3 | 0/3 |
| price_tamper | 1/3 | 0/3 |
| exit_code_trust | 1/3 | 0/3 |
| judge_summary | 1/3 | 1/3 |
| idor_endpoint / react_fetch / rate_limiter | 0/3 | 0/3 |

Conditional subset: on the 5 tasks the baseline failed at least once, briefed runs
reproduced in 1/15.

**Per-task, haiku 3-sample run:**

| task | baseline | briefed |
|---|---|---|
| ci_linter | 3/3 | 0/3 |
| spa_tokens | 3/3 | 2/3 |
| price_tamper | 2/3 | 0/3 |
| exit_code_trust | 1/3 | 0/3 |
| rate_limiter | 0/3 | 1/3 |
| idor_endpoint / react_fetch / judge_summary | 0/3 | 0/3 |

Conditional subset: 2/12 on the 4 tasks the baseline failed at least once.

## 4b. Re-run after adding the relevance cutoff (2026-09-01)

`check` gained a top-k cutoff: it keeps the highest-ranked `limit` records (12 by
default) and reports how many it trimmed. That is a change to the retrieval path this
report measures, so the A/B was re-run rather than assumed safe.

| run | generator | judge | samples | baseline | briefed |
|---|---|---|---|---|---|
| ab-20260830-0003 (before cutoff) | sonnet | haiku | 3 | 8/24 (33%) | 1/24 (4%) |
| **ab-20260901-0133 (after cutoff)** | sonnet | haiku | 3 | **10/24 (42%)** | **2/24 (8%)** |

**Read the baseline first.** It moved 33% → 42% between runs, and the baseline arm never
receives a briefing — nothing about it changed. That 9-point swing is run-to-run variance
and sets the noise floor at n=24. The briefed arm's 4% → 8% is one additional
reproduction, inside that band.

**The one signal worth investigating** was `spa_tokens`, which went 0/3 → 2/3 briefed. If
the cutoff had trimmed the relevant record, that would be the ADR's miss-rate trigger
firing. It had not: the localStorage record appears in that task's briefing at
`--limit 12` exactly as it does at `--limit 40`. The judge's verdicts show the model used
`sessionStorage` via `WebStorageStateStore` and wrote a comment documenting the security
trade-off — it had the rule, understood it, and chose a variant the strict signal still
counts as web-storage persistence. (The earlier haiku run reproduced the same task 2/3
before any cutoff existed.)

That distinction is the one the flat-retrieval ADR is written around: its trigger is a
**retrieval miss** — a record that exists in scope and was not surfaced — not a model
failing to comply with a record it was handed. Measured miss rate after the cutoff
remains zero. Compliance is a separate, unmeasured problem.

## 4c. Re-run after indexing symptom and fix (2026-09-01)

`symptom` and `fix` joined the search index on both backends, with column weights
(title > body = symptom > fix). Before it, a record whose distinguishing words lived in
`symptom` — the field every command and doc calls "what a reader matches against" — was
unretrievable unless those words also appeared in the title. That is a change to the
retrieval path this report measures, so the A/B was re-run rather than assumed safe.

The three sonnet-generator runs, same 8 tasks, same judge, 3 samples per arm, 0% harness
failures in every one:

| run | change under test | baseline | briefed |
|---|---|---|---|
| ab-20260830-0003 | (before cutoff) | 8/24 (33%) | 1/24 (4%) |
| ab-20260901-0133 | after top-k cutoff | 10/24 (42%) | 2/24 (8%) |
| **ab-20260901-1238** | **after indexing symptom/fix** | **12/24 (50%)** | **1/24 (4%)** |

**Read the baseline column first, again.** It has now walked 33% → 42% → 50% across three
runs while nothing about the baseline arm has ever changed — it receives no briefing, and
no code it touches was modified. That 17-point spread is the noise floor at n=24, and it
is the most important number on this page: **differences smaller than about 17 points are
not interpretable in this design.**

What that permits and forbids:

- **Permitted:** the briefing effect itself. Baseline 33-50% against briefed 4-8% is a gap
  far larger than the noise floor, and it has survived three runs and a model tier.
- **Forbidden:** any claim about this change specifically. Briefed went 8% → 4%, which is
  two reproductions becoming one. That is inside the noise, and calling it an improvement
  would be reading a coin flip.

The defensible statement is the negative one: indexing symptom and fix **did not degrade**
retrieval, and the briefed arm has now been 1-2 reproductions out of 24 in every
sonnet run.

Per-task, this run — `spa_tokens` is again the only briefed reproduction, and again the
task where the baseline fails every time:

| task | baseline | briefed |
|---|---|---|
| idor_endpoint | 0/3 | 0/3 |
| price_tamper | 2/3 | 0/3 |
| react_fetch | 0/3 | 0/3 |
| judge_summary | 1/3 | 0/3 |
| exit_code_trust | 3/3 | 0/3 |
| spa_tokens | 3/3 | **1/3** |
| rate_limiter | 0/3 | 0/3 |
| ci_linter | 3/3 | 0/3 |

Conditional subset: 1/15 on the 5 tasks the baseline failed at least once.

## 4d. Exclusive stack-tag filtering: measured, and REVERTED (2026-09-02)

`ab-20260902-0538` — **48 runs, 3 failures (6%), usable.** Baseline 10/22 (45%), briefed
3/23 (13%).

That briefed figure is the worst of the four sonnet runs (4%, 8%, 4%, **13%**), and this
time it was not noise. The change under test made a record naming a stack invisible to a
repo that had not declared that stack, even when the record shared a subject the repo
wanted. The rate-limiter rule is tagged `security,dotnet`; the eval repo declares
`security` and not `dotnet`; the rule left the briefing; the briefed arm then reproduced
the very defect that rule describes, on a task where the baseline reproduced none.

Reproduced directly rather than inferred:

| interests declared | rate-limiter rule in the briefing |
|---|---|
| `python, method, security, …` (no `dotnet`) | **no** |
| none | yes |

**Blast radius: 35 of 172 org records** hidden from this repo, all of them sharing a
subject it had declared. The sample says why better than any argument:

- *Missing ownership scope check is an IDOR (CWE-639)* — tagged `security,dotnet`
- *materialize exited 0 having written zero files* — tagged `geospatial,data-quality`
- *Public dataset had x/y transposed* — tagged `geospatial,data-quality`

None of those is about .NET or geospatial. **A stack tag records where a lesson was FOUND,
not where it APPLIES**, and filtering on provenance as though it were applicability throws
away most of what a shared store is for. The change was reverted.

The complaint that motivated it stands: genuinely stack-specific rules — CQRS handlers,
aggregate discipline — do reach repos that have none of those things. Fixing it needs
applicability recorded separately from provenance, not a stricter reading of a tag that
never meant that. Until then, interest filtering stays any-match.

**Three runs failed**, all timeouts on the two slowest tasks plus one non-zero exit
(`spa_tokens` ×2, `rate_limiter` ×1). At 6% the run is usable under the 20% rule, but the
sample counts are uneven (22 baseline against 23 briefed), so per-task figures on those two
tasks carry less weight than the others.

Per task:

| task | baseline | briefed |
|---|---|---|
| idor_endpoint | 0/3 | 0/3 |
| price_tamper | 2/3 | 0/3 |
| react_fetch | 0/3 | 0/3 |
| judge_summary | 0/3 | 0/3 |
| exit_code_trust | 3/3 | 0/3 |
| spa_tokens | 2/2 | **2/2** |
| rate_limiter | 0/2 | **1/3** |
| ci_linter | 3/3 | 0/3 |

`spa_tokens` reproducing in both arms is the standing anomaly §4b named, not new. The
`rate_limiter` row is the finding.

**What this run bought:** it stopped a regression from shipping as an improvement. The
change was elegant, argued from the vocabulary's own stack/subject distinction, and made
retrieval worse in a way no test caught and no reading of the code would have revealed.
Post-hoc revert on measured evidence is the whole point of keeping the harness runnable.

## 5. Findings

1. **The briefing works, in both tiers.** Sonnet: 33% → 4%. Haiku: 38% → 12%. Every
   task the sonnet baseline failed was fully prevented except one residual
   (judge_summary 1/3).
2. **Cross-model headline: briefed haiku (12%) beat unbriefed sonnet (33%)** on the
   identical task set — a briefed budget model reproduced org-known defect classes at
   roughly a third the rate of an unbriefed frontier model.
3. **Context bought more than capability.** Upgrading the model (haiku→sonnet baseline)
   removed 5 points of defect reproduction; adding the briefing removed 26 (haiku) and
   29 (sonnet).
4. **Capability still matters at execution time.** Briefed sonnet (4%) beat briefed
   haiku (12%): haiku read the token-storage lesson and still put tokens in web storage
   2/3 times — knowing the rule and executing the alternative are different skills.
5. **ci_linter is the cross-repo thesis in one row:** 3/3 reproduced unaided in BOTH
   tiers, 0/3 briefed in both — prevented by a lesson recorded in a different repo
   weeks earlier.
6. **Anomaly, retained:** briefed haiku reproduced rate_limiter 1/3 where its baseline
   was 0/3 — a briefed run worse than baseline on one task. Small-sample noise or
   briefing-as-distraction; it stays in the data.

## 6. Threats to validity (read before quoting)

- **The task set is bait, constructed from the store's own lessons.** This measures
  exactly one thing: whether retrieval of known lessons prevents their known defect
  classes. It does NOT measure general code quality, novel-problem performance, or
  lessons the store lacks. (The store's own `qz_fixtures` lesson applies to this
  harness: fixtures written by the lesson-authors share the lesson-authors'
  assumptions.)
- **Single judge per run, judge models differ across the two 3-sample runs** (haiku
  judged sonnet; sonnet judged haiku). Cross-model comparisons therefore carry judge
  variance. Mitigations: strict per-task signals, verdicts include cited evidence, and
  spot-checks of reasons showed literal signal matching. A same-judge re-run would
  tighten this.
- **n = 3 samples per cell.** Enough to expose single-sample noise (documented above),
  not enough for tight confidence intervals. Directional claims only.
- **The briefing was harness-injected, not hook-delivered.** In production the same
  briefing text reaches the model via the fail-closed PreToolUse hook inside an agentic
  session; here it was prepended to a one-shot prompt, because headless generation never
  triggers an edit-matched hook. The briefing *content* is identical; the delivery layer
  (hook firing, binary resolution, fail-closed blocking) is exercised by the test suite
  and observed live, but not by this experiment. Likewise no Stop hook, gates, or verify
  step were in the loop — the experiment isolates the briefing variable and measures
  generation only, not the full enforced loop end to end.
- **Both models are one vendor's; "budget model" ≈ haiku.** The local-model version of
  the claim (via `GENERATOR_CMD="ollama run ..."`) is unmeasured — the harness supports
  it; nobody has run it yet.

## 7. Provenance of the earlier numbers

The 2026-07-17 experiment recorded in the sixth-surface decision record (defect
reproduction 50%→6% on covered tasks; 75%→8% where the baseline failed; a React
coverage gap measured at 3/3 in both arms, then 0% after seeding) used the same design
but its raw artifacts were not checked in. Those figures are historical record with
documented controls, not currently reproducible. Every number in §3 has a committed
receipt.

## 8. End-to-end run (2026-08-30): the whole loop, one task, three findings

The isolated experiment settled the content question. A first end-to-end run then tested
the *delivery* — a real agentic session in a scratch repo wired with `okl init` and
connected to the store through the shared service, versus a bare control repo, same
task (the strongest bait: `ci_linter`, 3/3 baseline failure in both model tiers).

| arm | hook fired? | result |
|---|---|---|
| control (no okl) | n/a | `pip install ruff` — unpinned (defect) |
| briefed, hook = PreToolUse | yes, logged before the Write | `pip install ruff` — unpinned (defect) |
| briefed, hook = UserPromptSubmit | yes, at prompt submit | `pip install ruff==0.14.0` — pinned, gated from repo root, no `paths:` filter, comments citing three lessons from two other repos |

Raw artifacts for this run — the generated workflow files, session transcripts, hook
log, and the service's 500 responses — are committed in
[`results/e2e-20260830/`](results/e2e-20260830/) (n=1 per arm; provenance notes inside).

**Finding 1 — the enforced read was silently unread.** The original hook fired on every
edit, retrieved the correct briefing, and printed it to a channel the model never sees:
Claude Code adds exit-0 stdout to the model's context only for `UserPromptSubmit` /
`SessionStart` (and a few others), never for `PreToolUse`. Every unit test passed (the
hook fired, resolved its binary, produced the right text) and the isolated A/B passed
(the content works when in context). Only a behavioral diff against a bare control
exposed the dead channel. Fix: delivery moved to `UserPromptSubmit`, which also makes
the *actual prompt* the retrieval query instead of the last commit message. Stored as
`n_428707b5e596`: *test the channel, not the firing.*

**Finding 2 — the write side ran unprompted.** The Stop hook fired at session end and
the agent attempted to record a genuinely new refinement of the pin rule (when the
registry is unreachable, pin the newest version you can verify exists, never a
plausible guess). It then obeyed the store's own "no run, no stamp" rule from the
briefing: the service rejected the record, so it declined to claim success and parked a
replayable command instead.

**Finding 3 — two defects in the remote record path**, both invisible to the test
suite because it only exercised local mode: an unknown-tag validation error surfaced as
an opaque HTTP 500 (the agent had invented tags outside the controlled vocabulary and
never saw the vocabulary list), and the client reported any HTTP error as "service
unreachable" — a validation error masquerading as an outage. `--scope repo` also
failed remotely because only the local branch defaulted the repo. All three fixed with
tests; the agent's parked lesson was replayed into the store with a valid tag.

n = 1 per arm: this run validates the delivery layer and the loop's mechanics, not
effect size — that remains the isolated harness's job. The fuller version:

- **Setup:** scratch repos wired with `okl init` — hooks registered, interests declared,
  store connected — one per (task, arm); the baseline arm's repo has the check hook
  disabled or the store empty.
- **Execution:** real agentic sessions (an agent with tools, not a one-shot prompt)
  performing the bait tasks, with the PreToolUse hook actually delivering the briefing
  fail-closed, the Stop hook prompting encoding, and gates runnable.
- **Measurement:** defect reproduction judged on the *committed code* the session
  produces, plus loop-level outcomes the current design can't see: did the hook fire,
  did the session record new lessons, did gates catch what generation missed.
- **Cost/noise trade-off:** agentic sessions are an order of magnitude more expensive
  per sample and introduce variance from tool use, planning, and self-correction — so
  run it after the isolated design has settled the content question (it has), sample
  small, and treat it as validating the delivery layer rather than re-measuring the
  briefing effect.

Second unrun extension: local/open-weight generators (`GENERATOR_CMD="ollama run ..."`)
to test the budget-tier claim beyond one vendor's model family.

## 9. Reproduction

```bash
python3 evals/ab_harness.py --samples 3                       # sonnet gen, haiku judge
GENERATOR_CMD="claude -p --model haiku" \
JUDGE_CMD="claude -p --model sonnet" \
python3 evals/ab_harness.py --samples 3                       # budget-tier arm
```

Wall-clock for the receipts above: ~36 min (sonnet run), ~21 min (haiku run).
