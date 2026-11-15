# Plan: making the review after writing earn its default

- **Status:** In progress, started 2026-11-15. Piece 3 is built in #464, and is true once that pull request merges.
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
| 3 | Log what each review does in real use, and report it | built in #464, below as it ships |
| 4 | Grow the graded replay set to about 40 tasks | built for #457: 43 broken tasks, checked against blind alternatives, with power at that size (REPORT §4bi); no run on them yet |

Parked: whether a cheaper model can check one lesson as well as Sonnet (#456). That is a cost
question only, worth testing once piece 4 makes a test decisive.

## Why

**The review is the only step measured to turn lessons into changes.** A lesson given alone in a
fresh session after the code exists fixed past defects 0.72 of the time (REPORT §4ay). The same
lesson in a list of ten did 0.08 to 0.2 (§4ax), and asking the agent to check the ten in turn in one
session did 0.2 (§4bg). That is why the review is on by default.

**But it reaches that result only when the right lesson is among the ones it checks.** Picking its
own ten, end to end, it passed 0.2 of its sessions (§4az). Each piece of this plan answers one gap:

1. **The ground truth under the picking results is unvalidated.** §4bc's "the pick holds 0.465 of
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
sub-agent under `~/.claude/projects`. okl's Stop hook already reads the main transcript (`okl recap
--transcript`).

**When.** In Claude Code, at each stop after the first. The Stop hook blocks only the first stop;
at every later one it runs `okl recap --transcript <path> --log-review`, silently, cut off after about
five seconds, so a slow or failing read never delays or blocks a stop. The row is replaced each time,
since the transcript has grown.

**What counts as the review.** A note asks for one review: the first command that ran `okl check
--change` after it and before the next prompt a person typed (a grep, an echo or a commit message that
names it is not a run). A prompt first means the request was skipped, and with several notes in a
session the row describes the last. A run before the note reviewed another state and is dropped. The
review ends at the next typed prompt, or at a Stop-hook summary at which none of the review's
sub-agents is still running. Claude Code returns every Agent call at once and the agent stops to wait
for its notification, which arrives as a user line, a queued command, a task status or a queue
operation, so a review of three lessons stops three times and is not over. Tokens, time and sub-agents
are counted inside that window, and a sub-agent's own lines up to its end. An Agent call that came
back as an error started nothing and is no check.

**What it records,** in the store, one row per session and repo, replaced when the session is logged
again:
- the session, repo and time;
- whether the review was asked for and whether it ran;
- the files changed and the number of lessons listed, from the review's own output;
- each sub-agent the review started, with its model, the lessons it was given or opened, whether it
  edited anything in the repository and which files, a count of the edits elsewhere, the tests it ran
  (a runner name, paths that exist in the repository, and the outcome), and its tokens;
- the review's tokens and duration, and how many Agent calls came back as an error. Tokens are the
  work (input, output and cache creation); the cache reads, which dwarf it and cost far less, are
  kept apart in the row and in each check, and the report says so.

No code, command line or text from the session is stored: only ids, paths, counts and model names. The
row goes where the store is: `.okl/okl.db` by default, and a shared database if `OKL_DATABASE_URL`
names one. A shared service refuses the log. Nothing is sent to a model, and the row leaves the
machine only if the store is elsewhere.

**When it writes nothing.** Where the review after writing is off for the repo, where
`OKL_REVIEW_LOG=0` (or `review_log: false` in `.okl/config.json`) turns the log off, in a directory
never set up with `okl init` (a store URL exported does not enroll it), and for a session that neither
asked for the review nor ran it.

**What it reports.** `okl recap --reviews`:
- reviews run, against sessions that changed files, and reviews asked for and skipped;
- lessons checked per review;
- the share of checks that led to an edit in the repository;
- cost per review;
- per lesson, how often it was checked and how often that led to an edit.

**What it cannot say.** An edit after a check means the review *acted*, not that it *caught*
something: the log cannot tell whether the edit fixed a real break. The report says so in those
words. It covers Claude Code sessions only, since other agents leave no transcript okl can read.

**How it is tested.** Synthetic transcripts in the shape Claude Code writes: a review with
sub-agents, one without, one whose checks edited and one whose did not, a review that stops and resumes
once per lesson, a run before the note, a note with no review after it, a prompt that ends the
window, a sub-agent resumed afterwards, a skipped review, and a transcript that cannot be parsed. Tests
that the hook stays silent and inside its time limit and leaves nothing running when the read fails, and
the mirror and fingerprint updates the repo's rules require.

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
