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

## 2b. The decision procedure — what this experiment can and cannot settle

Written after a change was shipped, measured, and reverted on the same day
(§4d). The reverting was correct; doing it in that order was not. These rules exist so
the next retrieval change is judged against a standard set BEFORE the numbers arrive.

### Pre-register, or the result is a story

Any change to the retrieval path — what is indexed, what is filtered, what is ranked,
what is trimmed — is written down before the run, stating:

1. **The prediction.** Which arm moves, in which direction, and by roughly how much.
2. **The falsifier.** The specific observation that would mean the change is harmful.
3. **The tasks at risk.** Which of the eight could plausibly lose a record they depend
   on, and which record.

Point 3 is the one that would have caught §4d before it ran. `rate_limiter` depends on a
rule tagged `dotnet`; the change hid off-stack records; nobody wrote that down, so a
predictable regression arrived as a surprise.

### The noise floor is 17 points, and it is not optional

The baseline arm receives no briefing and has never changed. Across four sonnet runs it
has read 33%, 42%, 50%, 45%. **That 17-point spread is measurement noise on an arm where
nothing moved**, so:

- A difference smaller than ~17 points, in either arm, is **not interpretable**.
- The briefing effect (baseline 33-50% against briefed 4-13%) clears it comfortably and
  is the only headline claim this design supports.
- Run-to-run movement *within* an arm is not a result. It has been mistaken for one.

### What promotes a per-task signal above noise

A single task moving is noise unless it comes with a mechanism. `rate_limiter` counted in
§4d because the causal chain was reproduced independently of the run: the rule was shown
absent from the briefing with interests declared and present without them. **A per-task
number plus a demonstrated mechanism is evidence; a per-task number alone is not.**

### Failure accounting changes how the run is read

- **Above 20% failures: RESULTS NOT USABLE**, printed before any score.
- **Below 20% but non-zero:** usable, and the affected tasks carry less weight, because
  failures fall unevenly. §4d ran 22 baseline against 23 briefed after three timeouts,
  all on the two slowest tasks — so those two tasks' per-task rows are the least reliable
  in the table, which is unfortunate given one of them carried the finding.
- **A run with 0% failures and one with 6% are not the same experiment.** Say which.

### The decision rule for shipping a retrieval change

Ship it if the briefed arm does not worsen beyond the noise floor **and** no task loses a
record it depends on. Revert if either fails. "The idea is sound" is not an input:
§4d's change was argued from the vocabulary's own stack/subject distinction, passed
review, passed its tests, and made retrieval worse.

### What this design cannot settle

The tasks are bait, built from the store's own lessons, so this measures *"does a
briefing prevent a defect the store already knows about"* — not general code quality, not
retrieval at scale, and not whether the store contains the right lessons. Threats to
validity are enumerated in §6 and should be read before quoting any figure.

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

### Correction (2026-09-02): the cutoff DID cause a retrieval miss

This section concluded the top-k cutoff caused no retrieval miss. That conclusion was
drawn from run outcomes — no task got obviously worse — and never from asking the
deterministic question directly: *is each task's governing rule still in the briefing?*

`evals/preflight.py` now asks it, and the answer is no for **`exit_code_trust`**. Its rule
(`seed:geospatial-defects:d15`) ranks below the top 12 for that task's wording and needs
`--limit 40` to surface. It has been absent from that task's briefing since the cutoff
landed.

The task still reads baseline 3/3, briefed 0/3 across runs, so the briefing prevented the
defect — but something OTHER than the designated rule did that work. The row was never
evidence for the rule it is filed under.

A second miss, unrelated to the cutoff: `react_fetch`'s rule is tagged `react`, which the
host repo does not declare, so interest filtering removed it. The harness now fetches its
briefing with `--interests ""`, because the experiment measures whether a briefing prevents
a defect, not whether the host repo's tag curation is good. Both were found in milliseconds
by a check that needs no model.

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

## 4e. PRE-REGISTERED: applies_to, and the first run on a fixed harness (2026-09-02)

Written before the run, per §2b.

**What changed since the last run.** Three things, and they are not equivalent:

1. `applies_to` — a new field recording where a lesson is VALID, separate from the tags
   that record where it was found. 7 records marked `dotnet` (Wolverine, HybridCache,
   Minimal APIs, Aspire orchestration, the .NET logging stack). Unset on everything else,
   which is the pre-change behaviour.
2. The harness now fetches briefings with `--interests ""`. Previously it inherited the
   host repo's interests, which meant `react_fetch` measured the absence of its own rule.
3. `evals/preflight.py` gates the run.

**Prediction.** The briefed arm improves or is unchanged; the baseline is untouched by
construction. The improvement, if any, comes from (2) — `react_fetch` receiving its rule
for the first time — not from (1), which cannot help these tasks because none of the 7
curated records governs one. The honest expectation is **no detectable change**, because
`react_fetch` reads 0/3 briefed already and cannot improve.

**Falsifier.** The briefed arm worsens beyond the noise floor, or any task that previously
read briefed 0/3 now reproduces. Either means the curation hid something the pre-flight
did not think to check.

**Tasks at risk.** None of the 7 curated records is a task's governing rule — verified by
pre-flight, which passes 7/8 with `exit_code_trust` as the one accepted gap (its rule ranks
below the top-12 cutoff; §4b correction). `exit_code_trust` therefore still measures the
briefing WITHOUT its designated rule, and its row should not be read as evidence about
that rule.

**What this run is for.** Every earlier number in this report was produced while two of
eight tasks were not receiving the rule they test. The headline survives that — the effect
is 35-45 points and both broken tasks read briefed 0/3 anyway — but the per-task tables
meant less than they appeared to. This establishes the first reference point on a harness
whose retrieval has been verified.

### Result (2026-09-03)

Receipt: `evals/results/ab-20260903-0157.json`. Generator and judge as configured in §1.

| arm | reproduced | rate |
|---|---|---|
| baseline | 8/23 | 35% |
| briefed | 2/24 | 8% |

One recorded failure: `rate_limiter` baseline sample 0 timed out at 300s, so that arm
carries 23 samples rather than 24 (§"Failure accounting"). Failure rate 2%, below the 10%
usability bar.

**Falsifier: not triggered.** The briefed arm did not worsen — 8% sits mid-band against the
historical 4%, 12%, 8%, 4%, 13%. No task that previously read briefed 0/3 now reproduces:
`spa_tokens` reads 2/3, but it has read 1-2/3 in every run since 2026-08-30, four runs
before this change.

**The prediction held. The reasoning behind it did not.** See the correction below.

### Correction (2026-09-03): the pre-registration's premise 1 was false

The pre-registration above states that `applies_to` was set on 7 records. **It was set on
zero.** The field existed, both write paths worked, and nothing had ever written through
them.

Verified three ways: raw SQL against the store with the WAL checkpointed returns 0 of 205;
the string `applies_to` appears zero times across all 11 seed files; and no database on
disk carries a non-null value in that column. The corpus was written before the field
existed, `record` and `seed` are the only writers and both act at creation time only, so a
field nobody re-typed stayed empty.

**What this run therefore measured.** Changes (2) and (3) — the `--interests ""` fix and
the pre-flight gate — and nothing else. It is not evidence about `applies_to` in either
direction. The stated expectation of "no detectable change" from (1) was correct by
accident: a field set on nothing cannot move a number. The clause "which cannot help these
tasks because none of the 7 curated records governs one" was true of a set that did not
exist.

The pre-registration text above is left exactly as written. Editing it after the fact would
destroy the only property that makes it worth writing.

**Since corrected.** 32 records now carry `applies_to` — 21 `dotnet`, 7 `geospatial`,
4 `react` — written into the seed files so they survive `okl seed`, which is what the
earlier attempt did not do. The criterion was per-record judgment on whether the lesson is
*false or meaningless* off-stack, never the tag: `nc_idor`, `r_pagination_cap`,
`r_rate_limiter_scaleout` and `r_guid_v7` stay unset and reach every repo, because deriving
applicability from provenance is the §4d defect. Also left unset after inspection:
Testcontainers' macOS `DOCKER_HOST` quirk (that library ships for Java, Go, Python and
Node) and `d15` (exit 0 having written zero files), which is tagged `geospatial` and is
among the most portable records in the store.

Behaviour confirmed in both directions on the task *"order the Wolverine middleware
pipeline and register a handler for DI"*: a repo declaring `dotnet` receives 10 records
of which 7 are stack-gated; okl and a Rust repo receive 8 each with 0 gated. The gated
records disappear off-stack **and the portable ones still arrive** — the property §4d's
filter destroyed.

The evals are unaffected: the harness fetches with `--interests ""`, which bypasses the
filter entirely, and pre-flight still passes 7/8 with `exit_code_trust` as the one
registered gap.

## 4f. Re-run after the applies_to backfill — confounded, and not a test of it (2026-09-03)

Receipt: `evals/results/ab-20260903-0308.json`. 48 runs, **0 failures** — raising
`--timeout` from 300s to 420s recovered the sample §4e lost.

| arm | reproduced | rate |
|---|---|---|
| baseline | 11/24 | 46% |
| briefed | 3/24 | 12% |

### RESULTS NOT COMPARABLE ACROSS RUNS: the judge was changed

This run was judged by **opus**. Every previous sonnet-generator run in this report was
judged by **haiku**. The change was made when the run was launched, was not pre-registered,
and was not noticed until the receipts were tabulated afterward.

The run is internally valid — both arms saw the same judge, so the 46%-vs-12% contrast
within it stands, and the harness's judge≠generator guard held. But **no figure here may be
compared to §4a-§4e**, and both arms moving up together (baseline 35%→46%, briefed 8%→12%)
is exactly the signature a stricter judge produces. Attributing that movement to sampling
noise, to the timeout change, or to the backfill would each be unfounded.

Two consequences, stated rather than buried:

- **§4e's falsifier cannot be evaluated against this run.** It is defined relative to the
  noise floor of a series measured with a different instrument. Briefed 12% "sitting inside
  the historical band" is not a finding; it is a comparison this run cannot support.
- **This is not the replication it was intended to be.** A replication requires the same
  instrument. Establishing the run-to-run noise floor on an unchanged retrieval still needs
  a clean run with the documented judge.

The finding below about `applies_to` is independent of the judge — it is a deterministic
property of the retrieval path, established by query rather than by outcomes, and it holds
regardless of who graded the output.

### This run did not test applies_to either, and no run of this harness can

The intent was to measure the 32-record backfill. It cannot, and the reason is structural
rather than a bug.

The harness fetches briefings with `--interests ""` (§4b correction). The filter reads:

```python
if applies and wanted and not (applies & wanted):
    return False
```

An empty `wanted` short-circuits it. Confirmed against a real gated org-scoped record —
`g_multiyear_window_composite`, `applies_to=geospatial` — asked whether it reaches a python
repo:

| interests | reaches it? |
|---|---|
| `""` (what the harness sends) | **True** — filter bypassed |
| `python, method` | False — correctly gated |
| `dotnet` | False — correctly gated |

So the briefings in this run are byte-identical to §4e's. The retrieval did not change;
the timeout and the judge did. Whatever separates 46%/12% from 35%/8%, none of it can be
the backfill.

`--interests ""` is not a defect to fix. It was set deliberately, because the experiment
measures whether a briefing prevents a defect, not whether a repo's tag curation is good.
The consequence is that **`applies_to` is outside this harness's measurable surface by
design**: it changes which records reach a repo *with declared interests*, and every task
here runs with interests off. Measuring it through the A/B would need a new dimension — the
same task run in repos declaring different stacks.

That experiment is not worth building. `applies_to` is a retrieval predicate, and §4b's
lesson is that retrieval questions are deterministic: a query answers them in milliseconds,
with more precision than 48 model calls. The unit tests
(`test_applies_to_excludes_where_tags_must_not`,
`test_a_shared_subject_keeps_an_off_stack_record_in_the_briefing`) plus the direct
both-directions check are the right instrument, and they already answer it. A run of this
harness would only ever restate the noise floor.

**The generalisable lesson: an experiment cannot measure a filter it disables.** §4e failed
to measure `applies_to` because no record set it; §4f failed for a different reason, on a
corpus where 32 records do. Both were invisible from the outcome numbers and both took one
deterministic query to see.

### spa_tokens: briefed 3/3, equal to baseline

Flagged rather than buried, with the judge caveat attached. In this run briefed
`spa_tokens` read **3/3 — identical to its own baseline**, so the briefing bought nothing
measurable on that task. Under the haiku judge it has read 0/3, 2/3, 2/3, 1/3, 2/2, 2/3;
the step to 3/3 is not cleanly separable from the judge change and must not be reported as
a trend.

What is *not* judge-dependent: this is not a retrieval failure. Pre-flight confirms the
rule (`rx_tokens_localstorage`) reaches the briefing, and that record is deliberately unset
in the backfill, so nothing in this change touched it. Every reading of this task across
every run has the briefed arm at or near its baseline, which makes it the standing
counter-example to the headline — §5's finding 4, that knowing the rule and executing the
alternative are different skills. It belongs in the report as the honest ceiling on this
approach, not smoothed into the aggregate. Whether it is genuinely worsening is a question
for a clean run.

## 4g. Back on the documented instrument — the series restored (2026-09-03)

Receipt: `evals/results/ab-20260903-1214.json`. Judge back to haiku, which is 9 of 11
receipts and the series every quotable figure in this report was measured against.

| arm | reproduced | rate |
|---|---|---|
| baseline | 8/22 | 36% |
| briefed | 1/21 | 5% |

**Comparable, and it replicates.** Against the haiku series, baseline has read 33%, 42%,
50%, 45%, 35% and now 36%; briefed has read 4%, 8%, 4%, 13%, 8% and now 5%. Both land
mid-band. §4f's elevated 46%/12% was the opus judge, exactly as §4f said it could not rule
out.

**`spa_tokens` was the judge, not a trend.** It read briefed 3/3 under opus and 1/2 here,
against prior haiku readings of 2/3, 2/3, 1/3, 2/2, 2/3. §4f's refusal to call it a trend
was correct. It remains the standing counter-example — briefed at or near baseline in every
run — but it is not deteriorating.

**Harness health, flagged.** 5 failures (10%): three generator timeouts at 420s and two
exit-1s. Below the 20% usability bar, but the highest failure count in the series, and the
timeouts happened despite the limit having been raised from 300s specifically to prevent
them. That is generation getting slower, not a limit set too tight.

### The instrument guard found its own defect on its first live run

The guard added after §4f compared the run's instrument against the **most recent receipt**.
The most recent receipt was §4f — the anomaly. So this run, which returned to the documented
judge and restored the series, was announced as `NOT COMPARABLE ACROSS RUNS`.

The message was technically true and practically backwards: it told the reader to discard
the one run that had fixed the problem. A guard that fires on the repair is worse than no
guard, because it trains people to ignore it.

Now compared against the **modal** instrument across all receipts, which is what a number
actually gets quoted against, and a single off-series run cannot redefine it. Off the
series it names the series and how many runs back it; returning to the series after a
departure reports the restoration rather than staying silent.

The regression test needed the same correction. Its first version compared against this
repo's real receipts and passed against the broken implementation — because once the series
is restored, the newest receipt *is* the modal one and the two rules agree. It now builds a
temporary receipt history (three haiku, newest opus) via `AB_RESULTS_DIR`, which is the §4f
shape and separates them. Proved by reintroducing the original comparison and watching it
go red.

## 4h. PRE-REGISTERED: does interest filtering earn its place? (2026-09-03)

Written before the run, per §2b.

**Why this and not `applies_to`.** §4f established that `applies_to` is outside this
harness's measurable surface: it changes what reaches a repo *with declared interests*, and
every run here sets `--interests ""`. Interest filtering **is that pinned flag**. Unpinning
it is the one retrieval question this harness can actually answer.

**What is being tested.** The briefed arm fetches with okl's own declared interests
(`python, method, security, agent-safety, retrieval-design, eval-integrity, data-quality`)
instead of unfiltered. Everything else is held: same tasks, same generator, same haiku
judge, same sample count. The comparison is against `ab-20260903-1214.json` (§4g).

**The baseline arm is an internal control.** It uses no briefing at all, so filtering
cannot touch it. If the two runs' baselines differ materially, that difference is sampling
noise and calibrates how much of any briefed difference to believe. This is the cleanest
control this harness has ever had, and it is free.

**Deterministic pre-flight, run first.** Exactly one task loses its governing rule under
filtering: `react_fetch`, whose rule is tagged `react` — the §4b case. Seven of eight keep
theirs, so the comparison is not rigged. `exit_code_trust` loses nothing.

Filtering removes a mix of noise and signal, which is why the net is not predictable from
inspection:

| task | records lost to filtering |
|---|---|
| `idor_endpoint` | a geospatial `num_classes` off-by-one (noise), GUIDv7 (marginal) |
| `price_tamper` | a frontend bundle budget (noise on a payment task) |
| `rate_limiter` | a STAC imagery date-range bug (noise), parallel-awaits (marginal) |
| `spa_tokens` | TanStack mutation invalidation, feature boundaries (marginal) |
| `react_fetch` | **its own governing rule**, plus React Compiler and waterfalls (signal) |

**Prediction.** No detectable change. `react_fetch` reads baseline 0/3 briefed 0/3 in every
run and has no discriminating power, so losing its rule cannot show up in the aggregate;
what filtering removes elsewhere is mostly off-topic records that were not doing work. If
anything moves, a small improvement is more likely than a decline, because three tasks shed
records that are plainly irrelevant to them.

**Falsifier.** The briefed-filtered arm worsens beyond the 17-point noise floor, or any
task that currently reads briefed 0/3 reproduces. Either means filtering removed something
load-bearing that the pre-flight did not think to check — which is exactly the §4b failure,
one level up: pre-flight verifies the *designated* rule survives, not whatever else was
preventing the defect.

**What this cannot settle.** The task set is deliberately cross-stack, to test cross-repo
transfer. A repo whose work matched its declared interests would lose less. A null result
here is therefore weak evidence that filtering is harmless in general, and no evidence at
all that it helps.

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
