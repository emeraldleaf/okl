# ADR: The review after writing is on by default

- **Status:** Accepted (2026-11-14), shipped in 0.17.0
- **Decided by:** the maintainer, as a judgement on the evidence below, not by a pre-registered bar.
  Both bars the review was tested against were missed, and this record says why it is on anyway,
  so that a later reading of "missed its bar" does not quietly turn it off again.

## The decision

The review after writing (`okl check --change`) runs by default wherever okl was set up (a
`.okl/config.json` exists). In Claude Code, the Stop hook asks for it before a session that
changed files ends. The agent picks the ten lessons its change most likely breaks, checks each in
a sub-agent of its own, and fixes what breaks one. A repo turns it off with `okl init
--no-review-after-writing`, and `OKL_REVIEW_AFTER_WRITING=0` skips it for one session.

## Why: a list of lessons rarely changes code, and the review is the only step measured to

Every figure here comes from replaying past defects of this repository, graded on what the code
does ([REPORT](../../evals/REPORT.md)).

1. **A lesson given alone changes the code.** With no lesson, the agent fixed none of five real
   defects. With the right lesson alone, it fixed them 0.6 to 0.72 of the time (§4aw, §4ax, §4ay).
2. **The same lesson in a list of ten mostly does not.** It fixed them 0.08 to 0.2 of the time,
   and telling the agent the list bears on its change did not help (§4ax, §4ay). The agent read
   all ten and called the change ready.
3. **The briefing is a list.** That is the likely reason lessons shown in a briefing were followed
   no more often than lessons not shown (§4as).
4. **How the list is worded is not the cause.** Asked to check the same ten in turn in one session,
   the agent wrote a verdict for every lesson and fixed 0.2. In 8 of the 9 sessions it failed on
   tasks one at a time nearly always fixed, it named the right lesson and dismissed it in one line
   (§4bg, exploratory).
5. **One lesson at a time, in a fresh session after the code exists, works.** The same ten asked
   that way fixed 0.72, as well as the right lesson alone (§4ay). That is the review's shape.

So without the review, a lesson reaches the agent and mostly does not act, unless a check enforces
it. Off by default, okl would run the half that measurably does not change code and hide the half
that does. On top of that, the maintainer judges a missed lesson to cost more than the review's
sessions.

## What it costs

On five past bugs, a session with the review cost $0.73 API-priced on average against $0.11 with
none, about 6.9 times, and took a median of 214 seconds against 160 (§4az, receipt
`review-e2e-20261111-1543.json`). Every user pays that on every session that changes files,
unless they turn it off.

## The gap this does not close

The review works when the right lesson is among the ten it checks, and the agent's own pick puts it
there less than half the time: the pick held 0.47 of the broken lessons across 58 past changes
(§4bc). End to end, picking its own lessons, the review passed in 0.2 of its sessions (5 of 25, on
2 of 5 bugs) where no review passed in none (§4az). Its reach was 17.4% of the broken lessons
against a 30% bar (§4au). It is the only measured step that turns lessons into changes, and today
it runs at roughly a quarter of what it does when the right lesson is in its ten. All of this rests
on five replayed tasks from one repository.

## What would reverse it

Turn it back off by default only on evidence, not because it missed a bar; it missed both when it
was turned on. Any of these would justify it:

1. **A decisive test shows no gain.** On a task set large enough for 0.8 power (#457), a
   pre-registered comparison of the review against none finds the 95% interval of the gain below
   0.1.
2. **Real use shows it rarely acts.** If okl logs each review's outcomes and, across real
   sessions, the review almost never changes code while costing what §4az measured, the case
   here weakens.
3. **The cost drives people off.** If on-by-default leads users to remove okl, a default that
   loses the whole loop costs more than the misses it prevents.

## What follows

- **Better reach for less:** a cheaper model per checked lesson, so the review can check more
  lessons than ten (#456).
- **Lessons with checks skip the pick:** an approved check runs after every edit (`okl on-edit`,
  0.17.0), and a lesson with a check needs no picking.
- **A task set large enough to decide:** #457.
- **Drift by omission:** the docs failed to mention this behaviour until a person noticed (#455).

Related: REPORT §4at to §4bg; `docs/COSTS-AND-KNOBS.md`; issues #447, #450, #455, #456, #457.
