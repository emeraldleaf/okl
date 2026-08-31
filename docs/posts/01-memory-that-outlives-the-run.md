# Memory that outlives the run

*Part 1 of 3: The loop that learns. How one developer's AI loop remembers, verifies, and enforces.*

An agent writing code in one of my repos has no access to what the others learned. That is the problem in one sentence, and better prompting does not solve it.

Every project I work in has an instructions file with real standards in it. But a rule in a prompt is a suggestion, not a control: sometimes the agent applies it, sometimes I restate it, and neither of those is a system. Corrections do not persist either. A fix made in review is scoped to one conversation. The next session starts clean, and the next repository starts cleaner.

## What the audit actually found

So I audited my own setup across three codebases: a .NET microservices platform, a geospatial ML pipeline, a Python RAG service. The question was not whether the code was good, it was whether the standards I had written down were reaching the work.

Two findings.

First, several rules I had documented as enforcement were enforcement in name only. In one repo an architecture-review agent was described across six documents as a live review surface; nothing in CI or in any hook actually invoked it. Every one of those documents was accurate about the design and wrong about the system. Writing a rule down and running it are different acts, and only one of them changes what ships.

Second, and worse: the three repos had independently derived the same rules. Each had paid separately for knowledge the others already had. My standards existed, they were even written down, and they still could not cross a repository boundary. I had been thinking of my setup as "two readers, one canon": a human reads the rules, an agent reads the rules, and the two must not drift. What I actually had was N readers and N canons.

## The fix is a layer, not a bigger prompt

The obvious move is to paste every standard into every prompt. That fails in a specific way: always-on context taxes every session whether the rule is relevant or not. My .NET repo enforces a hard size budget on its instructions file in CI, warning at 400 lines and failing the build at 500, precisely because every byte of always-on context costs both readers attention.

So the design question became: where does each piece of knowledge belong? Three questions, asked in order.

**Does a session doing a completely unrelated task still need this?** Then it belongs in the always-on instructions. Almost nothing passes. Naming conventions, the security posture, the error-handling canon. This is the most expensive real estate in the system and the size budget is what keeps it honest.

**Would I want this in front of me whenever a future task resembles it?** Then it belongs in a retrievable store. This is the large category: the rate-limiter rule that matters enormously to the three tasks a year touching rate limiting, and is noise for everything else.

**Does it stop mattering once the PR merges?** Then it stays with the task. The subtle part is extraction, because a dead plan usually contains one durable decision worth pulling out before the rest is discarded.

The middle tier is the part I had to build: a small typed store of what the projects already know. Defects with symptom, cause, and fix. Rules. Deliberate decisions, recorded so they are not silently reversed. Tombstones for identifiers that must never come back. Retractions for claims that turned out to be false. Every note carries a scope, because org-wide standards should propagate to every project while one repo's quirks should stay home. Choosing that scope is a judgment call and it is the curation step that keeps a shared layer from filling with noise.

## Retrieved, not loaded

The reason the store can grow indefinitely is that no session ever reads it. Before a task starts, a hook queries it with the task description and injects only what survives four filters: relevance ranking, scope, the declared subject interests of the current repo, and typed routing that turns the survivors into a short action list. Fix this. Run that gate. Do not restate this retracted claim.

Each run sees a dozen relevant lines rather than the whole library. At ten times the current corpus, what reaches the agent should be the same length and better chosen.

## Proving it does something

A tool that feels helpful and a tool that is helpful are different claims, so I built an A/B harness and committed the results.

Eight tasks, each written to invite a specific defect class the store already covers. The same model in both arms, the retrieved rules as the only variable. A second, different model grading blind, never told which arm produced the code. Failure counts printed before any score, because a metric that cannot report its own failure rate is not a metric.

With none of the rules in context, the agent reproduced a known defect class in 33 percent of runs. With them, 4 percent. On the tasks the baseline actually failed, runs with the rules in context reproduced the defect in 1 of 15. One task, an unpinned linter version in CI, failed three times out of three without the rules and never with them.

The result I did not expect: a budget model with the rules in context made roughly a third the known mistakes of a frontier model without them on identical tasks. Context bought more than the model upgrade did, which is the more useful number if you are routing work between cheap and expensive models.

## The limits, stated

Those tasks were authored from rules already in my own store, so the experiment measures prevention of defect classes the store covers rather than general code quality. Small n. Directional, not a benchmark. The full method and every receipt are in the repository, including the runs that went the other way.

The system also found its own first defect: an early retrieval marked 28 of 33 stored notes as relevant to a single task. Ranking put the right records first, but nothing trimmed the tail. Subject tags and per-repo interest declarations cut it to 20; a proper relevance cutoff is still open work, recorded in the store as a defect against the store. The failure log lives inside the system it describes.

That is the first idea. The state in most agent-loop diagrams lives inside one execution. The compounding win is memory that outlives it: record the rule once, retrieve it into every future task that resembles it, across every project. Run N+1 should not repeat run N's mistake, and neither should the next repository.

Next: the verify step, and why a step's own report of success is not evidence.

*The model generates. The loop governs. The standard holds.*
