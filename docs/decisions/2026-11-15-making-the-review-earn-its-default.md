# Plan: making the review after writing earn its default

- **Status:** In progress, started 2026-11-15
- **Follows:** [The review after writing is on by default](2026-11-15-review-after-writing-on-by-default.md),
  which turned it on by decision while it missed both of its measured bars. This plan is the work
  that decides whether that decision holds, and how the review gets to the result it shows when the
  right lesson is among those it checks.

## What

Four pieces of work, in this order:

| | what | where it stands |
|---|---|---|
| 1 | Settle the answer key: a person labels the key's pairs blind | the page is ready; waiting on the maintainer's labels |
| 2 | Run the review's checks on the model it was measured with | done in #463: Sonnet, in Claude Code |
| 3 | Log what each review does in real use, and report it | designed below; #464 |
| 4 | Grow the graded replay set to about 40 tasks | #457 |

Parked: whether a cheaper model can check one lesson as well as Sonnet (#456). That is a cost
question only, worth testing once piece 4 makes a test decisive.

## Why

**The review is the only step measured to turn lessons into changes.** A lesson given alone in a
fresh session after the code exists fixed past defects 0.72 of the time (REPORT §4ay). The same
lesson in a list of ten did 0.08 to 0.2 (§4ax), and asking the agent to check the ten in turn in one
session did 0.2 (§4bg). That is why the review is on by default.

**But it reaches that result only when the right lesson is among the ones it checks.** Picking its
own ten, end to end, it passed 0.2 of its sessions (§4az). Each piece of this plan answers one gap:

1. **The ground truth under the picking results is unvalidated.** §4bc's "the pick holds 0.47 of
   the broken lessons", §4bd's "0 of 124 caught" and §4be's counts all score against a model's answer
   key. In the audit, a second model agreed with only 4 of the 12 pairs that key called broken
   (§4bh). Until a person labels them, nobody knows whether picking is as weak as those sections
   say.
2. **The review ran on whatever model the session used.** Its evidence is all Sonnet. An Opus
   session started ten Opus sub-agents and cost more than measured; a smaller model was never
   tested.
3. **The only evidence the review acts comes from five replayed tasks.** Every session that changes
   files now runs one, and what it did is lost when the session ends. The decision record's second
   condition for turning it off, real use showing it almost never acts, cannot be checked without
   this.
4. **Every decisive test is short of tasks.** In §4az the review's whole gain sat in one task of five,
   and a gain that concentrated needs many tasks to be found. On the 14 graded tasks there are now,
   a test of the review against no review would be a pilot, and the evaluation standard does not
   let a pilot set a default.

## How

### 1. Settle the answer key

The 30 answer-key pairs the audit drew (12 the key called broken, 12 followed, 6 related) sit on the
private audit page, shuffled, with nothing showing what the key said, so the labels stay blind. The
maintainer labels each with the key's own question: *did this change need this lesson, and did it
follow it?* `evals/audit_sample.py score` scores the labels against the key under the bar committed
with the draw (broken precision at least 0.8).

- **If the key holds,** §4bc to §4be stand, and picking is as weak as they say. The work that
  follows is better picking, and pieces 3 and 4 measure it.
- **If it does not,** those sections are corrected with dated notes, the figures citing them are
  changed (the README, the decision record, the site's methods page and two posts), and §4bd's
  reading changes: some of the 124 were not broken, so there was nothing for a check to catch.

### 2. The review's model

Done in #463. The review's step tells a Claude Code agent to start each sub-agent on Sonnet (the
Agent tool's `model: sonnet`), with the reason. The cost then matches what §4az measured, whatever
model the session runs on.

### 3. Logging what each review does (#464)

**Where the evidence is.** okl calls no model: the agent runs the review, and okl prints the steps
(`okl check --change`) and serves lesson texts (`okl show`, `okl_get`). The whole review is visible
only in the session's transcript, which Claude Code saves locally for the session and for each
sub-agent. okl's Stop hook already reads the main transcript (`okl recap --transcript`).

**When.** At the session's last stop, in Claude Code. Its Stop hook blocks only the first stop and exits early after
that; before that early exit it runs `okl recap --transcript <path> --log-review`, silently and with
a time limit, so a slow or failing parse never delays or blocks the stop.

**What it records,** in the local store, one row per review:
- the session, repo and time;
- the files changed and the number of lessons listed;
- each lesson checked, with its sub-agent's model, whether that sub-agent edited anything, and the
  files it edited;
- the tests the review ran, and their result;
- the review's tokens and duration.

No code or text from the session is stored: only ids, paths and counts. Nothing leaves the machine.

**What it reports.** `okl recap --reviews`:
- reviews run, against sessions that changed files;
- lessons checked per review;
- the share of checks that led to an edit;
- cost per review;
- per lesson, how often it was checked and how often that led to an edit.

**What it cannot say.** An edit after a check means the review *acted*, not that it *caught*
something: the log cannot tell whether the edit fixed a real break. The report says so in those
words. It covers Claude Code sessions only, since other agents leave no transcript okl can read.

**How it is tested.** Synthetic transcripts: a review with sub-agents, one without, one whose checks
edited and one whose did not, a skipped review, and a transcript that cannot be parsed. Plus a test
that the hook stays silent and inside its time limit when the parse fails, and the mirror and
fingerprint updates the repo's rules require.

### 4. Growing the graded replay set (#457)

The 14 graded tasks of `evals/replay-tasks-4bg.json` came from §4bc's 58 labelled changes. The rest
follow the same procedure:
1. screen each candidate's grader at the frozen and fixed commits;
2. write behaviour graders with positive controls;
3. check each grader against a second right fix and a wrong one, written by an agent that has not
   read the graders;
4. redact each lesson's mentions of its own fix;
5. build each task's list of nine other lessons.

Then re-run the power simulation at the new size, before any test uses the set. No model sessions
are needed to build it, only agent work.

## What would change this plan

- **If the key labels show picking is fine,** the review's gap is elsewhere, and the plan's weight
  moves to piece 3's real-use evidence.
- **If real use shows the review almost never acts,** the decision record's second reversal
  condition is met, and the default is reconsidered on that evidence.
- **If a decisive test on the larger set shows no gain,** the first reversal condition is met.

Related: REPORT §4at to §4bh; [EVALUATION.md](../EVALUATION.md); issues #426, #455, #456, #457, #464.
