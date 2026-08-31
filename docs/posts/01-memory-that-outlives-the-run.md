# Memory that outlives the run

*Part 1 of 3: The loop that learns. How our AI dev loop remembers, verifies, and enforces.*

I noticed something embarrassing while auditing three of my own codebases: they had all learned the same lesson, separately, the hard way.

One is a .NET microservices platform. One is a geospatial ML pipeline. One is a Python RAG service. In each of them, at some point, I had built a review rule or a checklist, described it in the docs as a live enforcement surface, and then discovered months later that nothing had ever run it. Three repos, three independent discoveries, one lesson: a surface nobody runs is documentation, not enforcement.

The lesson wasn't the embarrassing part. The embarrassing part was the *three times*. Each repo had a careful CLAUDE.md, encoded rules, a real engineering method. And none of that knowledge could cross the repo boundary. Every project was re-deriving the org's hard-won lessons from scratch, one incident at a time.

I had been thinking of my setup as "two readers, one canon": a human reads the rules, an AI agent reads the rules, and the two must not drift apart. What I actually had was N readers and N canons.

## The fix is a layer, not a bigger prompt

The obvious move is to paste every lesson into every prompt. That fails fast, and it fails in a specific way: always-on context taxes every session whether the lesson is relevant or not. My .NET repo enforces a hard size budget on its instructions file in CI (warning at 400 lines, build failure at 500) precisely because every byte of always-on context is cognitive overhead for both readers.

So the design question became: where does each piece of knowledge belong? I ended up with a three-way triage, decided by three questions asked in order.

**Does a session doing a totally unrelated task still need this?** Then it goes in the always-on instructions. Almost nothing passes this test. Naming conventions, the security posture, the error-handling canon. This is the most expensive real estate in the system, and the CI size budget keeps it honest.

**Would I want this to appear whenever a future task resembles it?** Then it goes in the knowledge store. This is the interesting category: the rate-limiter lesson that matters enormously to the three tasks a year that touch rate limiting, and is pure noise for everything else.

**Does it stop mattering once the PR merges?** Then it stays with the task and is allowed to die. The subtle part is extraction: a dead plan often contains one durable decision worth pulling out before you let go of the rest.

The store is the part I had to build. It's a small typed database of lessons: defects with symptom, cause, and fix. Rules. Deliberate decisions, so they don't get silently reversed. Tombstones for identifiers that must never come back. Retractions for claims that turned out to be false. Each note carries a scope: org-wide lessons propagate to every connected repo, repo-scoped quirks stay home. Choosing that scope is a human judgment, and it's what keeps a shared layer from filling up with one project's noise.

## Retrieved, not loaded

The reason the store can grow forever is that no run ever reads it. Before a task starts, a hook searches the store with the task description and injects only what survives four filters: lexical relevance ranking, scope (another repo's quirks are structurally invisible), declared interests (my Python repo says it cares about eval integrity and retrieval design, so React lessons never appear no matter how well they match), and typed routing that turns the survivors into a short action list. Fix this, run that gate, don't restate this retracted claim.

Each run sees a dozen relevant lines, not the whole library. At ten times the current size the briefing should be the same length, just better chosen.

Does it work? I measured it the way I'd measure anything: a held-fixed A/B, same model both arms, briefing injected versus not, scored by a blind judge that was deliberately a different model from the generator. In the original experiment, defect reproduction on covered tasks dropped from 50 percent to 6 percent, and from 75 percent to 8 percent on the tasks where the baseline model actually failed. I later rebuilt that experiment as a checked-in harness anyone can re-run, and the fresh receipt (48 sampled runs, zero harness failures) tells a sharper story: today's stronger models dodge much of the bait unaided, but the baseline still reproduced known defect classes in 33 percent of runs, and the briefed arm in 4 percent. On the tasks the baseline failed at least once, briefed runs reproduced in 1 of 15. One task always failed unaided, three out of three, and never failed briefed. The value concentrates exactly where models still get things wrong, which is exactly what an org's hard-won lessons describe. And the misses in the original run were both coverage gaps, a lesson not yet in the store, so the check doubles as a detector for what to encode next.

## The honest part

The first real dogfood run also found the system's first defect, in itself: the briefing for one specific task marked 28 of the 33 stored notes as relevant. Ranking put the right lessons first, but nothing cut the tail. Subject tags plus per-repo interest declarations cut it to 20 of 33, and a proper relevance cutoff is still open work, recorded in the store as a defect against the store, status: narrowed. The system's failure log lives inside the system.

That's the whole first idea. The state in most loop diagrams only lives inside one execution. The compounding win is memory that outlives the run: record the lesson once, retrieve it into every future task that resembles it, across every repo. Run N+1 should never repeat run N's mistake.

Next up: the verify step, and why you should never let a step grade itself.

*The model generates, the loop governs, and the team learns.*
