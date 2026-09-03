# The elegant change was the wrong one

*Part 4 of 3: The loop that learns. What happened when the method was pointed at the tool that implements it.*

I built a thing that tells you to verify your claims mechanically, then spent a day running it against itself. It found nineteen defects. This is about what they had in common, and about the one that survived every check I had.

## Everything that broke had never been run

The MCP server could not start. The library it depends on had renamed the class it imports, so `pip install` produced a server that failed on load, and the error handler told you to install the extra you had just installed.

The Postgres path had never touched Postgres. The schema was right, the queries were right, and the parity test I wrote to prove it opened with `DELETE FROM node` against whatever database you pointed it at. Anyone running it against their real store to check parity would have lost everything in it.

The shared service, deployed, answered 500 to every request. The ASGI entrypoint documented in its own docstring resolved to a module-level `None`. The process started, bound its port, and passed a liveness check that only asked whether something was listening.

And the token that gated writes did not gate reads, so `GET /nodes` handed the entire store to anyone who found the URL. For a knowledge layer that is not a minor leak. The store is a catalogue of the places an organisation already knows it is weak.

Four failures, one shape. Each lived in a surface nobody had ever exercised. Not badly written, not under-reviewed. Unrun. The defects clustered exactly where you would predict if you were being honest with yourself, which is the least surprising distribution in software and somehow always a surprise.

## The one that was carefully reasoned

Late in the day I found a real problem. Briefings in a Python repository were full of .NET rules. The vocabulary already separates *stacks* from *subjects*, so the fix looked obvious: a record naming a stack should only reach a repository that declared that stack, while subject tags stay permissive. One universal subject was rescuing every off-stack record into every project.

I implemented it. It passed its tests. It passed the architecture review. The reasoning was drawn from the system's own documented distinction, and I wrote three paragraphs of commentary explaining why it was correct.

Then the A/B measured it, and the briefed arm posted its worst result across four runs.

The cause took ten minutes to find and was not subtle once seen. One rule reads *"in-memory rate limiters silently weaken to N times the limit at N instances."* It is tagged `dotnet`. It is also true of every runtime ever written. The tag records where the lesson was **found**, not where it **applies**, because tags get assigned in bulk when a corpus is imported from a codebase. My filter read provenance as applicability and hid 35 of the 172 records in the store at the time, including an IDOR rule, a data-transposition defect, and the rate-limiter rule itself. The generated code then reproduced the exact defect the hidden rule described, on a task where the unaided arm reproduced nothing.

Most of the records tagged `dotnet` in that store are portable engineering lessons. I will not put a percentage on it, because the only way I have to classify them is keyword matching on their titles, and the answer moves by twenty points depending on which words I pick. That is the sort of number this series is about not quoting. The unambiguous cases are enough: an IDOR rule, JWT clock skew, fanout exchanges discarding unroutable messages, time-ordered primary keys. None of those is about .NET, and no amount of reading the filter's code would have told me, because the code was doing precisely what I designed it to do.

## Reasoning is not evidence, and review is not measurement

That change had everything except a measurement. It had a rationale, a test suite, a passing review, and a comment block. What it did not have was a number, and the number was the only thing that disagreed with it.

The uncomfortable part is the ranking. Of the nineteen defects, the four unrun surfaces were the easiest to find, because running them was enough. The carefully argued one needed a controlled experiment to catch, and I would have shipped it as an improvement.

There is a corollary I like less. Reverting was correct, but doing it in that order was not. The change should never have run without a written prediction and, more usefully, a list of which cases could plausibly lose a record they depend on. That list would have named the failing task before the experiment started, for free.

## The cheapest check was the one nobody was running

Whether a record reaches a briefing is deterministic. It needs no model, no samples, and no judge. It is a query.

Two separate regressions were each discovered only after a full run: twenty-five minutes and forty-eight model calls, to learn something a database could have answered instantly. So now a pre-flight asks it directly before anything is spent: for each case, is the rule it exists to test actually present in the retrieval it will receive?

The first time it ran, it found that two of eight cases had not been receiving their rule at all. One was filtered out by a tag the host repository never declared. The other had been silently dropped by a relevance cutoff added weeks earlier, in a change whose own report concluded it caused no retrieval miss. That conclusion had been drawn from outcomes rather than from asking the question. The case still looked healthy, because something else in the briefing happened to prevent the defect. It was never evidence for the rule it was filed under.

That correction is in the report now, above the section it corrects.

## What I would take from this

Untested surfaces contain defects in proportion to how untested they are, and that is boring and cheap to fix: run them. The expensive lesson is the second one.

The changes most likely to be wrong are the ones you can argue for best. A change with a clean rationale, a green suite, and an approving reviewer has passed every filter except contact with reality, and the more elegant the argument, the more of your judgment it has already borrowed. So decide in advance what would falsify it, write that down where you cannot revise it later, and make sure the cheap deterministic check runs before the expensive stochastic one.

None of that is a new idea. What was new to me was watching it fail on the tool built to enforce it, in a session where I was actively looking.
