# One lesson at a time

*Part 9: what happened when a lesson was handed to a coding agent alone, in a list, and one at a time. The canonical copy is on [emeraldleaf.dev](https://emeraldleaf.dev/writing/one-lesson-at-a-time/); the measurements are in [REPORT §4aw to §4bc](../../evals/REPORT.md) and the method in [the methods paper](https://emeraldleaf.dev/writing/okl-evaluation-methods/).*

okl keeps a coding agent true to a team's rules, specs and docs, and keeps those true to the code. It holds each of them as a lesson: a rule, a decision, a convention or a claim a doc makes. [Part 8](08-finding-the-lesson-was-the-easy-part.md) ended with the evidence pointing at the half of okl that checks lessons rather than the half that shows them, and with a test still to run on real work, graded without a model as judge: when the right lesson is in front of an agent, does the code it writes come out different?

It does, when the lesson stands alone. In a list of ten, the same lesson mostly did nothing. Asked about one at a time, the same ten did as well as the lesson alone. I rebuilt okl's review after writing on that. It ships in 0.16.0, off by default, because it did not clear the bar I set, and the largest gap left is choosing which lessons to check.

## The test

Past defects are where a lesson's effect can be graded, because the real fix says what the right answer was. They are the test bed, not the point. I took five changes from okl's own history where review later caught a defect that an existing lesson already described. In one, an eval script would start a run whose judge was the same model as the one it grades, named two different ways, and the lesson says a judge must be a different model.

Each task restarts from the change as first written, before review caught the flaw, in a clean copy with no agent files. The agent, Sonnet, is asked to get the change ready to merge. A grader it never sees checks what the code it leaves behind does. Every arm runs five times per task in one seeded order, and the bar for each reading was written down before any session counted. [The methods paper](https://emeraldleaf.dev/writing/okl-evaluation-methods/) has the procedure in enough detail to rerun on another project's history.

Part 8 said the grader would be the test the real fix added. It could not be: four of the five called a function the real fix had invented, so no agent could pass them without guessing its name, and the filter I had written to catch exactly that read an empty line and caught nothing. I replaced those four with graders that check what the lesson asks, written after the sessions ran and before any was graded by them (§4aw).

## Alone, a lesson changes the code

With no lesson, the agent fixed none of the five, in any of 25 sessions. It left every change as it found it and called it ready. Given the right lesson, and told the lesson bears on the change, it fixed most of them, with a pass rate of 0.64 averaged over the tasks (§4aw). That is the first evidence I have, on real past defects, that a lesson in front of an agent changes what it writes.

The same test checked the format Part 8 proposed. Rewritten as a small contract (when it applies, what to do, when it is done, when it does not apply, and why), with or without worked examples, the lesson did no better than as stored. On these tasks wording was not the bottleneck, so the format stays as it is.

## In a list of ten, it mostly did nothing

That setting was generous. The agent had one lesson, the right one, and a sentence saying it applied. A real briefing gives neither. So I put the same lesson among nine others, the ones okl's search ranks highest for the task's words, with and without that sentence (§4ax).

Alone, the pass rate was 0.6 with the sentence and 0.6 without. In the list of ten it was 0.2 without the sentence and 0.12 with it. The sentence made no difference alone and did not rescue the list. In the list the agent mostly did nothing: it edited in 16 of 50 sessions, against 39 of 50 alone. It read ten lessons, found no reason to act on any, and called the change ready.

Part 8 began with lessons a briefing showed being followed no more often than lessons it did not show. This is a likely reason: a briefing is a list.

## One at a time, it worked again

If being one of ten is what costs, the remedy is to hand lessons over one at a time. The risk is the other nine, which mostly do not apply: an agent asked about each might invent problems to fix. So I asked about the same ten lessons one at a time, each in a fresh session after the code was written: if the change breaks this lesson, fix that; if not, change nothing (§4ay).

One at a time passed 0.72, level with the right lesson alone in the same sitting. The list, re-run as the control, passed 0.08. The other nine lessons produced an edit in about one pass in nine, and no session broke another test in the grader's file. The cost of a list was in how the lessons were handed over, not in the lessons.

Across three sittings the lesson alone passed between 0.6 and 0.72, and the list between 0.08 and 0.2. Five repeats on five tasks move around; the gap between the two stays large.

The catch is cost. Ten fresh sessions cost about seven times as much as one, and took about six times as long.

## The review after writing, rebuilt

Part 8 introduced the step this calls for. `okl check --change` runs after the code is written: it lists the changed files and every lesson in scope, one line each, and has the agent pick the ten its change most likely breaks and check the code against them. Until now the agent checked all ten together, the shape §4ax found weak. Now it checks each lesson in its own fresh sub-agent, one lesson and one question each.

Every test so far had handed the agent a set that held the right lesson. The real review has to choose its own, from the 280 to 300 lessons these tasks could see. So I ran it end to end against no review and the old review, with the bar for turning it on by default written first (§4az).

The old review fixed none in its 25 sessions. The new one fixed 5 of 25, and no session broke another test in the grader's file. It is the better review, and not yet good enough to be on by default: the bar asked for 0.25 above no review, and it came out 0.2 above. Four of its five fixes were on one task, #198, the one whose lesson okl's search ranks first for the task's own words; the fifth was on #115. It costs 2.6 times the old review.

So in 0.16.0 the review after writing checks each lesson on its own, and stays off unless you turn it on for a repository with `okl init --review-after-writing`. The release also carries the checks Part 8 described for the most-broken lessons ([#415](https://github.com/emeraldleaf/okl/issues/415)), which fail the build whether or not the agent noticed.

## Finding the lesson was not the easy part after all

Part 8's title said finding the lesson was the easy part. Once handing it over worked, finding it was what was left. Run as it ships, from each task's own words, okl's briefing showed the right lesson in full on one of the five tasks, named it in one line on another, and did not show it on the other three (§4ax). Three tests then measured choosing:

- **From the task, a plan or the finished change (§4ba).** A model given every lesson's one line named ten. From a plan or the change, the right lesson was in its ten about half the time, and less often from the task's words. A plan written before any code chose as well as the finished change, so choosing need not wait for the code, but the plan missed the bar I set for it.
- **A line saying when each lesson applies, by mechanism (§4bb).** It raised the hit rate by 0.1 on average, under the 0.15 I asked for, and nearly all of that came from one task.
- **Choosing from the code (§4bc).** On 58 earlier changes, with 124 lessons they broke between them, I pooled the model's pick with three lists built from the code, then had Haiku screen each pooled lesson on its own. The screened set held 0.112 more of the broken lessons than the pick, under the 0.15 asked, at 22.1 lessons where the bar allowed 12, and part of that gain was built in, since the pool contained the pick's own list. Asked whether a change does something a lesson is about, Haiku said yes to most.

Two of the five bugs were never found. No picker put their lesson in its ten, from any starting point, in any repeat, with or without the lines, and the review fixed neither. In one, the lesson says an audit must read the committed files rather than the working folder, and the change was an eval script that loaded every pack in a folder, so a pack never committed could reach the measurement. A lesson is often written about the incident that taught it, and a line written from the lesson alone cannot know which other code shares its mechanism.

Choosing explains most of the drop from 0.72 to 0.2, and perhaps all of it. A review that lost only in choosing, with the right lesson in its ten about half the time and fixed about three times in four when it is, would land between 0.2 and 0.4, depending on which sitting's rates for each task are paired, since with five repeats a task those rates swing from one sitting to the next (§4ba). The review's 0.2 is at the bottom of that range. Something else may cost as well: one session gave its sub-agents only part of the change (one read just its first 400 lines), and a trial session before the count stopped after three of its ten. How often that happens is not yet measured.

## What this means for your rules file

These come from five tasks in one repository, so treat them as hypotheses to test on your own history. For any rules file an agent reads, they point one way. A rule changed the agent's code when it reached the agent on its own, at the moment it applied, and it has to still match the code: the research I read for Part 8 found agents following a stale instruction file over the code in front of them. A long file loaded at the start of every session is the list of ten, longer, and each rule added to it dilutes the rest. A rule backed by a check does not need to be noticed at all. [The methods paper](https://emeraldleaf.dev/writing/okl-evaluation-methods/) has the full list and what each point rests on.

## What is next

Each of these needs its own pre-registered test before it can be on by default.

- **Run a lesson's check when the agent edits a file it governs** ([#435](https://github.com/emeraldleaf/okl/issues/435)). A lesson can already name its files and carry the command that proves it, but the command runs only when someone runs `okl verify`; the gates notice only that a governed file changed. Run at the edit, with any failure handed straight back, a lesson no longer competes for attention in a list.
- **Point lessons at real gold-standard code** ([#436](https://github.com/emeraldleaf/okl/issues/436)). A lesson in one repository would name a real file or function to imitate, watched like the files it governs; a lesson shared across repositories would carry a checked example in its pack. Written examples did not beat the plain lesson in §4aw. A pointer to real code is a different treatment, and untested.
- **Ask-first files** ([#437](https://github.com/emeraldleaf/okl/issues/437)). A lesson could mark the files it governs so that an edit to one asks the person first, with the lesson as the reason.
- **Better choosing.** A screen that asks the review's own question (does this change break this lesson?) or uses a stronger model, the pooled list cut to the review's ten, and a cheaper shape for one at a time, such as several lessons to a fresh context, each tested on changes no arm here has seen.

## Limits

Five tasks, all from okl's own repository, picked by Opus after reading the tests and picked because a lesson applies, so they say how an agent responds when a lesson applies and nothing about how often one does. One agent model, Sonnet, at one date. Five repeats a task, so a single task's swing cannot be told from noise. The 58 changes in §4bc are scored against a model's answer key that no person has audited yet. Each result decided what to test next; none is an effect size for agents in general. The test on other projects' histories, with human labels, is [#413](https://github.com/emeraldleaf/okl/issues/413).

## What held

Part 8 ended at the half of okl that checks lessons, and this work came back to it from the other side. A lesson changed an agent's code when it was the only thing in front of the agent. A lesson backed by a check gets that by construction: when the code it covers moves, the gate holds the push until the check passes again. That is the case for turning the most-broken lessons into checks. For lessons no script can check, the review in 0.16.0 does the next best thing, one lesson at a time. Choosing which ones is the work now.
