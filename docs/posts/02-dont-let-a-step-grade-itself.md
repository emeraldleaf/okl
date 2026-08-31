# Don't let a step grade itself

*Part 2 of 3: The loop that learns. How our AI dev loop remembers, verifies, and enforces.*

I had a pipeline step whose job was to write 238 files. It failed on every single one, swallowed the exceptions inside a worker pool, and exited with a success code. Everything downstream ran happily on an empty folder. By the time I noticed, I was debugging the wrong end of the pipeline.

That incident bought me a rule I now apply everywhere: a step saying it succeeded and the work actually being done are two different facts, and the loop has to check the second one. Exit codes, green builds, and tests passing on invented fixtures all answer a narrower question than the one the loop thinks it's asking.

The same class of failure, in fancier clothes: a dependency's major-version upgrade compiled clean and carried three runtime breaking changes, one of which silently broke transactional atomicity. And in an eval harness, my LLM judge printed a perfect 5.0 out of 5.0 while 19 of 20 cases had crashed, because it averaged only the survivors. Different costumes, same bug. The verifier reported on itself, and the report was wrong.

## The grader is usually ls, not an LLM

When I say don't let a step grade itself, people sometimes hear "every step needs a second model reviewing it." Almost never. The correct grader for my 238-file disaster was a file count. The correct grader for the upgrade was an integration test that forced a rollback and asserted no event escaped. Boring, deterministic checks, placed at the boundaries where the loop makes a decision: mark done, merge, deploy.

A second model enters in exactly one case: when the verify signal is itself a model's judgment, like grading summary quality or reviewing generated code. Only there does judge-must-differ-from-generator apply, because a judgment shares blind spots with whoever produced it. A file count has no blind spots.

## Four rungs of independence

In the knowledge layer I described in part 1, verification isn't one feature. It's four escalating rungs, each answering the same question with less trust in the claimant.

**Rung 1: assertion, quarantined.** A "verified" flag that whoever writes the record can set is a step grading itself. The system still has that flag, but only for importing historical receipts. Live verification refuses it.

**Rung 2: an observed check with a stored evidence trail.** The verify command takes a node and a check to run. It runs the check itself, reads the real exit code, and, if you name an expected success signal, requires that signal to appear in the output, because exit zero alone is exactly what burned me on those 238 files. Only on an observed pass does it stamp the record, and it stores the command, the result, and the timestamp on the record itself. Yes, the claimant still chooses the check, and a lazy check is still possible. But the stamp records exactly which check was run. "Verified by: true" is visible to every future reader and invites the obvious question. Assertion hides its emptiness; evidence exposes it.

**Rung 3: an independent actor re-runs the checks.** CI runs the drift gate and the repo's mechanical gates on every pull request. A different grader, at a different time, with no stake in the original claim. When a gate proves itself by actually failing against real drift, the receipt is written by the job that watched it happen, not by the gate's author.

**Rung 4: time attacks every stamp.** Each rule declares which files it governs. The moment those files change after the rule was last verified, the drift detector flags it: a stale rule is a rule nobody re-checked. Verification also decays on a clock; a stamp nobody re-earns demotes to stale rather than staying quietly trusted. And the whole system is scored on an outcome it cannot flatter itself on: recurrence after arming, the count of defect classes that came back even though a catching check existed. Not "how many lessons did we record," which measures activity, but "did the mistakes stop repeating," which measures the point.

## The honest part

The remaining self-grading surface is check selection. Nothing stops someone from verifying a record against a trivially weak check. I chose to leave that to human judgment and make it inspectable rather than trying to mechanize taste: every stamp shows its evidence, and a weak check is now a visible, embarrassing artifact instead of an invisible belief. Mechanize what can be mechanized. Make the rest auditable.

One detail I enjoy: the rule that says "verification stamps come from observed checks, never from assertion" lives in the store as a record, and it was the first record verified by the verify command itself, evidence trail and all. The system's rules are subject to the system.

Next up: enforcement, and why a checklist nobody is forced to run is documentation.

*The model generates, the loop governs, and the team learns.*
