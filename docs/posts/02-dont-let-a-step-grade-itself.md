# Don't let a step grade itself

*Part 2 of 3: The loop that learns. How one developer's AI loop remembers, verifies, and enforces.*

Never trust an exit code. Most engineers learn that rule from one specific incident, and this was mine.

A pipeline step was supposed to materialize 238 files. It produced none. Every window raised, the exceptions were swallowed inside a worker pool, and the process exited zero. Downstream steps ran happily against an empty directory. The fix was trivial once seen: count the outputs rather than read the exit status. The discipline it bought has outlasted the project: a step reporting success and the work being done are two different facts, and only one of them is evidence.

That rule matters more when an agent is writing the steps. Review catches a lot, but review is sampling. What makes generated code safe at volume is the checks that run whether or not anyone is paying attention, and those checks are only as good as the question they actually ask.

## The same bug wears several costumes

A dependency's major-version upgrade compiled clean and carried three runtime breaking changes, one of which silently broke transactional atomicity. The build was green. Green answered "does this compile," which was not the question anyone cared about.

In an eval harness, an LLM judge printed a perfect 5.0 out of 5.0 while 19 of 20 cases had crashed, because it averaged the survivors. The score was real. It was also meaningless, and nothing in the output said so.

Different costumes, same failure: the verifier reported on itself, and the report was wrong.

## The grader is usually ls, not an LLM

When I say don't let a step grade itself, people sometimes hear "put a second model in front of every step." Almost never. The correct grader for the 238-file failure was a file count. The correct grader for the upgrade was an integration test that forced a rollback and asserted no event escaped. Boring, deterministic checks, placed at the boundaries where the loop makes a decision: mark done, merge, deploy.

A second model earns its place in exactly one case: when the verify signal is itself a judgment, like scoring summary quality or reviewing generated code. Only there does judge-must-differ-from-generator apply, because a judgment shares blind spots with whoever produced it. A file count has no blind spots.

## Four rungs of independence

In the knowledge layer from part 1, verification is not one feature. It is four rungs, each answering the same question while trusting the claimant less.

**Rung 1: assertion, quarantined.** A "verified" flag that whoever writes the record can set is a step grading itself. The flag still exists, but only for importing historical receipts. Live verification refuses it.

**Rung 2: an observed check with a stored evidence trail.** The verify command takes a record and a check to run. It runs the check, reads the real exit status, and when you name an expected success signal it requires that signal in the output, because exit zero alone is precisely what failed on those 238 files. Only an observed pass stamps the record, and the command, result, and timestamp are stored on the record itself. The claimant still chooses the check, and a weak check is still possible, but the stamp shows exactly which check ran. "Verified by: true" is visible to every future reader and invites the obvious question. Assertion hides its emptiness; evidence exposes it.

**Rung 3: an independent actor re-runs the checks.** CI runs the drift gate and the repository's mechanical gates on every pull request: a different grader, at a different time, with no stake in the original claim. When a gate proves itself by failing against real drift, the receipt is written by the job that watched it happen, not by the gate's author.

**Rung 4: time attacks every stamp.** Each rule declares the files it governs. The moment those files change after the rule was last verified, the drift detector flags it, because a stale rule is a rule nobody re-checked. Verification also decays on a clock: a stamp nobody re-earns is demoted rather than left quietly trusted. And the system is scored on an outcome it cannot flatter itself on: recurrence after arming, the count of defect classes that came back even though a catching check existed. Not "how many lessons were recorded," which measures activity, but "did the mistakes stop repeating," which measures the point.

## Where judgment stays

The remaining self-grading surface is check selection. Nothing stops someone from verifying a record against a trivially weak check. I left that to human judgment deliberately and made it inspectable instead of trying to mechanize taste: every stamp displays its evidence, so a weak check becomes a visible artifact rather than an invisible belief. Mechanize what can be mechanized, audit the rest.

One detail worth the build: the rule stating that verification comes from observed checks and never from assertion lives in the store as a record, and it was the first record verified by the verify command itself, evidence trail and all. The system's rules are subject to the system.

Next: enforcement, and why a rule that is not wired to something that runs is a preference.

*The model generates. The loop governs. The standard holds.*
