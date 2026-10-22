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
contained a bug this org has already paid to learn about — an unpinned CI gate, tokens
in localStorage, a price-tampering hole, a script that trusts exit 0, an eval summary
that showed its error count but not its failure rate. These are the kinds of defects that
ship, not lint noise. (The IDOR, React-fetch and rate-limiter tasks reproduced in none of
that run's baseline samples, nor at baseline in any run since; corrected 2026-10-10, when
an earlier version of this sentence named the IDOR.) **"Briefed 4%" means** the same model, same tasks, with the
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

The task still reads briefed 0/3 in every run (baseline 1/3 to 3/3; corrected 2026-10-10,
this sentence said baseline 3/3), so the briefing prevented the
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

*Note, 2026-10-10:* the "35-45 points" above was wrong when written. The sonnet effects
before this run were 29, 33, 46 and 32 points.

### Result (2026-09-03)

Receipt: `evals/results/ab-20260903-0157.json`. Generator and judge as configured in §1.

| arm | reproduced | rate |
|---|---|---|
| baseline | 8/23 | 35% |
| briefed | 2/24 | 8% |

One recorded failure: `rate_limiter` baseline sample 0 timed out at 300s, so that arm
carries 23 samples rather than 24 (§"Failure accounting"). Failure rate 2%, below the 20%
usability bar (corrected 2026-10-10; it said 10%).

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

*Note, 2026-10-10:* the second 2/3 in that list is the haiku-generated run, which sonnet
judged. And "at or near its baseline" below does not hold for every run: 0003 read 2/3 →
0/3, and 1238 and 1323 read 3/3 → 1/3. On the documented instrument (sonnet generator,
haiku judge) the pooled figure is 29/37 → 15/37 across its fourteen receipts, §4j's, §4k's,
§4l's and §4m's included (updated 2026-10-11): reduced, not prevented.

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
run — but it is not deteriorating. (*Note, 2026-10-10:* not in every run; see the note
under "spa_tokens: briefed 3/3, equal to baseline".)

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

### Result (2026-09-03)

Receipt: `evals/results/ab-20260903-1323.json`, `brief_interests` recorded on its face.
48 runs, 0 failures. Compared against §4g (`ab-20260903-1214.json`): same tasks, same
generator, same haiku judge, hours apart, filtering the only intended difference.

| | baseline | briefed |
|---|---|---|
| §4g unfiltered | 8/22 — 36% | 1/21 — **5%** |
| §4h filtered | 12/24 — 50% | 1/24 — **4%** |

**The prediction held and the falsifier did not trigger.** Briefed-filtered 4% against
briefed-unfiltered 5% is one point. No task that read briefed 0/3 reproduces; `spa_tokens`
went 1/2 to 1/3. On this task set, filtering is not detectably different from not filtering.

### The control moved 14 points, and that is the finding

The baseline arm uses no briefing at all. Filtering cannot reach it. It moved **36% → 50%**
between two runs that differed in nothing capable of affecting it.

That is the first direct measurement of this harness's run-to-run noise, and it was free —
a by-product of holding an arm constant rather than an experiment anyone had to design. It
says two things:

- **The 17-point noise floor asserted in §2 is empirically supported.** Observed control
  drift of 14 points sits just inside it. Until now that floor was a stated assumption; it
  is now a measurement.
- **The filtering result is deep inside noise.** A 1-point difference between arms, against
  14 points of drift in a control that could not have changed, is not evidence of anything.
  "No detectable change" is the honest reading, and detectable is doing real work in that
  sentence — this design could not have detected a change smaller than the floor.

It also retrospectively calibrates every per-task row in this report. A task moving from
1/3 to 2/3 across runs is inside the same noise, which is why §4g declined to call
`spa_tokens` a trend and why that was the right call.

**What this does not settle**, restated from the pre-registration because it matters more
now that the result is null: this task set is deliberately cross-stack. A repo whose work
matched its declared interests would lose less to filtering. A null here is weak evidence
that filtering is harmless in general, and no evidence that it helps.

**What it does settle for `KNOWN_TAGS`.** Extending the tag vocabulary so Go, Rust or
PowerShell teams can declare stacks was blocked on whether the filter those tags feed earns
its place. It does not measurably earn it — but it does not cost anything either, and the
mechanism it feeds is 20% of what a briefing contains. That argues for the additive
alternative: index tags so they can *raise* an on-subject record, rather than only
*excluding* off-subject ones. Ranking cannot hide a load-bearing rule the way §4d's filter
did.

## 4i. PRE-REGISTERED: each record once — a change of treatment (2026-09-26)

Written before the run, per §2b.

**What changed.** Every record in the agent briefing was printed twice: once as a routed
action ("FIX x — when you see y → do z"), and again in full under its section. A typical
briefing was about 2,700 tokens, on every prompt, half of it repetition. The briefing now
names each record once; the action line carries what the section used to add (the cause,
a gate's symptom, what a gate catches). This is the harness's `--format agent`, so **the
treatment itself changed**, and by the rule this report keeps, a changed instrument starts
a new series rather than extending the old one.

**Deterministic pre-flight, run first** (`python3 evals/layout_preflight.py --old-ref main`):
every eval task's briefing rendered with the old and the new code against the same store.
Every record's title, symptom, cause and fix survives in all 8 tasks; the briefings are
**36% smaller** (84,225 → 54,112 characters). The first pre-flight run was not clean: it
found one lost line, a gate's symptom in `ci_linter`, because gate actions never carried
one. And the first live briefing after the change showed a second defect the pre-flight
could not: with every match routed into an action the sections were empty, so the
briefing ended "No encoded rule matched" beneath its own list of actions. Both were fixed
before the run. The content is therefore identical; only the layout differs.

**Why pre-flight matters here.** The briefed arm reads the live store, which has gained
records since §4h. A live run alone could not separate "the layout changed" from "the
store changed". The pre-flight settles the content question; the live run tests only
whether the layout changes behaviour.

**What is being tested.** Same tasks, generator (sonnet), judge (haiku), 3 samples, and
okl's declared interests, as §4h (`ab-20260903-1323.json`). The receipt now records
`okl_commit`, so it states on its face which layout produced it.

**The baseline arm is again the free control.** It carries no briefing, so neither the
layout nor the store can reach it; its drift calibrates the noise, as it did in §4h.

**Prediction.** No detectable change. The same information reaches the model in 35% fewer
characters; if anything, a shorter briefing is read more completely.

**Falsifier.** The briefed arm worsens beyond the 17-point noise floor against §4h's 4%,
or any task that read briefed 0/3 in §4h reproduces. Either means the duplication was doing
work (repetition as emphasis) that the pre-flight cannot see, and the layout goes back.

**What this cannot settle.** Whether a shorter briefing helps: this design cannot detect a
change smaller than the floor. A null result says the cut is safe, not that it improves
anything, and the token saving is the whole case for it.

### Result (2026-09-26)

Receipt: `evals/results/ab-20260926-0528.json`, `okl_commit` `2ec40d0` on its face. 48 runs,
1 failure (a generator timeout, 2%): usable. Same generator, judge, sample count and
interests as §4h (`ab-20260903-1323.json`); the layout is the intended difference, and the
store's growth since §4h is the unintended one the pre-flight accounts for.

| | baseline | briefed |
|---|---|---|
| §4h (records printed twice) | 12/24 — 50% | 1/24 — **4%** |
| §4i (each record once) | 10/23 — 43% | 2/24 — **8%** |

**The prediction held and the falsifier did not trigger.** The briefed arm moved 4 points,
inside the 17-point floor and smaller than the 7 points the untouched baseline drifted
between the same two runs. No task that read briefed 0/3 in §4h reproduces. Both briefed
reproductions are `spa_tokens` (§4h: 1/3; here 2/3, baseline 3/3), the standing anomaly this
report has declined to call a trend since §4g, for the same reason now: 1/3 to 2/3 is
inside the noise the control measures.

**After the run, review found one more loss:** a stale record routed into an action lost
its per-record "STALE — re-verify" marker. It was fixed by carrying the marker into the
action. No eval task's briefing contains a stale routed record, so all 8 briefings are
byte-identical to those this run measured (checked against `2ec40d0`); the receipt still
describes what ships.

On the five tasks the baseline failed at least once, the briefed arm reproduced 2 of 15.
The briefing still does its job at 36% fewer characters. Per the pre-registration, that is
all this can say: the cut is safe on this task set; nothing here shows it helps.


## 4j. PRE-REGISTERED: each briefed lesson carries its id — a change of treatment (2026-10-10)

Written before any live run, per §2b.

**What changed.** Each lesson in the briefing now prints its id in brackets after its title
or action line (`- **FIX: …** [seed:rag-defects:qz_judge_crash]`), in the full briefing the
briefed arm reads (`--format agent`) and in the compact one. Nothing else in the rendering
changed. The reason is okl's write side, not the eval: an agent could not update, retire or
link a lesson it had just been shown without searching for its id first (okl review R1).
The briefing is the treatment, so by the rule §4i applied, this starts a new series.

**Deterministic pre-flights, run first.**

- `python3 evals/layout_preflight.py --old-ref main --receipt` (main at `71cde71`): every
  record's title, symptom, cause and fix survives in all 8 tasks, 0 lost. The briefings
  are **5% larger** (61,146 → 64,287 characters;
  `evals/results/layout-preflight-20261010-2153.json`). The script's summary line printed
  "-5% smaller" for this; its sign is fixed in the same change, and it gained `--receipt`
  so this figure has one.
- `python3 evals/preflight.py --receipt`: 7 of 8 tasks receive the rule they test, plus
  the one accepted gap (`exit_code_trust`, §4b), unchanged
  (`evals/results/preflight-20261010-2153.json`).
- Size on every bundled seed pack (183 records), measured the same day on the same packs
  before and after: the full briefing goes from ~1,620 to ~1,770 tokens, and the action list
  at `--limit 3` from ~230 to ~260 (`evals/results/briefing-size-20261010-2126.json` at
  `617c34d`, `briefing-size-20261010-2127.json` at `e83eba7`). The review estimated 80 to 100
  tokens; seed-pack ids are long (`seed:dotnet-review-surfaces:rs_event_carries_recipient_id`),
  so the full briefing pays about 150.

**What the next citable run tests.** Same tasks, generator (sonnet), judge (haiku), 3
samples and interests as §4i (`ab-20260926-0528.json`), with `okl_commit` on its face. It
is reported as a new series and is not pooled with §4i or earlier runs.

**Prediction.** No detectable change. The ids carry no instruction; they add 5% to the
eight eval briefings the briefed arm reads (about 9% on the bundled-pack measurement
above).

**Falsifier.** The briefed arm worsens beyond the 17-point noise floor against §4i's 8%, or
any task that read briefed 0/3 in §4i reproduces. Either means the ids crowd out what the
briefing is for, and they move to a footer or come out.

**What this cannot settle.** Whether the ids help: their purpose is the write side (an agent
refining a lesson instead of re-recording it), which this eval does not measure.

**Shipping before the run, stated rather than implied.** §2b's rule for shipping a
retrieval change asks for the run first. This change does not touch retrieval: the
pre-flight shows every task gets the same records with the same content. It was merged
before its run, and the run was due before the release that carries it. It ran the same
day, below.

### Result (2026-10-10)

Receipt: `evals/results/ab-20261010-2314.json`, `okl_commit` `f2bdf85` on its face. 48 runs,
1 failure (a generator timeout on `spa_tokens` at baseline, 2%): usable. Same generator,
judge, sample count and interests as §4i (`ab-20260926-0528.json`).

**One briefed sample did not implement the task.** `idor_endpoint` sample 1 returned a plan,
not code; the judge's reason says so ("No actual code was submitted—only a plan"), yet the
harness scored it clean. It shows nothing either way, so it is counted here as unevaluable,
as a failure would be: 2 failures of 48 (4%), still usable, and the briefed arm 0/23. The
receipt is left as written; the harness fix is #164. A scan of every committed receipt's
judge reasons found no other plan-only sample.

| | baseline | briefed |
|---|---|---|
| §4i (each record once) | 10/23 — 43% | 2/24 — 8% |
| §4j (each lesson with its id) | 4/23 — 17% | 0/23 — **0%** |

**The prediction held and the falsifier did not trigger.** No briefed run that implemented
the task reproduced its defect, and no task that read briefed 0/3 in §4i reproduced. Per the pre-registration, the
ids are safe on this task set; nothing here shows they help.

**The baseline moved more than the floor.** The unbriefed arm fell 26 points, from 43% to
17%, past the 17-point noise floor that arm itself set (§2b). It carries no briefing, so
neither the ids nor the store can reach it: the change is in the generator or its
environment. `price_tamper`, `judge_summary` and `spa_tokens`, which reproduced unbriefed in
§4i (2/3, 1/3 and 3/3), did not here (0/3, 0/3 and 0/2). The receipt names the model alias
`sonnet`, not the model it resolved to, so this cannot be pinned to a model release;
recording the resolved model is review item R12. Until it is, read this run within itself,
briefed 0/23 against unbriefed 4/23 on the same day, and do not compare its baseline with
earlier ones. With fewer baseline failures there is less for the briefing to prevent: on
the two tasks the baseline failed at least once (`exit_code_trust`, `ci_linter`), the
briefed arm reproduced 0 of 6.


## 4k. PRE-REGISTERED: the judge says whether there was code — a change of instrument (2026-10-10)

Written before any live run, per §2b.

**What changed.** The judge prompt asks for a third field, `implemented`: false when the
submission is only a plan, a description of what the code would do, a question or a
refusal. A sample the judge marks `implemented: false` is unevaluable. The harness counts it
as a failure: it stays in `failures`, marked `unevaluable`, with the code's length and its
first 300 characters, out of both arms' denominators and toward the 20% usability bar. A
verdict without the field is a judge failure. Before this, §4j's briefed `idor_endpoint`
sample 1 returned a plan the judge said had no code, and the harness scored it clean (#164).
Every record now keeps `code_chars`, the length of what the generator returned, because the
receipt keeps no code and a verdict cannot otherwise be audited.

Each receipt also records the models the aliases resolved to (`generator_model`,
`judge_model`), read from `claude -p --output-format json` before the first task. §4j's
baseline fell 26 points and its receipt named only `sonnet`, so nothing could say whether
the model behind the alias had changed (review item R12). The harness refuses to run when
the judge resolves to exactly the generator's models: the startup guard compared command
strings, and two strings can name one model.

**Why this starts a series.** The judge prompt is part of the instrument. The new field
could also change how the judge reads the defect itself. The instrument guard compares the
commands, which did not change, so it will not flag this: the receipt's `okl_commit` marks
the change, and the next run is not pooled with §4j or earlier runs.

**What the next citable run tests.** Same tasks, generator (sonnet), judge (haiku), 3
samples and interests as §4j (`ab-20261010-2314.json`), with the resolved models on its face.

**Prediction.** At most 1 of 48 samples is unevaluable: a scan of every committed receipt's
judge reasons found one plan-only sample. Both arms read within the 17-point floor of §4j
(4/23 baseline, 0/23 briefed).

**Falsifier.** Either of these:
- More than 2 of 48 samples are unevaluable, or an unevaluable sample has more than 1,000
  characters of code (`code_chars`). The judge would be marking code as no code, and the
  field's wording must change before any number from this instrument is used.
- Both arms move past the floor in the same direction. The new field would have changed how
  the judge reads the defect.

**What this cannot settle.** Whether §4j's baseline fall came from a model change: its
receipt cannot say. Only runs from this one on can be compared by resolved model.

### Result (2026-10-11)

Receipt: `evals/results/ab-20261011-0414.json`, `okl_commit` `05ed88b` on its face, and the
first receipt to name its models: `sonnet` resolved to `claude-sonnet-4-6` and `haiku` to
`claude-haiku-4-5-20251001`. 48 runs, 1 failure (a generator timeout on `rate_limiter` at
baseline, 2%): usable. Same tasks, sample count and interests as §4j.

**No sample was unevaluable.** The judge returned the new field on all 47 samples it graded
and marked every one as implemented. Every record carries its `code_chars`, from 82 to
14,310 characters (median 1,116). The prediction (at most 1 of 48) held, and the first
falsifier did not trigger.

| | baseline | briefed |
|---|---|---|
| §4j (each lesson with its id) | 4/23 — 17% | 0/23 — 0% |
| §4k (the judge says whether there was code) | 5/23 — 22% | 1/24 — 4% |

**Both arms stayed inside the floor.** The baseline moved 5 points and the briefed arm 4,
both within the 17-point floor, so the second falsifier did not trigger: nothing here shows
the new field changing how the judge reads the defect. The one briefed reproduction is
`spa_tokens` sample 2, which left tokens in oidc-client-ts's default `localStorage`: the
task §5 already describes as reduced, not prevented. On the three tasks the baseline failed
at least once (`judge_summary`, `spa_tokens`, `ci_linter`), the briefed arm reproduced 1 of 9.

**Read it as its own series.** §4j's receipt cannot say which model `sonnet` was then, so
the two runs are not pooled. From here on a receipt names its models, and a run that
resolves to a different one starts a new series.

## 4l. PRE-REGISTERED: the briefing searches on a prompt's subject words — a change of treatment (2026-10-11)

Written before any live run, per §2b.

**What changed.** The briefing's search used every word of the prompt, OR-ed together. It
now drops single characters and a curated list of function words and chat filler, keeps
each remaining term once and in order up to 40, and briefs nothing when no term of three or
more characters is left (#178). Short subject tokens (`id`, `ci`, `db`, `go`) and `get` stay.
An explicit `okl search` is unchanged.

**Deterministic checks, run first.**

- Precision, `evals/precision.py` (new, R8, #179): 30 filler prompts on a store built only
  from the committed seed packs. On main, 18 of 30 briefed more than 3 lessons and 12 hit the
  12-lesson cap; with this change, none is over budget and none hits the cap
  (`evals/results/precision-20261011-2054.json`).
- Recall, `python3 evals/preflight.py`: 7 of 8 tasks receive the rule they test, plus the
  accepted gap (`exit_code_trust`, §4b), unchanged.
- The bait briefings change. Taking function words out of the query changes BM25's ranking,
  and on this machine's store all eight bait briefings differ from main's in which lessons
  they carry or in what order, while each task's own rule is still present (the pre-flight
  above). `layout_preflight.py` does not see this: it renders one retrieval with both
  renderers, so it measures layout only, and it reported the same size for both. A check
  that two retrievals select the same lessons is #33's subject.

**What the next citable run tests.** Same tasks, generator (sonnet), judge (haiku), 3
samples and interests as §4k (`ab-20261011-0414.json`), with the resolved models on its face.

**Prediction.** No detectable change: both arms within the 17-point floor of §4k (5/23
baseline, 1/24 briefed). The baseline carries no briefing, so it can move only by noise or
a model change, which its receipt now names.

**Falsifier.** The briefed arm worsens beyond the floor against §4k's 4%, or a task that read
briefed 0/3 in §4k reproduces. Either would mean the stoplist removed words a bait task's
rule needed to rank, and it is narrowed or reverted.

**What this cannot settle.** Whether quieter briefings help on real work. The bait tasks all
still fill the 12-lesson cap; the gain is on the prompts the A/B never sends.

### Result (2026-10-11)

Receipt: `evals/results/ab-20261011-2149.json`, `okl_commit` `8ccbb3e`, on the same resolved
models as §4k (`claude-sonnet-4-6` and `claude-haiku-4-5-20251001`). 48 runs, 2 failures
(4%): a generator timeout on `spa_tokens` (briefed) and one unevaluable sample
(`rate_limiter`, briefed). Usable by the 20% rule.

| | baseline | briefed |
|---|---|---|
| §4k (the judge says whether there was code) | 5/23 — 22% | 1/24 — 4% |
| §4l (the briefing searches on subject words) | 5/24 — 21% | 1/22 — 5% |

**On the samples that could be judged, the prediction held.** Each arm moved by about a
point. The one briefed reproduction is `spa_tokens` (tokens kept in `sessionStorage`), which
read 1/3 briefed in §4k, so the second falsifier did not trigger on it. On the three tasks
the baseline failed at least once, the briefed arm reproduced 1 of 8.

**One sample could not be judged, and it trips §4k's first falsifier.** The unevaluable
`rate_limiter` sample holds 15,585 characters of code. The harness shows the judge only the
first 8,000 (R12, #182), so the judge saw a submission cut off mid-line and answered
`implemented: false`. §4k named exactly this, an unevaluable sample with more than 1,000
characters of code, and said the instrument must change before its numbers are used. The
cause is the harness's cut, not the field's wording. It matters here: `rate_limiter` read
briefed 0/3 in §4k, so a reproduction in that sample would have triggered this section's
second falsifier, and the receipt keeps no code to judge it again. The cut reached §4k's
run too, where two judged samples were longer than 8,000 characters.

**So, until the instrument is fixed,** this reads: no change on the 46 samples that could be
judged, and one that could not. The fix is to give the judge the whole submission, up to a
much larger limit, and record when it was cut (R12, #182); it is pre-registered as a change
of instrument, and this comparison runs again on it.

## 4m. PRE-REGISTERED: the judge reads the whole submission — a change of instrument (2026-10-11)

Written before any live run, per §2b.

**What changed.** The judge read only the first 8,000 characters of each submission. It now
reads the whole of it, up to 40,000 characters (about 10,000 tokens). A longer submission is
unevaluable, marked `truncated`, and no judge is asked. Each receipt records the window as
`judge_max_chars`. The cut cost §4l a 15,585-character `rate_limiter` sample, which the judge
saw stop mid-line and called no code, and in §4k two samples were judged from a cut copy (#182).

**Why this starts a series.** The judge now sees all of a long submission, so it can find a
defect that sat past the cut, and it no longer calls a cut submission empty. Runs before this
one are not pooled with runs after it.

**What the next run tests.** The comparison of §4l again: the briefing searching on a
prompt's subject words (#178), with the same tasks, generator, judge model, samples and
interests, on this judge. It settles the sample §4l could not judge and starts the series.

**Prediction.** No sample is unevaluable for its length: the longest so far is 15,585
characters. Both arms read within the 17-point floor of §4l (5/24 baseline, 1/22 briefed).

**Falsifier.** A task that read briefed 0/3 in §4k reproduces when briefed, or the briefed arm
worsens beyond the floor against §4l: the subject-words briefing then needs another look
before it ships. For `rate_limiter`, the base rate matters: it has reproduced only when
briefed, 2 of 30 times (§4d, §5), so one reproduction in three samples is plausible by chance
and is read beside that rate. An unevaluable sample with more than 1,000 characters of code
means the `implemented` field still misfires.

**What this cannot settle.** Whether the cut changed §4k's or §4l's verdicts on the samples it
did judge: their code was not kept (the sidecar in #182).

### Result (2026-10-11)

Receipt: `evals/results/ab-20261011-2254.json`, `okl_commit` `5e9b9dd`, `judge_max_chars`
40,000, on the same resolved models as §4k and §4l (`claude-sonnet-4-6` and
`claude-haiku-4-5-20251001`). 48 runs, no failures.

| | baseline | briefed |
|---|---|---|
| §4l (the judge saw the first 8,000 characters) | 5/24 — 21% | 1/22 — 5% |
| §4m (the judge reads the whole submission) | 10/24 — 42% | 1/24 — 4% |

**The instrument held.** No sample was unevaluable. The two longest submissions, both
`rate_limiter` baseline samples at 15,349 and 15,619 characters, were judged whole and judged
clean. Under the old cut they were the shape of the sample §4l lost.

**The falsifier did not trigger.** The one briefed reproduction is `spa_tokens` again (1/3, as
in §4k). No task that read briefed 0/3 in §4k reproduced when briefed, `rate_limiter`
included, and the briefed arm held at 4% against §4l's 5%. On the five tasks the baseline
failed at least once, the briefed arm reproduced 1 of 15. By its pre-registered test, the
subject-words briefing (#178) ships.

**The prediction failed on the baseline, and the judge is not why.** The baseline read 10/24,
21 points above §4l and past the 17-point floor. The wider window cannot explain it: all ten
baseline reproductions are short submissions, 82 to 4,637 characters, which the old
8,000-character judge read whole too. The baseline carries no briefing, so nothing this
branch changed reaches it. Its movement is the generator's own variation between runs, and
it widens the floor: two runs of one 24-sample arm can differ by 21 points. Most of the rise
is `price_tamper`, 3/3 here after 0/3 in §4k and 1/3 in §4l; its 3-sample sonnet baselines
have read 0/3 four times, 1/3 three times and 2/3 five times, so 3/3 is one step past its
usual range. `rate_limiter`'s baseline reproduced for the first time on record. The judge's
reason is that the submission claims a Redis-backed store without showing the code for it,
a call on a claim rather than on code; it can be checked once receipts keep the code (#182).

**For the series this run starts:** its gap, 42% → 4%, is not an effect size. The baseline
sits at the top of its range, and the floor between runs is now at least 21 points. The
direction matches every run before it.

*After the run (2026-10-11):* review of #196 found that "Next.js" alone briefed nothing,
because `next` is on the filler list. A filler word joined by a dot to the next word is now
kept as part of a name. The eight bait tasks' search terms are unchanged by it, so their
briefings are byte-identical and this result stands for the shipped code.

## 4n. PRE-REGISTERED: a relevance floor before the cutoff, and why it is not run live (2026-10-22)

Written before any live run, per §2b, for the change in #259 (issue #257).

**What changed.** The search is an OR of the task's subject words, so a short or generic
prompt filled every slot with records sharing one word with it. A record is now briefed only
when it shares two subject words with the task, or one that is in its title or symptom, or one
when the task has only one word; a record below the floor stays when it links one step to a
kept record; a full window the floor empties widens the fetch, bounded. The instrument is
§4m's: judge window 40,000 characters, same models, same tasks, same interests.

**The tasks at risk, measured first.** The floor can only lower recall, so §2b's third point
is the whole question: which of the eight tasks loses a record it depends on? None, and more
than that, none loses any record at all. On a store seeded from the twelve packs, the twelve
ids each task is briefed are identical with the floor and without it; `exit_code_trust`'s
accepted gap is unchanged. `evals/preflight.py` is green (7 of 8, the accepted gap listed),
and `tests/test_relevance_floor.py::test_the_floor_changes_no_eval_briefing` asserts the
identity, so the day the floor reaches an eval briefing the suite says so.

**Prediction.** Identical briefings give identical arms up to the generator's own movement
between runs (at least 21 points on the baseline, §4m). Nothing this change does can reach
either arm of this instrument.

**Falsifier.** Any difference in the briefed ids between the two pipelines on the eight
tasks: the test above. Were it to fail, a live run on this instrument would be due before
the floor ships to the next release.

**Why no live run.** An A/B whose two arms receive byte-identical briefings measures the
generator's noise and nothing else, at 48 generations and 48 judgments. The change's
effect lies where this instrument cannot look: on prompts that share one word with many
records, which the eval tasks do not (each shares two to ten with its lesson). That effect
is measured by `evals/probe_rephrase.py` (`evals/results/probe-rephrase-20261022.txt`): the
recall rows are unchanged, and six short real prompts return 5, 9, 0, 11, 7 and 11 records
where every one returned twelve. A live run belongs to the briefing-size series (#234),
where a shorter briefing is the variable.

**What this cannot settle.** Whether a briefing that loses a weak but useful record costs
anything downstream: no eval task exercises that case. The hook's one-line notice now says
how many records the floor left out, so the exposure log can be read for it.
## 4o. PRE-REGISTERED: twenty seed records gain a symptom, and the §4b gap closes (2026-10-22)

Written before any live run, per §2b. A corpus change, not a retrieval change, but one the
instrument can see, so it is registered the same way.

**What changed.** Twenty org Rules, Defects and Gates in the seed packs had no `symptom`
(nine of nine in `geospatial-defects`, six of eight in `rag-defects`, four of six in
`dotnet-defects`, one in `dotnet-decisions`). Each now carries one, written in the words a
developer would use when the problem bites, after the lesson's own title, body and fix.
`okl seed` warns when an advice record has none (#258, step 2). Nothing in the retrieval
path changed; the instrument is §4m's.

**The tasks at risk, measured first.** No task loses its governing record: a symptom only
adds words a record can be found by, and all eight are present. One task gains the record it
exists to test. `exit_code_trust`'s lesson (`seed:geospatial-defects:d15`) ranked 54th for
the task's own wording and sat in `evals/preflight.py` as the accepted gap since the §4b
correction; with the symptom "a pipeline or batch step exits 0 and reports success while its
output directory is empty or far smaller than expected" it ranks 4th, the pre-flight reads
8 of 8 with no accepted gap, and the probe's bug-report row reads 3 of 8 (was 2); receipt
`evals/results/probe-rephrase-20261022-symptoms.txt`.

The twelve-record membership of the briefings did change, which a first draft of this
section denied and a review caught: comparing the briefed id sets on two stores seeded from
the packs before and after, `judge_summary` is identical and the other seven each swap
records at the cutoff. Six swap one: the new symptom on `d15` carries words common in task
prompts ("pipeline", "step", "reports", "output"), so it enters the `idor_endpoint` and
`price_tamper` briefings in place of a dotnet decision, and elsewhere one peripheral record
replaces another (`react_fetch`, `spa_tokens`, `rate_limiter`, `ci_linter`). `exit_code_trust`
swaps three, gaining its own lesson, `nc_arch_reviewer` and `qz_crosstab` for a naming rule, a
testing rule and the unpinned-linter rule. None of the records that left is a task's
governing record; whether a briefing that gains an off-topic defect is any worse is what the
floor (#259) exists to keep small, and this corpus change is a reason to revisit the probe
with it on.

**Prediction.** On the next run of this instrument, `exit_code_trust` briefed reproductions
fall toward 0 of 3; every earlier briefed sample of that task was the briefing without its
lesson. The other seven tasks and the baseline arm read within the floor of §4m.

**Falsifier.** `exit_code_trust` reproduces when briefed with its lesson present in the
briefing (the receipt's briefing text shows it), at the same rate as before: the lesson then
does not prevent the defect it describes, and its fix text needs another look before the
symptom pass counts as an improvement.

**What this cannot settle.** Whether the other nineteen symptoms help: no eval task
exercises them, and the probe's bug-report row holds only the eight task lessons, so it
measures the one evaluated lesson and says nothing about the other nineteen. Their measure
would be rephrased prompts for records outside the eval set, which the probe does not yet
carry.

### Result (2026-10-22)

Receipt: `evals/results/ab-20261022-0455.json`. 48 runs, no failures, `judge_max_chars`
40,000, interests unfiltered. Generator `claude -p --model sonnet`, judge `--model haiku`.

| | baseline | briefed |
|---|---|---|
| this run | 6/24 — 25% | 1/24 — 4% |

Per task: `spa_tokens` baseline 3/3, briefed 1/3 (the one briefed reproduction, as in §4k
and §4m); `ci_linter` baseline 3/3, briefed 0/3; every other task 0/3 in both arms,
`exit_code_trust` included.

**The prediction's object did not occur.** `exit_code_trust`'s baseline read 0/3 here, so
its briefed 0/3 shows nothing about the lesson: there was no reproduction to prevent. The
task has reproduced unbriefed before, so the prediction stands for the next run that
produces one. **The falsifier did not trigger**: no briefed sample of that task reproduced.

**Two things make this run its own series, not a point in §4m's.** First, the models
behind the aliases changed: the receipt resolves the generator to `claude-sonnet-5-5` (with
`claude-haiku-5-5` as the CLI's helper model) and the judge to `claude-haiku-5-5`, where
every run from §4k to §4m resolved to `claude-sonnet-4-6` and `claude-haiku-4-5`. By §2b a
new generator or judge starts a new series; the 6/24 baseline is this pair's first reading
and its own floor is unknown until a second run. The judge-is-generator guard passed as the
harness defines it (equal sets, a helper model beside the main one is not the judge grading
itself), and that definition is the right place to look if a reader doubts it.

Second, a provenance fault in how the run was made, recorded here rather than tidied. The
harness renders the briefed arm from the working tree (`python -m okl` on `src/`) and stamps
`okl_commit` from the tree's HEAD when it writes the receipt. The run was started on this
branch at `acdcb99`, and the tree was switched to the relevance-floor branch (#259) while
it ran, to answer that PR's review; the receipt therefore names `b54e075`, that branch's
head, and the later samples were briefed by code carrying the floor. The two codes brief the
eight eval tasks identically (§4n's `test_the_floor_changes_no_eval_briefing`, and the
store was constant), so the briefed input did not change mid-run; but a receipt should not
need that argument. A lesson is recorded, and the harness is to record HEAD at start and
refuse to write a usable receipt when it has moved.

## 5. Findings

1. **The briefing works, in both tiers.** Sonnet: 33% → 4%. Haiku: 38% → 12%. Every
   task the sonnet baseline failed was fully prevented except one residual
   (judge_summary 1/3). *Note, 2026-10-10:* "fully prevented" held in no 3-sample run
   after that one. spa_tokens is reduced, not prevented: 35/43 → 20/43 (81% → 47%) across
   the 16 receipts that include it, and 29/37 → 15/37 on the documented instrument
   (sonnet generator, haiku judge). The 15 include §4j's run, where it read 0/2 → 0/3,
   §4k's, 1/3 → 1/3, §4l's, 1/3 → 1/2, and §4m's, 2/3 → 1/3, and §4o's, 3/3 → 1/3 (updated 2026-10-22).
2. **Cross-model headline: briefed haiku (12%) beat unbriefed sonnet (33%)** on the
   identical task set — a briefed budget model reproduced org-known defect classes at
   roughly a third the rate of an unbriefed frontier model. One haiku run, never
   repeated, and judged by sonnet where the sonnet runs were judged by haiku: a
   direction, not a ratio.
3. **Context bought more than capability.** Upgrading the model (haiku→sonnet baseline)
   removed 5 points of defect reproduction; adding the briefing removed 26 (haiku) and
   29 (sonnet).
4. **Capability still matters at execution time.** Briefed sonnet (4%) beat briefed
   haiku (12%): haiku read the token-storage lesson and still put tokens in web storage
   2/3 times — knowing the rule and executing the alternative are different skills.
   *Note, 2026-10-10:* findings 3 and 4 compare tiers through the one haiku run, which
   sonnet judged. Their 5- and 8-point gaps are inside the §2b noise floor, so only the
   within-tier briefing effects (26 and 29 points) are measured.
5. **ci_linter is the cross-repo thesis in one row:** 3/3 reproduced unaided in BOTH
   tiers, 0/3 briefed in both — prevented by a lesson recorded in a different repo
   weeks earlier.
6. **Anomaly, retained:** briefed haiku reproduced rate_limiter 1/3 where its baseline
   was 0/3 — a briefed run worse than baseline on one task. Small-sample noise or
   briefing-as-distraction; it stays in the data.
7. **The pooled figure quoted in the launch posts (added 2026-10-12).** Over the eight
   committed runs on the documented instrument (sonnet generator, haiku judge, eight tasks
   with three samples per arm) from §4 through §4i, 78 of 186 unbriefed attempts
   reproduced a known defect (42%) against 13 of 188 briefed ones (7%). The eight receipts:
   `ab-20260830-0003`, `ab-20260901-0133`, `ab-20260901-1238`, `ab-20260902-0538`,
   `ab-20260903-0157`, `ab-20260903-1214`, `ab-20260903-1323`, `ab-20260926-0528`.
   Denominators fall short of 192 because failed and unevaluable samples are left out.
   The pool keeps §4d's run (`ab-20260902-0538`), whose retrieval change was reverted:
   its briefed arm read 3 of 23, so keeping it raises the briefed rate. Without it the
   pool reads 68 of 164 (41%) against 10 of 165 (6%). It leaves out §4f (judged by opus,
   not the documented instrument) and every run from §4j on, because each of those
   started a new series (§4j's unbriefed arm moved 26 points with nothing changed; §4k
   and §4m changed the instrument). Pooling all thirteen comparable receipts, those
   included, reads 108 of 304 (36%) against 17 of 305 (6%), leaving out §4j's plan-only
   sample as §4j itself does. Read it with §6: one-shot
   code on bait tasks written to invite defects the store already knew about, a small
   n, and nothing about code quality improving over time.

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
  briefing text reaches the model via the fail-closed UserPromptSubmit hook inside an agentic
  session (it was a PreToolUse hook when these runs were made; see §8); here it was
  prepended to a one-shot prompt. The briefing *content* is identical; the delivery layer
  (hook firing, binary resolution, fail-closed blocking) is exercised by the test suite
  and observed live, but not by this experiment. Likewise no Stop hook, gates, or verify
  step were in the loop — the experiment isolates the briefing variable and measures
  generation only, not the full enforced loop end to end.
- **Both models are one vendor's; "budget model" ≈ haiku.** The local-model version of
  the claim (via `GENERATOR_CMD="ollama run ..."`) is unmeasured — the harness supports
  it; nobody has run it yet.
- **The corpus changed on 2026-10-04: every run above briefed from a smaller one.** Adding
  `seed/python-canon.json` (#122) took the bundled seed corpus from 161 records to 178. In
  this repo's store (the one the harness briefs from, with `--interests ""`), 4 of the 8
  tasks' briefings now include 1-3 Python-canon lessons: `judge_summary` and `ci_linter` 3
  each, `spa_tokens` and `rate_limiter` 1 each. The briefed arm has changed, so a run after
  this date is not comparable to the receipts above without saying so. `evals/preflight.py`
  still passes: each task still receives the rule it tests (7 of 8, plus the accepted
  `exit_code_trust` gap).

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

## 10. Fresh-install end-to-end run (2026-09-26): the loop from a wheel

§8 tested delivery a month ago, against the shared service, before the rename, the hook
anchoring, fingerprints, the failed-command candidates and the each-record-once briefing.
This run repeats it from what a new user gets: a wheel built off `main` (`e3be24c`),
installed into a clean environment, in a scratch repo with no okl history, local store.
Receipt: [`results/e2e-20260926/`](results/e2e-20260926/). n=1 per arm; a delivery check,
not a measurement.

| surface | result |
|---|---|
| briefing reaches the model | yes — `hook_success` attachment in the transcript holds it; briefed arm pinned `ruff==0.9.0` citing two lessons, control wrote unpinned `ruff check .` |
| Stop question | fired once, answered honestly; no failed commands, so no candidates listed |
| record → verify → snapshot → drift gate | 0 after verify, 1 after a governed edit |
| shipped CI drift step, run as its own shell | 0, from the committed snapshot |
| `doctor`, re-`init`, `--uninstall --dry-run` | clean; nothing clobbered; dry run wrote nothing |
| `OKL_DISABLED_HOOKS` inside a live session | both hooks stayed silent |

**Finding — `claude -p` prints the answer to the Stop question, not the task.** Print mode
emits the final message only; a blocked stop makes the reply to "what did we learn?" the
final message. The user's YAML survived only in the transcript. No documented hook input or
environment variable distinguishes print mode, and the one undocumented candidate
(`entrypoint`) is inherited from the parent process, so a nested `-p` run reports the
parent's value. The honest resolution is the documented switch: headless callers set
`OKL_DISABLED_HOOKS=encode`, proven in this run. The harness never hit this because it
runs generators in a clean room (§8's lesson).

**Finding — stack-keyed pack recommendation** (#54): a Python repo was told one 2-record
pack fits it; the pack holding the rule this run shows working was unmarked because it
names the stack it was found on.

Two false starts cost no model calls and are recorded so the next run skips them: macOS
has no `timeout`, and `claude -p` wants the prompt on stdin.

## 9. Reproduction

```bash
python3 evals/ab_harness.py --samples 3                       # sonnet gen, haiku judge
GENERATOR_CMD="claude -p --model haiku" \
JUDGE_CMD="claude -p --model sonnet" \
python3 evals/ab_harness.py --samples 3                       # budget-tier arm
```

Wall-clock for the receipts above: ~36 min (sonnet run), ~21 min (haiku run).
