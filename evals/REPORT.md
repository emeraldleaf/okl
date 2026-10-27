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

### The noise floor is at least 21 points, and it is not optional

The baseline arm receives no briefing and has never changed. Across the first four sonnet
runs it read 33%, 42%, 50%, 45%, and that 17-point spread was the floor this section first
set. The same arm has since moved further with nothing changed: 21 points between two runs
of one instrument (§4m, 21% to 42%) and 26 points across the §4j boundary (43% to 17%),
which §4j attributes to the generator and treats as the start of a new series. **The spread
on an arm where nothing moved is measurement noise**, so:

- A difference smaller than ~21 points, in either arm, is **not interpretable**. The
  sections written before §4m say 17, which was the floor as measured when they were written.
- The pooled briefing effect (42% against 7%, §5 finding 7) clears it; a single run's gap
  need not (§4j's 17% against 0% does not), which is why the headline is the pool and not
  one run.
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
haiku judge, as the aliases name them) the pooled figure is 29/37 → 15/37 across its
fourteen receipts, §4j's, §4k's, §4l's, §4m's and §4o's included; §4o's aliases resolved to
different models and start their own series (§4o), so on the earlier models alone the figure
is 26/34 → 14/34 across thirteen (updated 2026-10-22): reduced, not prevented.

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
before the run. Every record's content therefore survives the new layout; the pre-flight
says nothing about the rendered briefings being identical, and they are not, since the
layout is the change.

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

*Added 2026-10-22, revised 2026-10-23.* This section calls the layout change a new series,
and from 2026-10-12 to 2026-10-23 §5 finding 7 pooled this run (`ab-20260926-0528`) with
§4 through §4h all the same. The pre-flight above shows that every record's content
survived the new layout, not that the briefings were identical, and the rule this report
keeps is that a changed treatment starts a new series; finding 7 now reports this run
beside the pool, with the figure the launch posts quoted, rather than in it.


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

**What that identity covers.** Eight authored prompts, each sharing three to ten subject
words with its governing lesson (`evals/results/probe-rephrase-20261022-symptoms.txt`,
section C). It says nothing about a prompt whose only link to a lesson is one identifier in
the lesson's body, which the floor drops by design and an independent verification on
2026-10-22 reproduced on three records; #263 tracks that rule.

**Prediction.** Identical briefings give identical arms up to the generator's own movement
between runs (at least 21 points on the baseline, §4m). Nothing this change does can reach
either arm of this instrument.

**Falsifier.** Any difference in the briefed ids between the two pipelines on the eight
tasks: the test above. Were it to fail, a live run on this instrument would be due before
the floor ships to the next release.

**Why no live run.** An A/B whose two arms receive byte-identical briefings measures the
generator's noise and nothing else, at 48 generations and 48 judgments. The change's
effect lies where this instrument cannot look: on prompts that share one word with many
records, which the eval tasks do not (each shares three to ten with its lesson). That effect
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

## 4p. PRE-REGISTERED: every org advice record gains aliases, measured by the probe (2026-10-23)

Written before any measurement, per §2b, for #258's second vectorless arm.

**What changed.** Each of the 136 org-scoped Rules, Defects and Gates in the seed packs now
carries `aliases`: two to eight short phrases in the words a developer uses when the lesson
bites or when asking for the work ("logged out on refresh", "query in a loop", "CI failed
with no code change"). The field is indexed with the symptom at its weight, and one alias
word counts as the record's subject for the relevance floor (#257). The phrases were written
from each record's title, symptom and body, not from any prompt that had missed; the author
had read the probe's own rephrasings, which is the bias the held-out set below exists to
bound.

**The instrument.** No model. `evals/probe_rephrase.py`, with the floor on, on a store seeded
from the twelve packs with okl's configured interests, as in §4o's receipt. Two recall tables:
the probe's authored rephrasings (seen by the alias author), and a held-out set
(`evals/heldout_variants.json`) written on 2026-10-23 by an agent given only the id and task
fields of `evals/tasks.jsonl`, which opened no pack, receipt or probe code; the alias author
read it only after the aliases were written. The six short real prompts measure precision as
before.

**The tasks at risk, measured first.** Aliases add terms, so no record can lose a match; but
BM25 normalises by the record's length, so a record that was marginal for its task can lose
rank to records whose aliases match. `exit_code_trust` is the one at risk: its lesson ranked
4th after §4o, from 54th before. `evals/preflight.py` on a store seeded from the new packs,
and the eight tasks' briefed id sets compared against a store seeded from the packs at
`origin/main`, settle it before any row is read.

**Prediction.** Authored and ticket rows stay 8 of 8. The probe's paraphrase row (0 of 8) and
bug-report row (3 of 8) rise; by how much is the measurement. On the held-out set no row
reads lower than the probe's corresponding row did before this change (ticket 8, paraphrase
0, bug-report 3). The eight eval briefings keep every record they had; the six precision
prompts return no more records than in §4n (5, 9, 0, 11, 7, 11) beyond what an alias
legitimately matches, and none returns twelve.

**Falsifier.** A task's governing lesson leaves its briefing (pre-flight red, or a removed id
in the comparison); a held-out row below its pre-change probe row; a precision prompt back
to twelve. Any of these and the aliases that caused it are revised, or the field's weight
drops, before this ships.

**What this cannot settle.** Whether the briefed arm's behaviour changes: the A/B's authored
tasks already receive their lessons, so a live run would measure generator noise (§4n). The
arm that would show it is a run on rephrased tasks, which belongs to #258's third step with
the hybrid index, so the two arms are measured on one instrument.

**First pass (2026-10-23, recorded, not shipped).** Receipt
`evals/results/probe-rephrase-20261023-aliases-pass1.txt`. Pre-flight green and every
governing lesson kept. The probe's bug-report row rose from 3 to 8 of 8 and its paraphrase
row from 0 to 1; the held-out rows read ticket 7, paraphrase 2, bug-report 5. Two
falsifiers fired. The sixth precision prompt returned twelve records again, nine of them
sharing one word with it ("search", in aliases such as "throttle search" and "count with
similarity search"), and every eval briefing swapped one to four records at its margin
(`r_202_long_running` entered the IDOR briefing on "endpoint"). The cause is the rule as
pre-registered: one alias word made a record on-subject, and an alias is a phrase, so its
common words ("search", "endpoint", "tests") did exactly what the floor exists to stop.
Revision, per the falsifier's remedy: aliases count toward the two shared words, and a
single alias word is the record's subject only when it is a one-word alias matched whole
("PKCE", "I001", "throttling"). The result below is of the revised rule, on the same
aliases.

### Result (2026-10-23, revised rule)

Receipts: `evals/results/probe-rephrase-20261023-aliases.txt` (the probe on the live store,
313 records) and `evals/results/seed-compare-20261023-aliases.txt`
(`evals/compare_seed_briefings.py`: two stores seeded from the packs at `origin/main` and from
this tree, so the aliases are the only difference between them).

| of 8 tasks | before | after |
|---|---|---|
| held-out ticket | 6 | 7 |
| held-out paraphrase | 2 | 3 |
| held-out bug report | 5 | 5 |
| probe's own bug report (seen by the author) | 3 | 8 |
| probe's own paraphrase (seen by the author) | 0 | 1 |
| six precision prompts, seeded store (records returned) | 3, 8, 0, 4, 1, 2 | 3, 8, 0, 4, 1, 2 |

**What held.** Every governing lesson is briefed on both sides; pre-flight is green on a
store seeded from the new packs; the authored and ticket rows stay 8 of 8. On the seeded
stores the six precision prompts return exactly what they returned before, so the aliases
cost no precision there. No held-out row fell.

**What did not.** The prediction that each briefing keeps every record it had was wrong: on
all eight tasks, one to three records at the margin left and as many arrived
(`rxc_effects_discipline` and `d15` left the IDOR briefing; `r_202_long_running` and
`rx_tokens_localstorage` arrived). Each arrival shares two or more words with its task,
through its aliases and body, and outranks a record that shared as few: BM25 reordering from
added indexed text, which any edit to a record's text also does, showing at the margin of a
twelve-record briefing. The falsifier's "removed id" clause fired on it; the clause was
written for the governing lesson, which it did not touch. The pre-registered comparison of
the held-out rows against the probe's own pre-change rows was also the wrong baseline, since
they are different sentences; the comparison tool gives the held-out set its own before, and
that is the table above. The probe's precision table on the live store reads 4, 9, 0, 11,
7, 12 against §4n's 5, 9, 0, 11, 7, 11: the twelfth record on the sixth prompt is a lesson
recorded in the live store since §4n whose title says "search", and the seeded comparison,
where the store does not move, shows the aliases added nothing to that prompt.

**Reading.** The honest effect is the held-out column: one more task found from a ticket and
one more from a paraphrase, none from a bug report, on wording the alias author had not seen.
The probe's own bug-report row rising from 3 to 8 is an upper bound, since the author had
read those eight sentences; it says the field can carry a developer's words to a lesson once
someone writes them, which is this arm's whole premise and its whole cost. Paraphrases that
avoid every noun stay out of a lexical index's reach, 3 of 8 held-out and 1 of 8 authored:
that is the case for #258's third step, to be measured on this same held-out set.

**What ships.** The field, the revised floor rule and the 136 alias lines. The ADR's
amendment waits for the third step, so one amendment records both vectorless arms and the
hybrid measurement together.

## 4q. PRE-REGISTERED: a local embedding beside the full-text search, fused and measured (2026-10-23)

Written before any hybrid row was read, per §2b, for #258's third step. The flat-retrieval
ADR (`docs/decisions/2026-07-17-flat-retrieval-until-scale.md`) says what to do when its
vocabulary-mismatch trigger fires: add an embedding index beside FTS, fuse by reciprocal
rank, measure against FTS-only on the same tasks, adopt only if it wins.

**What changed.** `okl embed` writes one vector per record into the store from a local static
embedding model (`minishlab/potion-retrieval-32M`: Model2Vec, 249 MB on disk, 512 dimensions;
its model card gives MTEB retrieval 35.1 against all-MiniLM-L6-v2's 42.9, at well under a
millisecond per text). `okl check --hybrid` fetches the nearest records by cosine beside the
full-text candidates and fuses the two orders: `rrf` sums reciprocal ranks (k = 60); `linear`
is a convex combination (alpha 0.5, untuned) of a rank-normalised full-text score and the
min-max-normalised cosine, the family Bruch, Gai and Ingber (ACM TOIS 2023) found to beat RRF
once its one weight is tuned. A candidate whose cosine reaches 0.25 passes the relevance floor
whatever words it shares; the line was set from one probe before this section was written (a
held-out paraphrase of its lesson scored 0.31, an unrelated bug report 0.16, chat filler 0.12)
and is a parameter this measurement may move, in which case the first pass is recorded as
§4p's was. Off by default; at check time the model is loaded from the local cache only, so
the hook path never reaches the network, and without the extra, the model or the vectors the
briefing is the full-text one and says so.

**The instrument.** `evals/probe_rephrase.py --hybrid off|rrf|linear`, floor on, on the live
store (313 records, every one embedded), with okl's configured interests: three receipts, one
per mode. The rows: the authored eval tasks, the probe's own rephrasings, the held-out set
(`evals/heldout_variants.json`), and the six precision prompts. No paid model call; the
embedding runs on this machine.

**The tasks at risk, measured first.** Fusion reorders candidates, so a governing lesson that
full-text ranks high can fall; the authored row must stay 8 of 8 in each mode
(`exit_code_trust`, 4th by full-text, is the one to watch). Wall time: a check took 0.09 s
full-text and 0.62 s hybrid before this section was written, most of it loading the model;
the hook's budget is 30 s.

**Prediction.** The held-out paraphrase row rises from 3 of 8 in both modes; the held-out
bug-report row (5) and ticket row (7) do not fall; the probe's own paraphrase row rises from
1 of 8. Between the modes, no prediction: the literature favours the convex combination once
tuned, and alpha is not tuned here. On the six precision prompts the semantic arm admits
records by meaning, so the counts may rise; the falsifier is below.

**Falsifier.** An authored task's governing lesson leaves its briefing in either mode; a
held-out row below its full-text value; a precision prompt returning twelve records, or more
than three above its full-text count. Any of these and the subject line (0.25) rises, or the
arm stays off by default with the measurement recorded, before the ADR is amended.

**What this cannot settle.** Whether a briefed arm behaves differently with the semantic arm
on. The A/B's authored tasks already receive their lessons (§4n); the live run that could show
it is one on rephrased tasks, a new instrument with its own pre-registration, and the held-out
set here is its candidate task list.

**First pass (2026-10-23, recorded, not shipped).** Receipts
`evals/results/probe-rephrase-20261023-hybrid-{off,rrf,linear}.txt`, at the 0.25 line. The
full-text run on this store reads held-out paraphrase 2 of 8 (the pre-registration's "3" was
the seeded-store figure of §4p; the live store differs by its recorded lessons). Linear:
authored 8, the probe's own paraphrase 1 → 3, bug report 8; held-out ticket 7 → 7,
paraphrase 2 → 4, bug report 5 → 5. RRF: the probe's own ticket row fell 8 → 7, held-out
ticket 7 → 6 and bug report 5 → 4. In both modes three of the six precision prompts returned
twelve records (full-text: 9, 11, 7, 12), so the falsifier fired for both, and the held-out
clause fired for RRF. Two causes, read from the receipts. The line was too low: "ok do the
updates and update my site and the writing section" has 31 records at or above 0.25 and
10 at 0.30. And the fused window is up to twice the full-text one, so more records reached
the floor's one-word title-or-symptom rule, which was written for a full-text window.
Revision: a record only the semantic arm found is on the subject only by meaning (the word
rules stay with the full-text candidates), and the line is chosen by a grid over 0.25, 0.30,
0.35 and 0.40 in both modes, by a rule written before the grid ran: the lowest line at which
no precision prompt returns twelve and no held-out row is below its full-text value; between
modes, the higher held-out paraphrase row, ties to RRF as the ADR's named default. The grid
is `evals/hybrid_grid.py`, its receipt `evals/results/hybrid-grid-20261023.txt`.

### Result (2026-10-23, second pass, line 0.40)

Receipts: `evals/results/hybrid-grid-20261023.txt` (the grid) and
`evals/results/probe-rephrase-20261023-hybrid-{rrf,linear}-040.txt` (the probe at the chosen
line); full-text is `probe-rephrase-20261023-hybrid-off.txt`.

| of 8 tasks | full-text | linear 0.40 | rrf 0.40 |
|---|---|---|---|
| authored | 8 | 8 | 8 |
| probe's own ticket / paraphrase / bug report | 8 / 1 / 8 | 8 / 2 / 8 | 7 / 1 / 8 |
| held-out ticket / paraphrase / bug report | 7 / 2 / 5 | 7 / 3 / 5 | 6 / 4 / 4 |
| six precision prompts, records returned | 4, 9, 0, 11, 7, 12 | 5, 9, 0, 12, 7, 12 | 5, 9, 0, 12, 7, 12 |

**The rule's verdict.** No cell satisfies the rule as written: at every line two prompts
touch twelve, and the sixth already returns twelve on full-text (a lesson recorded in the
live store since §4n whose title says "search"), so the absolute clause was unattainable on
this store and should have been relative. By the relative clause, linear at 0.40 adds one
record to two prompts and none to the rest; RRF fails the held-out clause at every line (its
ticket and bug-report rows fall, because reciprocal ranks let the semantic arm's order
displace full-text's on tasks full-text already had right). Linear at 0.40 is therefore the
arm's configuration when it is on, and the arm does not become the default.

**What the arm buys.** One more held-out paraphrase found of eight (2 → 3) and one more of
the probe's own (1 → 2); nothing on tickets or bug reports; one record more on two of six
short prompts; 0.8 s per prompt for the model load (the search itself is under a millisecond
with numpy) and a 249 MB model on disk. The two vectorless arms bought more: symptoms took the
probe's own bug-report row from 2 to 3 of 8 (§4o), and aliases took it from 3 to 8 of 8 and
added one held-out ticket and one held-out paraphrase (§4p; corrected 2026-10-26, this sentence
had given the alias gain to symptoms). The static model's cosines sit in a narrow band (true pairs 0.30
to 0.55, chat filler up to 0.42), which is why no line separates meaning from filler cleanly;
a stronger local model (bge-small through ONNX at about 130 MB) or a reranker over the fused
top 36 is the next experiment, on this same held-out set, before the semantic arm can earn
the default.

**Prediction check.** The held-out paraphrase row rose in both modes, as predicted; held-out
ticket and bug report held under linear and fell under RRF, which was not predicted; the
probe's own paraphrase row rose under linear, as predicted; precision rose by one on two
prompts, which the falsifier allowed. The pre-registration's "about 30 MB" was another model's
figure: this one is 249 MB on disk.

**What ships.** `okl embed`; `okl check --hybrid` (linear fusion at the 0.40 line when the
flag is bare; `rrf` stays selectable for measurement), off by default; a numpy matrix product
over every vector that holds to roughly 100,000 of them (under a millisecond at 10,000, 3 ms
at 50,000, plus 14 and 49 ms to read them; `okl.semantic`'s docstring has the measurements
and the next tier); and the ADR amendment. The hook never reaches the network for any of it.

## 4r. PRE-REGISTERED: the index arm, measured where it can act (2026-10-23)

Written before the run, per §2b, for #258's first vectorless arm, on a new instrument.

**The question.** §4q measured retrieval as recall: is the governing lesson among the twelve
briefed? The index arm asks something the probe cannot: when the briefing names every other
lesson in scope by id and title, does the agent fetch the one it needs? The one eval cited
on #258 scored an always-present index at 100% where loading on demand scored about half;
that was a different setup (skills, not lessons), and nothing has measured it for okl.

**The instrument, and why it is a new series.** The generator is agentic: `claude -p` may
run one tool, `okl show <id>` (`--allowedTools "Bash(okl show:*)"`), against the store this
harness reads, through an `okl` shim on its PATH that logs every invocation. The judge is
the §4m judge, haiku, unchanged. The tasks are the 24 held-out rephrasings
(`evals/heldout_tasks.jsonl`, built by `evals/make_heldout_tasks.py` from the blind set),
each judged by its authored task's signal. Three arms, three samples each: `baseline` (no
briefing), `briefed` (the twelve-record briefing), `indexed` (the briefing plus every other
live lesson in scope as `- [id] title`, with one line telling the agent to read a relevant
one with `okl show` before writing code). An agentic generator on rephrased tasks is a
different instrument from §4 through §4o, so nothing here pools with them. The index costs
about 120 characters per lesson in scope; the receipt stamps the size it added.

**The tasks at risk, measured first.** The held-out briefings hold the governing lesson in
7, 3 and 5 of 8 tasks (ticket, paraphrase, bug report; §4p). The indexed briefing contains it
in all 24, by construction: where the ordinary briefing already selected it, the index does
not repeat it, and where the briefing omitted it, the index names it. The measure is whether
being named is enough.

**Predictions.** In the indexed arm the generator fetches the governing lesson in at least a
third of samples and in a majority of the paraphrase samples, where the briefing lacks it;
in the briefed arm it fetches nothing (nothing tells it a store exists). Defect reproduction
in the indexed arm is at or below the briefed arm's; the baseline arm reproduces most.

**Falsifiers.** The governing lesson is fetched in under 10% of indexed samples (the agent
does not use an index of this shape); or the indexed arm reproduces more defects than the
briefed arm by more than the noise the baseline arm shows between its own samples (the
index distracts); or the agent fetches so many lessons that the cost reads as a second
briefing (a median above three fetches per sample). Any of these and the arm stays an
experiment; the hook does not gain an index.

**Cost.** 72 agentic generations and 72 judgments per arm; the tree is not switched while
the run is in progress, and the receipt refuses if it moved (§4o).

**What this cannot settle.** Whether an index helps on a real codebase's prompts; these are
24 rephrasings of eight bait tasks. Whether a reranker (the third arm the plan names) does
better; it is not built, and it measures on the same tasks when it is.

### Result (2026-10-23)

Receipt: `evals/results/ab-20261023-1303.json`, `okl_commit` 96da803 at start and at end.
216 runs, 18 failures (8%; 15 with no implementation to judge, most of them bug-report prompts
answered in prose, and 3 errors): usable. The index added 38,608 characters to each prompt.
Median generator time per sample: baseline 25 s, briefed 32 s, indexed 36 s. The gate ran on
the authored tasks, as the harness then did; which held-out briefings lacked their lesson is
known only through §4p's probe, and the harness now gates the task file it runs.

| arm | reproduced | fetched the governing lesson | fetched anything |
|---|---|---|---|
| baseline | 19 of 61 (31%) | 0 of 61 | 0 of 61 |
| briefed | 5 of 66 (8%) | 0 of 66 | 0 of 66 |
| indexed | 2 of 71 (3%) | 1 of 71 | 1 of 71 |

By variant, reproduced (baseline, briefed, indexed): ticket 13/22, 0/22, 0/24; paraphrase
4/23, 4/24, 2/24; bug report 2/16, 1/20, 0/23.

**The falsifier fired.** The agent fetched the governing lesson once in 71 indexed samples
(`idor_endpoint/bug-report`, sample 2) and nothing else at all, far under the 10% line; the
briefed and baseline arms fetched nothing, as predicted. Given about 300 titles and an
instruction to read a relevant one before writing code, a one-shot code generator does not
go and read. The prediction that it would fetch in a third of samples, and in most
paraphrase samples, was wrong by an order of magnitude.

**What the arm did instead.** It reproduced fewer defects than the briefed arm (2 of 71
against 5 of 66) without fetching, so the fetch mechanism is not the cause. Two readings
remain, and this run cannot separate them: noise (a 5-point gap, on a new instrument with no
second run to set its floor), or the index text acting as a second briefing, since a title
such as "Access tokens in localStorage are XSS-exfiltratable" carries the lesson. The per-task
rows read the same way on both: `spa_tokens/paraphrase` reproduced 3/3, 3/3 and 2/3 across the
arms, so a lesson every arm named, by title or in full, did not stop the defect on that
wording; the briefing's gain over the baseline sits in the ticket row (13/22 to 0/22), where
the briefing already holds the lesson.

**Reading, against the pre-registration.** The arm's premise, that an agent fetches by id
what an index names, does not hold for this generator and this prompt; the arm stays an
experiment and the hook gains no index. The cost is real (38 KB a prompt, 4 s a sample) and
the benefit, if any, is the titles-as-briefing effect, which is a different and cheaper design
to test: the titles of the records the floor left out, appended to the briefing. The
generator prompt's "output only the code" was part of the treatment as pre-registered and
plausibly suppresses tool use; a variant that invites it, or exposes the lesson through an
MCP tool rather than a shell command, is a new pre-registration, not a reinterpretation of
this one.

**What ships.** The harness's arms, tool shim and fetch records, so the next variant costs a
flag; the held-out task file; and `okl check --index` as the measured treatment, off
everywhere. Nothing in the hook changes.

## 4s. PRE-REGISTERED: near misses appended to the briefing, settled by pre-flight (2026-10-23)

Written per §2b for the cheaper design §4r pointed at: instead of every lesson in scope (38 KB),
append only the records that matched the task and were left out, by the floor or the cutoff,
as id and title, at most twelve lines (`okl check --near-misses`, about 1.8 KB). The premise
was that a title can carry its lesson, so naming the near misses might do what the index did
not, at a twentieth of the cost.

**The pre-flight, run before any model.** For each of the 24 held-out tasks, where does the
governing lesson land with the flag on: briefed, in the near-miss list, or neither?

| where the governing lesson lands | tasks |
|---|---|
| in the briefing already | 14 |
| in the near-miss list | 3 (`price_tamper/paraphrase`, `price_tamper/bug-report`, `rate_limiter/paraphrase`) |
| neither | 7 |

The seven are not in the full-text candidate window at all: each shares zero or one common
word with its task (`add`, `url`, `request`, `runs`), so no list drawn from that window can
name them. The three the list would name are tasks on which §4r's briefed arm reproduced
nothing (0 of 3, 0 of 1, 0 of 3), so a live run could not show a gain on them, only noise.

**Decision.** No live run: the instrument cannot measure the arm, which is what the
pre-flight exists to say (§4b, §4d). The flag ships as an optional, unmeasured convenience
for a reader who wants to see what else matched, off by default, and nothing in the hook
changes. The finding that matters is the seven: the gap on paraphrases is a candidate-window
problem, not a ranking problem, and a reranker over the full-text window alone cannot reach
them either. §4t measures the fused window for that reason.
## 4t. PRE-REGISTERED: a cross-encoder second stage over the fused candidates (2026-10-23)

Written before the run, per §2b, for #258's second stage, on the probe (§4p's instrument).

**The question.** §4q left the semantic arm optional: it found one more held-out paraphrase
and nothing else, because a static embedding's cosines sit in a band too narrow to separate
the governing lesson from filler. The standard second stage reads the task and each candidate
together: a cross-encoder scores the pair, a sharper question than either arm's independent
score. Does reordering the fused candidates by that score put the governing lesson among the
twelve where the first stage ranked it past them, without displacing it where the first stage
had it right, at a latency a hook can carry?

**The design.** `check` fetches three times its limit per arm (36 full-text and 36 by cosine,
fused by the §4q linear rule). The cross-encoder scores the first 24 fused candidates against
a short text per record (title, symptom, aliases) and reorders them; the tail keeps its order;
the scope gates, the §4n relevance floor and the cutoff are unchanged and run after. The score
is an order, not a line: on the selection set below the governing lesson scored from −11.4 to
+8.2 (medians −5.8 authored, −3.3 ticket, −8.6 paraphrase, −1.1 bug report) while the six chat
prompts' best candidate peaked at −4.0, so no absolute score separates the two, and the floor
still admits or drops. A candidate only the semantic arm returned still needs its cosine at
0.40 to pass the floor; a reranker rank does not admit it. Off by default: `okl check
--rerank`, `"rerank": true` in the config or `OKL_RERANK=1`; the model comes from the local
cache or the stage says why it did not run.

**How the model was chosen, and on what.** Five local cross-encoders fastembed ships were run
on a selection set that is not the held-out set: the probe's own rephrasings and the eight
authored tasks, over fused windows of 18 and 36 per arm, one process per model (receipt
`evals/results/rerank-select-20261023.txt`, script `evals/rerank_select.py`). At the smaller
window `Xenova/ms-marco-MiniLM-L-6-v2` kept all eight authored lessons in the top twelve
(ranks 2, 8, 3, 1, 3, 3, 1, 12), found 7 tickets, 5 paraphrases and 8 bug reports of 8, at
612 ms a task and a 0.1 s load from cache. MiniLM-L12, bge-reranker-v2-m3 (int8) and
bge-reranker-base each found one more of the probe's own paraphrases and lost one or two
authored lessons, at 2.6, 9 and 12 times the time (and 3.5, 9.8 and 18.4 s to load); jina
turbo lost an authored lesson and a bug report. The larger window hurt every model: given
more filler, each ranked some of it ahead of a governing lesson (MiniLM-L6 authored 8 → 6).
The shipped pool, the first 24 of the fused list from the 36-per-arm fetch, is therefore the
smaller side of the fetch, between the two windows measured. Short text was chosen in the
first spike (`evals/rerank_spike.py`, receipts `rerank-spike-20261023-*.txt`): the record's
full text slowed scoring about five-fold (4.4 s a task) and found nothing more. The current
best small cross-encoders by published benchmark (Ettin-reranker, Qwen3-Reranker) are not in
fastembed's registry and were not run; they are the next spike if this one moves a row.

**The embedder under it, checked at the same time.** Five contextual dense models were scored
on the same selection set as the semantic arm alone (receipt
`evals/results/embedder-select-20261023.txt`, script `evals/embedder_select.py`): none found
more held-out-shaped paraphrases than the static model (5 of 8 for every model), the best of
them found two more authored lessons and one more bug report at 500 times the encode time per
record, and their filler cosines rose with their true-pair cosines (bge-small's chat prompts
reached 0.68), so none offers a cleaner line. The static model stays; the reranker is where
the precision is sought.

**What the held-out set has already seen, stated.** The first spike scored the held-out tasks
twice before the selection set existed: full text at window 36 (MiniLM 7/4/6 of 8 by variant,
jina 7/5/6) and short text at window 18 (MiniLM 7/5/5, jina 6/6/4), as ranks in the reranked
list, before the floor. The model, text and window were then chosen on the selection set, but
the held-out rows below were seen once by the author and are not blind for this arm. The
probe's own rows were used for selection and are reported, not pooled.

**The measure.** `evals/probe_rephrase.py --hybrid linear --rerank` against the same probe
without `--rerank`, at the same commit and store, in the same sitting (and the full-text probe
beside them for orientation): held-out recall by variant after the floor (harness and hook
configurations), the governing lesson's rank in the reranked in-scope list, the authored row,
the probe's own rows, the six precision prompts' counts, and the median `core.check` latency
the probe now prints (the first call includes the model load). §4q's control at an earlier
commit and a 313-record store: held-out 7 / 3 / 5, probe's own 8 / 2 / 8, authored 8,
precision 5, 9, 0, 12, 7, 12.

**Predictions.** The held-out paraphrase row rises by at least one over the same-sitting
control; the held-out ticket and bug-report rows do not fall; the authored row stays 8; no
precision prompt gains more than one record; the median check latency with the model loaded
is under one second on this laptop, and the first call under two.

**Falsifiers.** Any held-out row falls below the control (the second stage displaces what the
first had right); or the paraphrase row does not rise after the floor while its rank column
does (the order was not the limiter; the floor is, and a relative admission rule for
reranked semantic-only candidates is the next pre-registration, not a reinterpretation of this
one); or a precision prompt gains two or more records; or the median check exceeds 1.5 s. Any
of these and the stage ships as an experiment flag, off, with the result recorded.

**What a pass earns.** The flag is documented beside `--hybrid` as the measured configuration
of the semantic arm, and the next agentic A/B on the held-out tasks (§4r's instrument) runs
with both on, since the probe measures recall and the harness measures what the agent writes.
Neither becomes the default on the probe alone (§4n's rule).

**Cost.** No paid call; about a minute per probe run; an 80 MB ONNX model on disk under the
`rerank` extra, fetched once by `okl embed`.

**What this cannot settle.** Whether a better order changes what the agent writes; whether
the first stage's recall, which bounds the pool, holds on a larger store (the pool is 24
regardless of store size, so the cost is flat and the recall question moves to the fetch);
whether a stronger cross-encoder would do better than the fastest one on wording the author
has not read.

### Result (2026-10-23)

Receipts: `evals/results/probe-rephrase-20261023-rerank-{control-off,control-linear,on}.txt`,
all three at commit 3bbe621 against the same 318-record store (every record with a vector),
run in one sitting; the control is the middle column.

| of 8 tasks | full-text | linear 0.40 (control) | linear 0.40 + rerank |
|---|---|---|---|
| authored | 8 | 8 | 8 |
| probe's own ticket / paraphrase / bug report | 8 / 1 / 8 | 8 / 2 / 8 | 7 / 2 / 8 |
| held-out ticket / paraphrase / bug report | 7 / 2 / 5 | 7 / 3 / 5 | 7 / 4 / 4 |
| six precision prompts, records returned | 4, 11, 0, 11, 8, 12 | 5, 11, 0, 12, 8, 12 | 5, 11, 0, 12, 8, 12 |
| median `core.check`, in-process | 7 ms | 24 ms | 538 ms (first call 900 ms, max 1.7 s) |

**The falsifier fired.** One held-out row fell: the bug report for the token-storage lesson
(`spa_tokens`), briefed at rank 5 under the control, left the twelve at rank 17 under the
reranker; and the probe's own ticket row lost one (`ci_linter`, rank 12 → 18). The held-out
paraphrase row rose as predicted (`rate_limiter`'s entered), the ticket rows held, the
authored row held, the precision counts did not move at all (the same twelve records in
another order on every prompt), and the latency was as predicted. By the rule as written the
stage ships as an experiment flag, off.

**What the order did.** The cross-encoder moves records a long way in both directions. Toward
the top: the governing lesson of five paraphrases that share no subject word with it went
from ranks 23, 42, 39, 72 and 77 to 2, 1, 8, 11 and 25 (`price_tamper`, `rate_limiter` and
`react_fetch`'s own paraphrases; `judge_summary`'s and `idor_endpoint`'s held-out ones), and
eight tickets and bug reports already briefed went to rank 1. Away from it: `price_tamper`'s
held-out paraphrase 1 → 8 and bug report 4 → 20, `spa_tokens`' paraphrase 3 → 8 and bug
report 5 → 17, `react_fetch`'s paraphrase 2 → 8. The pool was the limiter once:
`idor_endpoint`'s held-out bug report sits at fused position 35 and was never scored.

**Why the gains did not reach the briefing.** Four of the five paraphrases the reranker lifted
into the top twelve share no subject word with their lesson, so the full-text arm did not
return them and the §4q rule holds, as pre-registered: a candidate only the semantic arm found
passes the floor by cosine (0.40) and never by a word or a rank. The reranker's score cannot
take the floor's place: in check's own window the lifted lessons scored −9.8 to −11.4 while
the six chat prompts' best candidate scored −4.0 to −11.4 (the band the selection set
showed), so a score line that admitted the lessons would admit the filler, and a rank line
admits whatever is first, which on a chat prompt is filler by construction. The second stage
orders well enough to put a paraphrase's lesson first and not well enough to say that it
belongs; the floor, which is what keeps the short prompts at 0, 5 and 8 records, still has to
decide, and it decides on words.

**Reading, against the pre-registration.** Net on the held-out set after the floor: one in,
one out; on the probe's own rows, one out. The paraphrase gain is real and the bug-report loss
is real; a measurement this size cannot rank them. A passage cross-encoder trained on web
search queries, reading one to three sentences per record, is a different regime from the one
its benchmark gains come from; the heavier models that read more carefully found one more
paraphrase on the selection set at nine to twelve times the time and lost authored lessons.
The default stays the first stage, and the "what a pass earns" clause does not apply.

**What ships.** `okl check --rerank` (and `"rerank": true` in the config, `OKL_RERANK`), the
`rerank` extra, `okl embed` caching the model, each briefed record's `rerank_score` in the
JSON, `evals/probe_rephrase.py --rerank`, a latency line on every probe receipt, and the three
selection scripts with their receipts; off everywhere; documented as the measured experiment
it is. The next retrieval experiment is not another cross-encoder on this pool. It is the
floor's rule for a candidate only the semantic arm returned (an admission by the first
stage's cosine and the second stage's rank together, pre-registered against the six prompts),
or a wider first-stage window; each is its own pre-registration.

## 4u. PRE-REGISTERED: the floor's word rule for a candidate only the semantic arm returned (2026-10-24)

Written before the run, per §2b, for the two follow-ups §4t named; the first is settled here
without a run and the second is measured by the probe.

**The admission rule, settled by the grid.** §4t's reranker lifted the lesson of several
paraphrases to rank 1 or 2 and the floor then dropped them. The proposed rule was an
admission by the first stage's cosine and the second stage's rank together.
`evals/admission_grid.py` (receipt `evals/results/admission-grid-20261024.txt`) lists, on the
selection set, every governing lesson the floor drops with its cosine and reranker rank, and
every record the six chat prompts' floor drops with the same two numbers, then counts both
over a grid of cosine lines (0, 0.25, 0.30, 0.35) and rank bounds (1, 2, 3, 5). The dropped
governing lessons sit at cosines 0.20 to 0.29; the chat prompts' rank-1 to rank-3 filler
reaches 0.36. Rank alone admits two lessons and two filler records, one of them on the prompt
that returns nothing today (the §4n case); every cosine line at or above 0.25 admits no
lesson at all. No cell separates them, so the rule is not pre-registered on the held-out set
and the reranker stays as §4t left it.

**The second follow-up, and what the diagnostic found.** A wider first-stage window was named
because one held-out bug report sat at fused position 35, past the reranked pool. Tracing
every held-out row the §4t receipt marks MISS through the first stage at fetches of 36, 72
and 108 per arm (reranker off) found a different mechanism in one row: the paraphrase for the
exit-code lesson shares two subject words with it ("data", "job") and sits at fused position
18, but the full-text search's 36 did not include the lesson, so the floor judged it as a
candidate only the semantic arm found and asked for a cosine of 0.40 (it has 0.31). At a
fetch of 72 the full-text search includes it and the two-word rule passes it. Every other
MISS row shares at most one word with its lesson, outside its title and symptom, at every
fetch, so no window admits it after the floor. This diagnostic read the held-out rows, which
§4t had already read once; the row it names is therefore not blind, and the prediction below
is a mechanism check on that row plus a cost check on everything else, not a blind recall
claim.

**Two knobs, both neutral where they can be chosen.** `core.FETCH_MULTIPLIER` (the first
stage's fetch per arm, 3 times the limit today) and `core.SEMANTIC_WORD_FLOOR` (None today:
a semantic-only candidate passes by cosine alone; an integer n admits it when it shares n
subject words with the task, never fewer than the floor's own two). `evals/window_grid.py`
(receipt `evals/results/window-grid-20261024.txt`) runs `core.check` on the selection set
and the six prompts for hybrid off and linear, fetches of 36, 72 and 108, and the word rule
off and at 2: every cell is identical on recall (8 / 8 / 2 / 8 under linear; 8 / 8 / 1 / 8
full-text) and on the six counts. The selection set cannot choose, and it says neither knob
costs precision there.

**The choice, and why.** The two-word rule ships (`SEMANTIC_WORD_FLOOR = 2`); the fetch stays
at 3 times the limit. The rule judges a candidate by the evidence in front of the floor,
two shared subject words, rather than by which arm's window happened to reach it, which is
what §4q's first pass got wrong in the other direction (one word in the subject was never
enough for a semantic candidate, and still is not). A wider fetch would reach the same row
by accident of window size, costs more per check as the store grows, and changes the
fusion's normalisation for every query.

**The measure.** `evals/probe_rephrase.py --hybrid linear` against the same probe with
`--semantic-words off`, at one commit, one store, one sitting; the full-text probe beside
them, which the rule cannot change (it has no semantic-only candidates). Held-out recall by
variant after the floor, the authored row, the probe's own rows, the six precision prompts'
counts.

**Predictions.** Under linear, the held-out paraphrase row rises by one (3 → 4: the exit-code
row, named above); no other held-out row changes; the authored and probe's own rows do not
change (the grid says so); the six counts do not change; the full-text probe is identical
under both settings.

**Falsifiers.** Any precision prompt gains a record; or any held-out row falls; or the
named row does not enter (the mechanism was misread). Any of these and the rule reverts to
None in the same change, with the receipts kept.

**Cost.** Nothing: the rule reads words the floor already matched.

**What this cannot settle.** Whether the rule matters on prompts the author has not read:
one row moved, and it was read first. Whether the semantic arm, with this rule, earns the
default: that remains an A/B question (§4n's rule), not a probe one.

### Result (2026-10-24)

Receipts at commit b36d1b7 (the rule at 2 in `core`, the probe's `--semantic-words off` for
the control), one 322-record store, one sitting: `evals/results/probe-rephrase-20261024-semwords-{off-fulltext,control,2}.txt`
are the pre-registered runs; `probe-rephrase-20261024-semwords-rerank-{control,2}.txt` are
exploratory, reranker on, and were not pre-registered.

| of 8 tasks | full-text | linear, rule off (control) | linear, rule 2 |
|---|---|---|---|
| authored | 8 | 8 | 8 |
| probe's own ticket / paraphrase / bug report | 8 / 1 / 8 | 8 / 2 / 8 | 8 / 2 / 8 |
| held-out ticket / paraphrase / bug report | 7 / 2 / 5 | 7 / 3 / 5 | 7 / 3 / 5 |
| six precision prompts, records returned | 4, 11, 0, 11, 9, 12 | 5, 11, 0, 12, 9, 12 | 5, 11, 0, 12, 9, 12 |

**The falsifier fired: the named row did not enter.** Every cell is identical. Tracing the
row through `check`: the floor now keeps the lesson, the sixteenth of thirty-six kept
records, and the cutoff at twelve drops it, because fifteen records the floor also keeps
rank above it in the fused order ("Never let stored data reach a shell", "Write commit
bodies to a file", and others sharing two generic words with a prompt about writing a data
job's output). The mechanism was half-read: two gates stood in the row's way and the
pre-registration named the first. By the rule as written `SEMANTIC_WORD_FLOOR` reverts to
None in this change; the knob, its test and the probe flag stay for a later pre-registration.

**Exploratory, not pre-registered.** With the reranker on (§4t's configuration), where the
probe had the row at rank 5, the rule admits it (MISS → yes) and the rate-limiter paraphrase,
which sat at the cutoff's edge, leaves in the harness configuration (yes → MISS) because one
more admitted record ranks above it; the held-out paraphrase row reads 4 of 8 under both
settings, the hook configuration gains one (3 → 4), the six counts are identical, and the
authored and probe's own rows do not move. A rule that decides who holds the twelfth slot is
not a gain, and it is reported here so nobody re-runs it expecting one.

**Reading.** On this store a paraphrase's lesson, once the floor admits it, sits at fused
position 15 to 20 behind records kept by the same two-word rule on generic words. What binds
is the order among the kept records and the cutoff that reads it, not the floor. The next
retrieval pre-registration is about that order: a cut that prefers matches in a record's
title, symptom and aliases over matches in its body, or a cutoff that counts by type, each
measured first on the six prompts and the authored row. Nothing here changes the default,
and §4n's rule stands: the probe measures recall; the harness measures what the agent
writes.

**What ships.** Nothing in behaviour. `core.FETCH_MULTIPLIER` and `core.SEMANTIC_WORD_FLOOR`
as constants at today's values, `evals/admission_grid.py` and `evals/window_grid.py` with
their receipts, the probe's `--semantic-words`, and the floor test for the knob.

## 4v. PRE-REGISTERED: the floor's one-word rule, weighted by how common the word is (2026-10-24)

Written before the run, per §2b, for #277; the selection grid is the only thing run first.

**The question.** The floor admits a record that shares one word with the task when that word
sits in the record's title or symptom (§4n). Written for "price" and "endpoint", the rule also
admits every record whose title holds "doc", "update" or "search", so three of the six no-match
prompts still return 9 to 12 lessons (§4u's receipts: 4, 11, 0, 11, 9, 12), each through one
common title word. Does weighting that rule by how common the word is in the store refuse
those prompts without costing recall?

**The design.** `core.COMMON_WORD_SHARE` (None today): a title or symptom word admits a record
on its own only when it occurs whole in at most that share of the store's live records; two
shared words admit regardless, and so does a one-word alias matched whole, since an alias is a
deliberate choice. The share is counted by a scan of the store per check (a few milliseconds
at a few hundred records; a count from the full-text index is the version for a large store).

**Selection, on the selection set.** `evals/common_word_grid.py` (receipt
`evals/results/common-word-grid-20261024.txt`) ran `core.check` over the probe's own
rephrasings, the authored tasks and the six prompts at shares of 3, 5, 10, 15 and 25 per
cent, full-text and linear. Recall did not move in any cell (authored 8, the probe's own
8 / 1 / 8 full-text and 8 / 2 / 8 linear, at every share). The six prompts: at 3 per cent
4, 11, 0, 11, 9, 12 became 1, 8, 0, 2, 8, 6 (three refused at the three-lesson budget); at 5
per cent 1, 10, 0, 2, 9, 6 (three refused); from 10 per cent up nothing changed, because
"doc", "update" and "search" each sit in about 6 per cent of the 323 records. #277's rule
picks the largest share that keeps the authored row and lowers all three heavy prompts: 5 per
cent. The 3 per cent reading is reported beside it below. §4n's section C had put the IDOR
task at risk under a flat 3 per cent line; the grid shows why it is not: that lesson passes
by two shared words, which the knob leaves alone.

**The measure.** `evals/probe_rephrase.py` at one commit with the knob at 0.05 and with
`--common-share off` as the control, full-text and linear: held-out recall by variant after
the floor, the authored row, the probe's own rows, the six counts and the rejection line.

**Predictions.** At least two of the three heavy prompts drop below 6 lessons and the
rejection line reads 3 of 6; no held-out row falls; the authored row stays 8; the probe's own
rows do not move.

**Falsifiers.** Any held-out row falls below the control; or the authored row falls; or
fewer than two heavy prompts drop. Then the knob stays at None with the receipts kept.

**Cost.** One scan of the store per check at this scale; nothing else.

**What this cannot settle.** Whether 5 per cent is the right line on a store ten times this
size, where a word's share means something different; the index-count version and a re-grid
belong to that store. Whether refusing filler changes what the agent writes (an A/B question).

### Result (2026-10-24)

Receipts at commit 2ae05a8, one 323-record store, one sitting:
`evals/results/probe-rephrase-20261024-common-{fulltext,linear}-{control,on}.txt`, the
control run with `--common-share off`. An absolute minimum joined the rule before the run:
a word counts as common only past five records as well as past the share, because in a store
of a dozen records every word is in a large share, and the suite's small-store floor tests
said so.

| | full-text, rule off | full-text, 5% | linear, rule off | linear, 5% |
|---|---|---|---|---|
| authored | 8 | 8 | 8 | 8 |
| probe's own ticket / paraphrase / bug report | 8 / 1 / 8 | 8 / 1 / 8 | 8 / 2 / 8 | 8 / 2 / 8 |
| held-out ticket / paraphrase / bug report | 7 / 2 / 5 | 7 / 2 / 5 | 7 / 3 / 5 | 7 / 3 / 5 |
| six no-match prompts, records returned | 4, 11, 0, 11, 9, 12 | 1, 10, 0, 2, 9, 6 | 5, 11, 0, 12, 9, 12 | 1, 11, 0, 3, 9, 6 |
| refused at the three-lesson budget | 1 of 6 | 3 of 6 | 1 of 6 | 3 of 6 |
| median `core.check`, in-process | 7 ms | 19 ms | 21 ms | 39 ms |

**No falsifier fired; one prediction was half right.** No recall row moved, in any
configuration, held-out or authored or the probe's own: the rule took nothing. All three
heavy prompts dropped, which is what the falsifier asked, but only one dropped below six
("give me a doc for that too", 11 → 2, losing the lessons that share nothing but "doc" in
their titles); the search prompt went 12 → 6 exactly, and the updates prompt 11 → 10. The
rejection line reads 3 of 6 as predicted. The prediction of two prompts under six was wrong
by one prompt and one lesson.

**What left and what stayed.** The lessons that left are the ones the rule was written for:
four "doc" titles, four of the search prompt's "search" titles, three of the scrutinize
prompt's one-word matches. The updates prompt keeps ten because its words ("updates",
"update", "site", "writing") each sit under the line or match twice; the governing-plan
prompt keeps nine for the same reason. Those two are the ordering question §4u named, not
this one. The search prompt's six are lessons about retrieval in a store that is largely
about retrieval; six may be close to right.

**Cost.** The share is a scan of the store per check: 12 ms at 323 records, which is the
whole of the 7 → 19 ms change. A count from the full-text index replaces the scan when a
store makes it matter; §4q's ADR amendment carries the same tier logic for vectors.

**What ships.** `COMMON_WORD_SHARE = 0.05` with the five-record minimum, as the default;
the diagram's floor text and both renders, the README's floor sentence and alt text; the
grid and probe receipts; the probe's `--common-share`. The rejection line in `evals/README`'s
standing table reads 3 of 6 once #278 and this land.

## 4w. PRE-REGISTERED: a calibrated briefing decision over write-time triggers, on a benchmark built to decide (2026-10-26)

Written before the held-out split was run, per §2b, for #291. The selection split was used to
choose, and was run first; its receipts are named below. No run has touched the held-out
queries. The null prompts are not held out in the same way, because they are not divided by
query: every selection run printed the unseen half's rate (the tables below), and a held-out run
scores those same prompts against the same line, so it reproduces those figures by
construction. The unseen half was never part of a selection rule, but it was seen. The fresh
test on real prompts is the judged-precision run on TASK prompts, which no selection run used.

**Why a new instrument.** §4n through §4v were measured on eight authored tasks, three
rephrasings each and six chat prompts: one lesson moves a row by 12.5 points, and a paired test
at that size needs about six discordant tasks in one direction before it can see anything.
`evals/bench/` is built to decide:

- **Corpus**: the twelve committed seed packs, 183 records, imported fresh on every run.
- **Queries**: 519, three per advice lesson (a ticket, a paraphrase sharing no content word
  with the lesson's title, a bug report), written by Claude Sonnet from the lesson alone under
  `evals/bench/GENERATION.md`, which was written before any query existed. Its structural rules
  are checked mechanically (`assemble_queries.py`: three registers per lesson, 6 to 40 words,
  no title word in a paraphrase other than a stopword or a single character). Its rules about
  content (never naming the lesson or its advice, a bug report never naming the cause or the
  fix) were instructions to the writer and are not checked. Split by lesson, by the parity of a
  hash of its id: 249 selection, 270 held out.
- **Null prompts**: 550 real prompts with no subject of their own, the NULL label given by a
  Sonnet sub-agent to 1,367 distinct prompts typed in one developer's Claude Code sessions (577
  were TASK, 240 UNCLEAR). Beyond the Claude sub-agents that label and judge them, they never
  leave that machine: nothing commits, publishes or quotes them, and receipts carry counts and
  a hash. They are halved by the parity of a hash of their id: the calibration half sets lines,
  the unseen half tests them.
- **Scope**: each query is asked from a repo where its lesson is in scope. Eighteen seed lessons
  are repo-scoped, and `check` rightly shows them nowhere else; the first runs asked every query
  from one repo and so scored 54 queries no arm could win, and the prototype runners, which
  ignored scope, looked better than production for it. Fixed before any receipt below.
- **Statistics**: recall carries a 95% percentile bootstrap that resamples lessons (2,000
  draws), because a lesson's three queries are not independent; rates on the null prompts carry
  Wilson intervals. The bench is deterministic for a store and a commit, so §2b's 21-point noise
  floor, which is about the agent harness, does not apply to it; sampling error does, and the
  intervals are that.

**What it found about today's default (selection, receipts at 2993368).** Recall 75.1% [69.1,
80.7]; 11.8 lessons briefed per query; and 149 of 268 unseen null prompts (55.6%) briefed
something; a briefed null prompt got 5.1 lessons on average, over all 550. The briefing also
treats prompts a harness wrote (task notifications, sub-agent reports) as typed by a person: in
the session that built the bench, they were briefed repeatedly, up to twelve lessons each.

**The design, two parts measured apart.**

1. **Triggers**: write-time phrasings of the moments a lesson applies (the doc2query and HyPE
   idea: index the questions a document answers, not only the document). Ten per advice lesson,
   1,730 in all (4 task, 3 symptom, 3 vocabulary), written by Claude Opus from the lesson alone,
   in a folder that held only the lessons, never shown a query (`evals/bench/triggers.jsonl`,
   checked by `assemble_triggers.py`). Their overlap with the queries for the same lesson: a
   median 10.3% of a query's word bigrams appear somewhere in its lesson's triggers, 25.0% at the
   90th percentile; the closest single query-trigger pair has bigram Jaccard 0.40. Stored in
   their own full-text column at the symptom's weight.
2. **The calibrated decision** (`src/okl/decide.py`, `okl check --decision calibrated`). A
   prompt a harness wrote is briefed nothing; a prompt with no subject word is briefed nothing; a
   candidate's score is how many of the prompt's subject words its about-text (title, symptom,
   aliases, triggers) holds, ties broken by their rarity relative to the store; a candidate is
   briefed at or above a line set by split conformal at alpha 0.05 over the calibration half
   (2.0017173: three shared subject words, or two nearly as rare as a word in one record), best
   first, at most five.

**Selection, on the selection split** (receipts `evals/results/bench-20261026-sel-*.txt`, each
naming its commit: the decision arms and the first two dense runs (bge-small, potion) at
2993368, the other model arms at fa0d8ca, cb73568 and 2077f09):

| arm (alpha 0.05, cap 5 where it applies) | recall [95%] | lessons per query | unseen null prompts briefed |
|---|---|---|---|
| today: floor, full-text | 75.1% [69.1, 80.7] | 11.8 | 149 of 268 (55.6%) |
| floor, full-text, with triggers | 80.3% [75.1, 85.5] | 11.8 | 149 of 268 (55.6%) |
| floor, with the semantic arm | 78.3% [72.7, 83.5] | 11.9 | 150 of 268 (56.0%) |
| decision: share of the subject covered, with triggers | 0.0% | 0.0 | 0 of 268 |
| decision: rarity evidence in the about-text, with triggers | 84.3% [79.5, 88.8] | 3.6 | 6 of 268 (2.2%) |
| decision: rarity evidence in the whole text, with triggers | 86.3% [81.9, 90.4] | 4.3 | 7 of 268 (2.6%) |
| **decision: shared subject words, with triggers (production)** | **88.0% [83.9, 91.6]** | **4.7** | **9 of 268 (3.4%)** |
| decision: rarity evidence, without triggers | 30.1% [24.1, 36.5] | 0.9 | 2 of 268 (0.7%) |

**Models, on the same split.** Each recent local model tried on this machine's CPU was
measured in up to three ways (receipts `-rerank-*`, `-rank-*` and `-dense-*`; the rerankers
have only the first, bge-small, granite and answerai-colbert-small only the last). The runner applies each
model card's retrieval prompts itself. fastembed 0.9 names them in its model descriptions, but
its `query_embed` and `passage_embed` apply none of them, and the first EmbeddingGemma receipt
ran without them. That receipt is kept, renamed `-noprompts`, as an ablation.

*A model as the decision.* A cross-encoder scores each prompt's full-text candidates. The line
is set by the same split conformal procedure.

| reranker (quantized ONNX) | candidates scored | recall [95%] | lessons per query | unseen null prompts briefed | scoring one prompt, median, other runs sharing the machine |
|---|---|---|---|---|---|
| gte-reranker-modernbert-base | 24 | 22.5% [16.9, 28.5] | 0.54 | 16 of 268 (6.0%) | 1.2 s |
| Qwen3-Reranker-0.6B, P(yes) | 8 | 31.3% [24.5, 38.2] | 0.63 | 13 of 268 (4.9%) | 2.5 s |

A reranker's score orders the candidates for one prompt; it is not calibrated across prompts.
So the line that holds the null prompts near 5% refuses most real queries as well. In the
abstention literature (Gisserot-Boukhlef et al., TMLR 2024, arXiv 2402.12997), a function
fitted on labelled queries over the sorted scores abstained better than heuristics on the raw
scores.

*How well a model orders, and how well it separates* (`rank_quality.py`). Every in-scope lesson
is ranked by the model alone. AUC is the governing lesson's score against each calibration-half
null prompt's best.

| | hit@1 | hit@3 | hit@12 | MRR | AUC against null prompts |
|---|---|---|---|---|---|
| full-text with triggers, no model | 70.7% | 85.5% | 94.8% | 0.793 | |
| LateOn (late interaction) | 78.7% | 91.2% | 97.2% | 0.855 | 0.831 |
| EmbeddingGemma-300m, with its prompts | 65.5% | 88.4% | 97.6% | 0.778 | 0.869 |
| EmbeddingGemma-300m, without | 68.7% | 88.4% | 98.0% | 0.799 | 0.739 |
| Qwen3-Embedding-0.6B (int8), with its prompt | 62.7% | 85.5% | 98.8% | 0.755 | 0.813 |
| potion-retrieval-32M (static) | 59.8% | 77.1% | 91.2% | 0.704 | 0.767 |

LateOn orders best of anything measured. But its MaxSim has a median of 0.938 for the governing
lesson and 0.865 for a null prompt's best, too narrow a band to draw a line in. EmbeddingGemma's
prompts cost it a little order (hit@1 68.7% to 65.5%) and buy most of its separation (AUC 0.739
to 0.869), the best of any model.

*A model added to the decision.* The score is the shared subject words plus W times the model's
best cosine over the lesson's about-text phrasings (for late interaction, MaxSim over one
about-text document). The candidates are the full-text window plus the model's own 36 nearest.
The line is recalibrated for every W. At W = 0 every one of these runs reproduces production
exactly (88.0%, 9 of 268).

| added to the shared-word decision, cap 5 | W, best on this split | recall [95%] | lessons per query | unseen null prompts briefed | paraphrases briefed | a new process pays: load, then per prompt |
|---|---|---|---|---|---|---|
| nothing (production) | | 88.0% [83.9, 91.6] | 4.66 | 9 of 268 (3.4%) | 64 of 83 | no model |
| potion-retrieval-32M | 1 and 2 | 90.0% [86.3, 93.6] | 4.67 | 8 of 268 (3.0%) | 66 | 0.8 s, 0.3 ms |
| LateOn | 1 to 8 | 88.8% [84.7, 92.4] | 4.65 | 10 of 268 (3.7%) | 65 | 1.6 s, 150 ms |
| Qwen3-Embedding-0.6B (int8) | 4 and 8 | 91.6% [88.0, 95.2] | 4.65 | 10 of 268 (3.7%) | 70 | 2.4 s, 0.9 s |
| EmbeddingGemma-300m | 8 | 92.4% [88.8, 95.6] | 4.39 | 12 of 268 (4.5%) | 72 | 2.0 s, 0.17 s |

EmbeddingGemma's W = 8 is the top of a broad rise, not a lone spike (`-words` and `-words-wide`).
Recall at each W:

| W | 1 to 4 | 8 | 12 | 16 | 24 | 32 |
|---|---|---|---|---|---|---|
| recall | 90.8% | 92.4% | 91.2% | 89.6% | 86.3% | 83.9% |

Its cold load measured 12.4 s at fa0d8ca and 1.7 to 2.1 s in every run after (the held-out
run included); the first run followed the download, and the operating system's file cache is
the likely difference, not measured. A hook process pays somewhere in that range on every
prompt.

Most of these models were also run on the rarity-evidence base, the earlier design, and none
beat EmbeddingGemma on the shared-word base. The best weight for each:

- potion: 89.6%, with 18 of 268 null prompts briefed;
- granite-embedding-small-english-r2: 88.8% at 11;
- bge-small-en-v1.5: 85.5% at 9;
- EmbeddingGemma: 90.8% at 13 with its prompts, 91.6% at 14 without;
- Qwen3-Embedding: 91.2% at 8;
- answerai-colbert-small and LateOn: flat at the base's 84.3%.

**What the models add.** They help where shared words fail, on paraphrases. EmbeddingGemma
briefs 8 more of 83 paraphrases, at the cost of 3 more null prompts briefed. But the hook is a
new process on every prompt. The cheapest model that helps costs 0.8 s there for 2 points, and
the best costs about 2.2 s. So the default stays model-free. The model arm is pre-registered
below as a second, exploratory treatment, for a process that keeps the model loaded.

Two readings decide the design. Neither part works alone: triggers lift the governing lesson
to first place for 70.7% of queries against 45.0%, but under the floor a query is still
briefed 11.8 lessons on average and half the null prompts something; the decision without
triggers misses the governing lesson on two queries in three. And the share-of-subject score cannot be used at all: a
one-word prompt covered by a title scores 1.0, so the line saturates.

**The selection rule**, stated plainly as written after the grid was read: the highest recall
at alpha 0.05 among configurations that load no model at prompt time (the hook is a new process
per prompt) and brief at most five lessons on average. That is the shared-words decision with
triggers, cap five, which production reproduces exactly (`bench-20261026-sel-calibrated.txt`
against `bench-20261026-sel-v2-shared_words-triggers.txt`: the same 88.0% and the same 9 of 268).

**The rule for the exploratory model arm**, also written after the grid was read: the highest
recall at alpha 0.05 and cap five among the models that encode a prompt in under 250 ms once
loaded. That rule leaves out Qwen3-Embedding, at 0.9 s. It picks EmbeddingGemma-300m with its
prompts, added to the shared-word decision at W = 8.

**The measure.** At the commit that carries this section, from a clean worktree, in one
sitting, on the held-out split and the unseen half of the null prompts:

- `evals/bench/run.py --split heldout`, three ways:
  - with `--decision floor`: the control, today's default;
  - with `--decision floor --triggers`: triggers alone;
  - with `--decision calibrated --triggers`: the treatment.
- `evals/bench/run_v2.py --split heldout --score shared_words --triggers`: the implementation
  check.
- `evals/bench/run_dense.py --split heldout --model google/embeddinggemma-300m --base
  shared_words --weights 0,8 --triggers`: the exploratory model arm, with W = 0 as its
  same-run control.
- Judged precision on real prompts (`evals/bench/precision_pairs.py`). 100 TASK prompts are
  drawn with seed 7 and briefed by the control and by the treatment. Every (prompt, lesson) pair
  is judged once by a Claude Sonnet sub-agent as APPLIES, DOES_NOT_APPLY or UNSURE. The pairs
  are shuffled and do not say which arm briefed them.

**Predictions** (each against the same-sitting control):

1. The treatment's held-out recall is at least 10 points above the control's, and no register
   is lower than the control's.
2. The treatment briefs at most five lessons per query on average (the control about twelve).
3. A check, not a prediction: the unseen null prompts reproduce their selection figures, 9 of
   268 for the treatment and 149 of 268 for the control. They are the same prompts against the
   same line, so any other figure means the code changed.
4. Production and the prototype agree on whether each held-out query's lesson is briefed.
5. On real TASK prompts, the treatment's judged precision (the share of the lessons it briefs
   that the judge says apply) is higher than the control's.
6. Exploratory: the model arm's held-out recall at W = 8 is above its own W = 0, and more of the
   gain comes from paraphrases than from either other register.

**Falsifiers.** Any one of these and `calibrated` stays opt-in, with the receipts kept:

- the treatment's held-out recall below the control's;
- any register more than five points below the control's;
- a null-prompt figure other than the selection one;
- any disagreement between production and the prototype;
- a judged precision below the control's.

Prediction 6 gates nothing in this release. If W = 8 is not above W = 0 on held-out, no
loaded-model tier is built on this evidence.

**The lessons at risk**, per §2b: a lesson whose only route to a query is one word in its
title, which the floor admitted and the decision will not (its about-text must share three
subject words, or two rare ones); and paraphrases in general, the weakest register on selection
(77.1% against 96.4% for bug reports).

**What a pass earns.** `calibrated` becomes the default decision in the next release, the seed
packs carry their triggers, and `okl record` asks for triggers. A pass of prediction 6 earns the
model arm a production implementation in a process that keeps the model loaded (the MCP server
or a daemon), measured again there, judged precision included. It does not settle whether
briefing fewer, better-chosen lessons changes what an agent writes: that is a question for the
agent harness, pre-registered separately (§4n's rule).

**What this cannot settle.** The queries and the triggers were written by two models of one
family, which can flatter the trigger arm on synthetic queries (CIKM 2025, arXiv 2506.10301);
the judged-precision run on real prompts is the check, not a cure. The null prompts and the
line's guarantee are one developer's: the guarantee holds for prompts exchangeable with those,
and another team's line is its own calibration. The corpus is the 183-record seed set; a live
store holds recorded lessons that have no triggers until someone writes them, and the scan that
computes rarity runs per check (the whole calibrated check takes 12 ms, median, at this size),
which a full-text vocabulary count replaces on a store that makes it matter.

**Cost.** Ten trigger lines per lesson in the packs; per check, the rarity scan; no model.

### Result (2026-10-26)

Run at cd04216 from a fresh worktree, in one sitting (receipts
`evals/results/bench-20261026-heldout-*.txt`; judged precision in
`bench-20261026-precision.txt`, whose tally prints no commit: it ran in the same worktree at
cd04216, and the detail receipt beside it names 7e7aa2f).

| held out: 270 queries, 90 lessons | control: floor, no triggers | floor, triggers | **treatment: calibrated, triggers** | model arm, W = 0 | model arm, W = 8 |
|---|---|---|---|---|---|
| recall [95%] | 74.4% [68.5, 80.4] | 84.1% [79.3, 88.5] | **90.0% [86.7, 93.3]** | 90.0% [86.7, 93.3] | 95.2% [93.0, 97.4] |
| bug report / paraphrase / ticket, of 90 each | 78 / 52 / 71 | 84 / 63 / 80 | **86 / 73 / 84** | 86 / 73 / 84 | 81 paraphrases |
| governing lesson first in the search's order, before the decision (hit@1) · MRR | 40.4% · 0.515 | 68.1% · 0.780 | 68.1% · 0.780 | | |
| lessons briefed per query | 11.8 | 11.8 | **4.7** | 4.69 | 4.52 |
| unseen null prompts briefed anything | 149 of 268 | 149 of 268 | **9 of 268** | 9 of 268 | 12 of 268 |

The model arm's receipt prints only the paraphrase register; its W = 0 by register is the
prototype's (`-heldout-v2-shared_words`), whose figures it matches.

**Predictions 1 to 4 and 6 held, and no falsifier fired.**

1. Recall rose 15.6 points, from 74.4% to 90.0%. Every register rose: bug reports by 8 queries,
   paraphrases by 21 and tickets by 13.
2. The treatment briefed 4.7 lessons per query, against 11.8.
3. The check passed. The null figures were the selection figures exactly: 9 of 268 for the
   treatment and 149 of 268 for the control.
4. Production and the prototype agree everywhere their receipts can be compared: recall 90.0%,
   86 / 73 / 84 by register, and 9 of 268 null prompts. The prototype's runner prints no
   outcome per query, so per-query agreement is not shown. Equal counts in every register would
   need disagreements that cancel exactly within each register.
6. At W = 8 the model arm reached 95.2% against its own W = 0's 90.0%, 14 more queries. Eight
   of them were paraphrases (73 to 81). At W = 0 bug reports and tickets had only 4 and 6 queries
   left to gain, so neither can account for as much. The gain was larger held out than on
   selection (5.2 points against 4.4).

**Prediction 5 held.** On 100 real TASK prompts, judged precision rose from 8.9% [7.1, 11.2] to
24.5% [19.2, 30.8] (`bench-20261026-precision.txt`). Of the 770 lessons the control briefed,
751 were judged either way and 67 of them applied. Of the treatment's 211, 208 were judged
and 51 applied.

**The judging.** Six Sonnet sub-agents judged the 861 pairs, in six batches, under one
instruction. One batch's judge wrote only the pairs it labelled APPLIES or UNSURE and let a
script mark the rest DOES_NOT_APPLY, against the instruction to write every label. A fresh
judge re-judged that batch before any tally was run, and its labels are the ones counted. The
two labellings of that batch agree on 131 of 143 pairs (Cohen's kappa 0.69). With the first
judge's labels in place (`judge-out-3-listdefault`, which the detail receipt calls the second
labelling because it is passed second), precision is 8.4% and 24.2%
(`bench-20261026-precision-detail.txt`).

**What it costs on real prompts.** This analysis is exploratory, not pre-registered, and was
written after the tally was read (`-precision-detail`).

- **Most real prompts had nothing to brief.** Only 35 of the 100 TASK prompts had any briefed
  lesson the judge said applied. Most of one developer's prompts concern work the seed packs
  know nothing about, and there silence is right.
- **Where something applied, the treatment found less of it.** On those 35 prompts the control
  briefed an applying lesson on 32, the treatment on 28. Of the 80 applying lessons either arm
  found, the control found 67 and the treatment 51.
- **The treatment's silences were mostly right.** It was silent on 45 prompts; on 6 of them the
  control found an applying lesson.
- **The control's extra finds cost noise.** It found 16 more applying lessons by briefing 6.8
  lessons that do not apply on every prompt, against the treatment's 1.6.

This is the cost §4w named under the lessons at risk, and it is the first measure where the
decision gives something up. Held-out recall on the bench's queries rose 15.6 points. On real
prompts, the treatment surfaces about a quarter fewer of the applying lessons, while a lesson it
briefs is nearly three times as likely to apply. Real prompts are terser than the bench's
queries, and the line asks for three shared subject words, or two rare ones.

**How the parts divide the work.** Triggers did the ranking: the governing lesson came first
for 68.1% of queries against 40.4%. Under the floor, that bought 9.6 points of recall (201 to
227 of 270) and nothing else; a query was still briefed 11.8 lessons on average, and more than
half the null prompts something. The decision cuts the search's candidates at the calibrated
line and orders what clears it by shared subject words, then by the search's rank. That added
5.9 more points, took the briefing from 11.8 lessons to 4.7, and took the null prompts from
149 briefed to 9. Held-out recall (90.0%) came in above selection's (88.0%), inside each
other's intervals: no sign that the choice fitted the selection split.

**The strongest number measured is the model arm's.** It reached 95.2% [93.0, 97.4], with 12
of 268 null prompts briefed, on prompts no choice saw. It needs EmbeddingGemma loaded, which a
prompt hook cannot afford.

**What follows.** No falsifier fired, so, as pre-registered, the next release makes
`calibrated` the default decision, ships the seed packs with their triggers, and has
`okl record` ask for triggers. The cost on real prompts points to two next steps, each to be
pre-registered when it is built (#291):

- **Observed triggers**: the words of the prompt or error that led to a lesson. No model has to
  imagine them, and real prompts share them.
- **The model arm, in a process that keeps the model loaded.** On the bench it recovered much of
  what words miss (paraphrases 73 to 81 of 90). Its judged precision and its recall on real
  prompts are not yet measured.

**Shipping it (2026-10-26).** The pre-registered consequences have landed:

- `calibrated` is the default decision (`decide.DEFAULT`); `--decision floor` or
  `OKL_DECISION=floor` keeps the floor;
- the twelve seed packs carry the 1,730 triggers this section measured, and a test holds
  them equal to `evals/bench/triggers.jsonl`;
- `okl record`, the Stop hook, `/record` and the encoding-loop skill ask for triggers.

The bench's corpus drops the packs' triggers on import, so every arm keeps the meaning its
receipt gives it. On the new packs, the held-out control and treatment reproduce their
receipts query for query.

Three consequences the bench did not measure are recorded here, so they are not discovered
later:

- **The agent harness's pre-flight (§4s) under the new default.** Seven of eight tasks are
  briefed their governing record. `ci_linter`'s rule clears the line, with four shared subject
  words, and ranks sixth behind the cap. `d_unpinned_linter`, the defect it generalizes, is
  briefed in its place with the same fix, so `ci_linter` is an accepted gap in
  `evals/preflight.py`. Folding a rule and its defect into one slot is the typed-edges
  follow-up.
- **Linked gates.** The floor kept a gate that catches a briefed defect, even when the gate's
  own words were weak. The calibrated decision has no such rule: a gate is briefed only when it
  clears the line itself. Whether linked gates should ride along is unmeasured.
- **The semantic arm.** `--hybrid` can brief a record found by meaning alone only under the
  floor. Under the calibrated decision it can only reorder what clears the line.

One reporting fix: the decision counted the lessons the cap of five cut as weak matches. They
are now counted as cut (`dropped_by_cutoff`). What is briefed does not change, and the
held-out receipts reproduce exactly.

**Corrections to this section (2026-10-26).** After the result was written, an independent
agent checked about 300 figures and claims in this section and in `docs/RETRIEVAL.md` against
the receipts and the code. Every measured figure matched. It found descriptive errors, now
corrected above; none touches a prediction, a falsifier or a number a decision rests on:

- the paraphrase rule excludes the title's content words, not every word, and only the
  structural rules are checked mechanically;
- a briefed null prompt's 5.1 lessons is an average over all 550, not over the unseen half;
- bge-small and potion ran at 2993368, with the decision arms;
- the models were measured in up to three ways, not each in all three;
- the Qwen3 reranker's ONNX file is quantized; int8 is confirmed only for gte-modernbert's;
- EmbeddingGemma's cold-load range now includes the held-out run's 1.74 s, and the first run's
  12.4 s is put down to the file cache as likely, not measured;
- "every query briefed twelve lessons" was an average of 11.8;
- "abstains on two lessons in three" was "misses the governing lesson on two queries in three";
- the 12 ms is the whole calibrated check, not the rarity scan alone;
- in the result, the floor's gain from triggers is 9.6 points, not 9.7;
- the hit@1 and MRR rows describe the search's order before the decision, and the decision
  re-sorts what clears the line rather than keeping the search's order.

The same check found §4q giving the aliases' gain on the bug-report row to symptoms; that
sentence is corrected in place.

**A further correction (2026-10-26, found building §4x).** The prompt labels came from every
project folder on this machine. That includes the A/B harness's temporary repos and the e2e
scratch repos, whose prompts are authored eval tasks the harness typed, not anything a person
typed. 15 of the 100 TASK prompts in the judged-precision sample came from those folders, and
2 of the 550 null prompts did. So "real prompts" overstates that sample. The figures stand as
measured on it, but its judge labels were deleted with the run's worktree, so they cannot be
re-tallied without the 15. §4x re-measures the floor against the calibrated decision on
person-typed prompts only, with their context.

## 4x. PRE-REGISTERED: real prompts and a real store decide what the briefing needs (2026-10-26)

Written before the held-out half was pooled, for the question "how do we get real prompts to
improve too?" (follow-up to §4w and #294). The tuning half was used to choose, and its
receipts are named below.

**Why a new instrument.** §4w tuned on generated queries over the seed packs. It judged real
prompts only at the end, 15 of those 100 were not real (§4w, a further correction), and every
lesson in its corpus had triggers. A team's store is mostly its own recorded lessons, and a
person's prompts are terse. `evals/bench/real_prompts.py` measures exactly that:

- **Prompts.** The TASK-labelled prompts from project folders a person typed in (486), and the
  null prompts from the unseen half (548 person-typed). Each comes with what the prompt hook
  could have read before it (`extract_context.py`): the two typed prompts before it and the
  assistant's last reply. The prompts split into a tuning half and a held-out half by a
  salted hash. Each half pools a seeded sample of 120 task prompts and 60 null prompts.
- **Store.** A snapshot of this machine's store (ee5406f19cf9: 183 seed records, 143 recorded
  lessons without triggers), as of each prompt. A lesson recorded after a prompt is not in its
  store; the seed packs always are.
- **Judging.** Every lesson any arm briefs is pooled and judged once, by Sonnet sub-agents,
  per lesson. The judge sees the prompt with its context, shuffled, with no mark of which arm
  briefed it. One tuning batch was re-judged because its judge had decided six items whole;
  the redo agreed with the first labelling on 162 of 165 pairs. Recall is pooled: the share of
  the applying lessons any arm found.
- **Privacy.** The prompts, the store snapshot and the labels stay in
  `evals/bench/private/`; receipts carry counts and hashes.

**What the tuning half found** (receipts `real-20261026-tuning.txt`, `-tuning-fix.txt`,
`-tuning-sweep.txt`; the last holds every arm):

| task prompts, tuning (120) | precision [95%] | applying found, of the pool's 117 | lessons/prompt | null prompts briefed (of 60) | F1 |
|---|---|---|---|---|---|
| floor (the default before §4w) | 9.8% [8.0, 12.0] | 85 | 7.23 | 44 | 0.173 |
| floor-3 | 13.9% [10.5, 18.3] | 42 | 2.53 | 44 | 0.200 |
| calibrated (the default since §4w) | 16.5% [11.1, 24.0] | 21 | 1.07 | 6 | 0.172 |
| calibrated with context: prev / prev-own / reply-own | 10.5% / 10.9% / 8.6% | 26 / 26 / 42 | 2.08 / 1.99 / 4.11 | 17 / 11 / 39 | 0.14 |
| fallback | 21.6% [16.0, 28.6] | 35 | 1.37 | 7 | 0.251 |
| **backfill** | **26.3% [20.0, 33.7]** | **41** | **1.32** | **7** | **0.300** |
| line2+backfill | 14.4% [11.2, 18.5] | 52 | 3.02 | 23 | 0.218 |

Four findings, in the order they were reached:

1. **Conversation context did not help.** The first design re-set each context arm's line on
   null prompts with their context. It was self-defeating, measured before any judging: a
   continuation prompt ("ok, do it") carries its previous turn's subject, so the lines rose to
   4 to 9 shared words and the arms briefed less than the calibrated one. With the calibrated
   line kept, every context arm was less precise than the calibrated arm. The context rule,
   fixed before judging, selects none.
2. **The calibrated default misses recorded lessons.** Of the 55 applying lessons that were
   recorded lessons, it found 3, because it reads only title, symptom, aliases and triggers,
   and recorded lessons have no triggers. Of the 67 applying lessons the floor briefs and the
   calibrated arm does not, 51 are recorded lessons.
3. **Backfilling triggers fixes most of it.** The recorded advice lessons were given triggers:
   1,390 of them, ten per lesson, written by Claude Opus from each lesson alone, blind to every
   prompt, under the seed packs' protocol (`backfill-triggers.jsonl`, private). With them, the
   calibrated decision found 41 applying lessons at 26.3% precision. The fix rule, fixed
   before the fix arms were judged, selects backfill. Fallback (a lesson without triggers is
   also scored on its body and fix) found 35 at 21.6%.
4. **Lowering the line loses more precision than it gains recall.** The sweep rule, written
   before its pairs were judged, takes the highest F1 among arms briefing at most five lessons;
   it selects backfill over the floor capped at 3 or 5 and over lines of one or two words.

**The measure.** At the commit that carries this section, the held-out half is pooled under
five arms: floor, floor-3, calibrated, fallback and backfill. That is 120 task prompts and 60
null prompts, seed 11, every new pair judged per lesson as above, then
`real_prompts.py tally --split heldout`.

**Predictions** (held-out task prompts unless named):

1. Backfill finds more applying lessons than calibrated.
2. Backfill's judged precision is higher than both the floor's and floor-3's.
3. Backfill has the highest F1 of the five arms.
4. Backfill briefs anything on at most 10 of the 60 null prompts.
5. Fallback, the path that needs no triggers written, finds more applying lessons than
   calibrated, and its precision is not below calibrated's.

**Falsifiers.** If prediction 1, 2 or 3 fails, backfill does not ship as the fix, and the
default is reconsidered: the floor capped at 3 is the measured alternative. If prediction 5
fails, fallback does not ship.

**What a pass earns.** The calibrated default stays, with three additions:

- recorded lessons get triggers through a command an agent runs, which drafts them from each
  lesson, as `/record` does now;
- the briefing names how many of a store's own lessons lack triggers, as it names packs that
  predate them;
- fallback is the default's safety net for a lesson that still has none, if prediction 5 holds.

Then the release.

**What this cannot settle.**

- One developer's prompts and one store.
- The judges are Claude models, as were the trigger writers.
- Pooled recall is relative to the pool, and the floor's seven lessons a prompt dominate it.
- Whether briefing changes what the agent writes stays a question for the agent harness.

### Result (2026-10-26)

The held-out half was pooled at 4e951c0 under the five arms, 1,283 pairs, every one judged per
lesson with no label missing (receipt `real-20261026-heldout.txt`).

| task prompts, held out (120) | precision [95%] | applying found, of the pool's 101 | lessons/prompt | null prompts briefed (of 60) | F1 |
|---|---|---|---|---|---|
| floor | 9.8% [8.0, 11.8] | 90 | 7.69 | 43 | 0.176 |
| floor-3 | 12.1% [8.9, 16.2] | 38 | 2.62 | 43 | 0.183 |
| calibrated | 16.5% [11.9, 22.5] | 31 | 1.57 | 2 | 0.215 |
| fallback | 16.0% [11.6, 21.7] | 32 | 1.67 | 4 | 0.213 |
| **backfill** | **17.8% [13.3, 23.5]** | **38** | **1.77** | **4** | **0.242** |

**Predictions 1 to 4 held; prediction 5 failed.**

1. Backfill found more applying lessons than calibrated: 38 against 31.
2. Backfill's precision, 17.8%, was above the floor's 9.8% and floor-3's 12.1%.
3. Backfill had the highest F1 of the five arms.
4. Backfill briefed something on 4 of the 60 null prompts.
5. Fallback found one lesson more than calibrated, but its precision was 16.0% against 16.5%.
   So fallback does not ship, as the falsifier says.

**The gain is smaller held out than on tuning.** Backfill added 7 applying lessons over
calibrated here, against 20 on tuning. Its precision was 1.3 points above calibrated's, inside
both intervals; on tuning the gap was 9.8 points. Some of that is the calibrated arm doing
better held out (31 found, against 21). The choice holds, but the size of the step does not:
backfill lifted what the calibrated decision finds by 23% held out and 95% on tuning, and the
held-out figure is the one to plan on.

**What this says about the default, on a real store and real prompts.** Both halves agree:

- the calibrated decision briefs 15% to 20% as many lessons as the floor (1.07 against 7.23 a
  prompt on tuning, 1.57 against 7.69 held out);
- a lesson it briefs is about 1.7 times as likely to apply (16.5% against 9.8% in both halves);
- it surfaces a quarter to a third of the applying lessons the floor surfaces (21 of the
  floor's 85 on tuning, 31 of its 90 held out). §4w's "about a quarter fewer", measured on
  the seed corpus alone, understated that loss.

On F1 it beats the floor in both halves, which is the criterion this section fixed in advance.
A team that wants recall over precision has `--decision floor`.

**A correction (review on #298).** The prompt extractors removed duplicates before they left
out the harness's folders. Nine prompt texts were typed both in a harness session and by a
person; for seven, the harness copy was read first, so those labelled prompts were attributed
to a harness folder and left out of both pools: 7 of about 1,000. The extractors now skip
harness folders before removing duplicates. The receipts above stand on the files as
extracted; re-extracting would change the seeded samples.

**What follows.** As pre-registered, the calibrated default stays, without fallback. Recorded
lessons get triggers through a command an agent runs, and the briefing names how many of a
store's own lessons lack them. This machine's store gets the 1,390 triggers this section
measured.

## 4y. PRE-REGISTERED: two tiers, so the default hides no lesson that matched (2026-10-26)

Written before any tier arm was pooled, judged or sized.

**Why.** §4x's held-out half put every arm that briefs at most five lessons at 38 or fewer of
the 101 applying lessons in the pool, where the floor reached 90. The person who uses okl
ranks a missed lesson as the worse error. **This section therefore changes the criterion:**
§4x chose by F1, and this one chooses by reach, the applying lessons a briefing names, with
the briefing's size as the cost.

**Where the misses are.** On the tuning half's task prompts, backfill missed 76 of the 117
applying lessons. A count of where each one stopped (no labels used beyond §4x's):

| where the missed lesson stopped | lessons |
|---|---|
| among the candidates, below the line: one shared about-word | 34 |
| among the candidates, below the line: two shared about-words, both common | 23 |
| cleared the line, cut by the cap of five | 17 |
| among the candidates, no shared about-word | 2 |
| not among the candidates | 3 |

The search found 73 of the 76; the decision dropped them. §4t already showed that a
cross-encoder can order these candidates but cannot say which belong. So this section changes
what the decision does with a candidate it does not show: it names it instead of hiding it.

**The treatment: `decision: tiered`, the new default.** `core.check` runs the calibrated
decision and shows its lessons in full, at most five, as §4x's backfill arm did. It then
lists, in `also_matched`, what cleared the line past the cap, then what the word floor keeps,
each once and not already shown, at most `limit` (12). Each is one line: id, title, and the
first sentence of its fix, cut at a word to 160 characters. The list sits under "Also matched
(N), one line each. If one fits this task, read it with `okl show <id>` (the okl_get tool)
before you write code." The person's line names how many were listed. A listed lesson is not
logged as shown, as with the near misses (§4s).

**What was seen before this was written.** The composition "backfill in full, the floor's other
lessons by line" was computed from §4x's labels before this section existed. It reaches 101 of
the held-out pool's 101 applying lessons and 96 of tuning's 117, with 1.77 lessons in full and
6.64 lines per held-out task prompt. The treatment as built differs: its floor runs on the
store with the written triggers, which re-rank the full-text candidates, and it adds the cap's
overflow. So the held-out half is not blind to reach; the predictions are about the treatment
as built, and its new pairs are judged as before.

**Instrument.** `evals/bench/real_prompts.py` gains two arms through `pool --extend`: `tiered`
(every lesson it names, in full or by line) and `tiered-full` (only those in full). New pairs
are judged by Sonnet sub-agents, per lesson, blind to arm, as in §4x. `size` renders each
sampled prompt's briefing (the hook's text) under the floor, backfill and tiered, and reports
its size in tokens at four characters each.

**Predictions, on the held-out half's task prompts.**

1. Tiered reaches at least as many applying lessons as the floor. (The tier rule.)
2. Tiered-full briefs exactly what backfill briefs on every sampled prompt: the full tier is
   the calibrated decision on the same store. This checks the build, not the idea.
3. The median tiered briefing is at most 75% of the floor's. (An estimate from §4x's averages,
   made before sizing, put it near 60%.)

**Falsifiers and what follows.** If 1 fails, tiered is not the default: the floor is, since
reach is the criterion. If 2 fails, the build is wrong, and nothing is decided until it is
fixed. If 3 fails, the line drops its fix, as §4s's near misses did, and the size is measured
again; reach does not change. The null prompts are reported, not predicted: the second tier
names lessons on about as many of them as the floor briefs, by design.

**What this cannot settle.** Reach counts a lesson that was named, not one that was read or
followed. Whether an agent acts on a one-line mention as it does on a full lesson is the next
measurement. It will be pre-registered separately, before any agent runs.

### Result (2026-10-26)

Receipts, all at fd96d79: `real-20261026-heldout-tiers.txt` and `real-20261026-tuning-tiers.txt`
(the tallies; the tier arms' new pairs, 192 held out and 139 on tuning, judged per lesson by
Sonnet sub-agents with no label missing), `real-20261026-heldout-size.txt` and
`real-20261026-tuning-size.txt` (the sizes), and `briefing-size-20261027-0132.json` (the one
representative task the docs quote).

**All three predictions held.**

1. Held out, tiered reached 102 of the pool's 115 applying lessons; the floor reached 90. On
   tuning: 95 of 124 against 85.
2. Tiered-full briefed exactly what backfill briefed, in the same order, on all 180 sampled
   prompts of each half.
3. The median tiered briefing on held-out task prompts was 721 tokens, 51% of the floor's
   1,424. On tuning: 614, 54% of 1,133.

| held-out task prompts (120) | applying reached, of 115 | in full | by line | named per prompt | in full per prompt | median tokens |
|---|---|---|---|---|---|---|
| floor | 90 | 90 | 0 | 7.69 | 7.69 | 1,424 |
| backfill (the calibrated decision, with triggers) | 38 | 38 | 0 | 1.77 | 1.77 | 113 |
| **tiered** | **102** | 38 | 64 | 9.08 | 1.77 | 721 |

**The pool grew.** The tier arms found 14 applying lessons that no §4x arm had found. The
floor inside tiered runs on the store with the written triggers, which re-rank the full-text
candidates, so it keeps a different twelve. §4x's figures stand on their pool of 101. On this
pool of 115, every arm's share reads lower: the floor's 90 is 78% here and was 89% there.

**Where tiered still misses.** All 13 applying lessons it did not name (held out; 8 recorded, 5
from the packs) were among the floor's lessons on the store without triggers. The same
re-ranking moved them out of the twelve the second tier draws from. A larger second tier would
reach some of them; that is a choice to make on the tuning half, with its size measured.

**Precision and size.** Of everything tiered names, 9.4% applies, about the floor's 9.8%. Of
what it shows in full, 17.8% applies, exactly backfill's. The floor's noise now sits in the
one-line tier. A line costs about 64 tokens (from the size receipts' means: (816 − 351) / 7.31),
against about 160 for a lesson in full under the floor.

**Null prompts.** Held out, tiered names something on 43 of 60 null prompts, the same 43 the
floor briefs, and shows a lesson in full on 4, as backfill does. A median null prompt costs 362
tokens under tiered, 629 under the floor and 72 under backfill. That is the price of naming
everything that matched: one-line entries on prompts that ask for no work.

**What follows.** As pre-registered, tiered becomes the default. `calibrated` stays available for
the smallest briefing, and `floor` for every match in full. Whether an agent acts on a one-line
entry as it does on a full lesson is the next measurement, to be pre-registered before it runs.
The release waits for it.

## 5. Findings

1. **The briefing works, in both tiers.** Sonnet: 33% → 4%. Haiku: 38% → 12%. Every
   task the sonnet baseline failed was fully prevented except one residual
   (judge_summary 1/3). *Note, 2026-10-10:* "fully prevented" held in no 3-sample run
   after that one. spa_tokens is reduced, not prevented: 35/43 → 20/43 (81% → 47%) across
   the 16 receipts that include it, and 29/37 → 15/37 on the receipts the aliases name as
   sonnet generator and haiku judge (the pool `tests/test_docs.py` recomputes). §4o's run
   among them resolved those aliases to different models and starts its own series, so on
   the earlier models alone the figure is 26/34 → 14/34. The 16 include §4j's run, where it
   read 0/2 → 0/3, §4k's, 1/3 → 1/3, §4l's, 1/3 → 1/2, §4m's, 2/3 → 1/3, and §4o's, 3/3 → 1/3
   (updated 2026-10-22).
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
7. **The pooled figure (added 2026-10-12; recut 2026-10-23).** Over the seven committed
   runs on the documented instrument (sonnet generator, haiku judge, eight tasks with
   three samples per arm) from §4 through §4h, 68 of 163 unbriefed attempts reproduced a
   known defect (42%) against 11 of 164 briefed ones (7%). The seven receipts:
   `ab-20260830-0003`, `ab-20260901-0133`, `ab-20260901-1238`, `ab-20260902-0538`,
   `ab-20260903-0157`, `ab-20260903-1214`, `ab-20260903-1323`.
   Three earlier receipts on the same models are outside the pool because they are not
   eight-task, three-sample runs: `ab-20260829-2300` (two tasks, one sample),
   `ab-20260829-2315` (eight tasks, one sample) and `ab-20260902-1216` (one task,
   `idor_endpoint`, one sample, 0/1 in each arm), which no other section names.
   Denominators fall short of 168 because failed and unevaluable samples are left out.
   The pool keeps §4d's run (`ab-20260902-0538`), whose retrieval change was reverted:
   its briefed arm read 3 of 23, so keeping it raises the briefed rate. Without it the
   pool reads 58 of 141 (41%) against 8 of 141 (6%). The launch posts of 2026-10-12
   quoted this pool with §4i's run (`ab-20260926-0528`) added: 78 of 186 (42%) against
   13 of 188 (7%), the same percentages. §4i pre-registered its layout change as a new
   series, and its pre-flight shows that every record's content survived the new layout,
   not that the briefings were identical, so from 2026-10-23 that run is reported beside
   the pool rather than in it (review on #265). It leaves out §4f (judged by opus,
   not the documented instrument) and every run from §4j on, because each of those
   started a new series (§4j's unbriefed arm moved 26 points with nothing changed; §4k
   and §4m changed the instrument). For reference, the aggregate over all thirteen receipts
   that the alias and run-shape filters select, those included, reads 108 of 304 (36%)
   against 17 of 305 (6%), leaving out §4j's plan-only sample as §4j itself does; it spans
   several model series (§4o's among them), so it is an alias-selected aggregate, not a
   comparable-series estimate. Read it with §6: one-shot
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
