# Enforcement, or good intentions

*Part 3 of 3: The loop that learns. How one developer's AI loop remembers, verifies, and enforces.*

A rule that is not wired to something that runs is a preference, not a standard.

I know that from auditing my own work. In one codebase an architecture-review agent was documented across six files as a live enforcement surface. When I audited what actually executed, meaning the CI jobs, the hooks, and the pre-commit path, that agent appeared nowhere. Every one of those documents was accurate about the design and wrong about the system.

I have now found the same shape in three codebases, which makes it a pattern rather than an oversight: if a rule only lives in the prompt, sometimes the agent applies it, sometimes I restate it, and neither of those is a control. Probabilistic compliance is still non-compliance when the point is a guarantee.

## What mechanical looks like

In the loop from parts 1 and 2, every rule that matters is wired to something that runs without anyone deciding to run it.

**The read is enforced, fail closed.** The moment a task is submitted, a hook retrieves the relevant lessons and injects them into the model's context before any work begins. If the store is unreachable, the hook blocks the task rather than proceeding, because "no lessons apply" and "I could not reach the lessons" look identical from the outside and only one of them is safe. Silence is never reported as safety. There is an explicit override for working offline, explicit on purpose: proceeding without the standards should be a decision someone made, not a default they fell into.

One detail that cost me a rebuild. The first version was wired to an event whose output the model never receives. The hook fired on every edit, retrieved exactly the right lessons, and wrote them to a channel nothing read, while every unit test passed, because those tests proved the hook ran and produced correct text. Only a behavioral test against a bare control repository exposed it: same task, same model, defect reproduced in both arms. A hook that fires is not a hook that is heard. Test the channel, not the firing.

**The write is prompted at the only moment it can work.** Lessons die when sessions end, so a stop hook blocks the first stop of any session that changed files and asks one question: did this session produce something worth keeping? Either the lesson is recorded with a deliberate scope and subject, or the session states that nothing durable came out of it and finishes. It fires once per session and never loops. The first session running that hook was caught by it and had to record three lessons it had fixed but never encoded. A rule that catches its own author on day one is the only kind I trust.

**The gates run at merge time.** Retired identifiers cannot resurface. Retracted claims cannot be restated. Documentation cannot silently orphan. The instructions file cannot bloat past its budget. Each is a small script that fails CI, and none of them require anyone to remember anything.

## Installation is where enforcement quietly dies

Auditing my own installer turned up the same failure one layer down: it did half the wiring and printed instructions for the rest. Install the hook, then "add it to your settings file." Copy this CI workflow. Register this tool. Four printed instructions, four surfaces that would never run for anyone who skipped the homework, which over time is everyone including me.

So the rule became: init must wire, not instruct. It registers the hooks in the agent's settings itself, idempotently, preserving whatever is already there. It installs the CI workflow instead of describing it. It registers the agent tools when the dependency exists and deliberately refuses when it does not, because a registration pointing at a missing dependency is a broken tool, which is worse than none. The only things it prints are the things it genuinely cannot do, and it says those loudly: this is not a git repository, so the drift gate is disabled until it is.

Same lesson again at the environment layer. Hooks run in whatever process the agent harness spawns, which routinely lacks the PATH of the shell you developed in. A hook that works on the author's machine and silently no-ops on everyone else's is the "surface nobody runs" bug wearing an environment-variable costume. The fix is a layered resolver: an explicit override, then a path pinned at install time by the shell where the tool demonstrably works, then PATH, then module execution by any interpreter that can import the package. The enforcement hook fails closed with instructions when nothing resolves; the reminder hook silently disables, because a best-effort prompt must never brick someone's session. Degrade by role.

## Where the trust boundary sits

The stop hook can be lied to. A session can answer "nothing durable" untruthfully and finish. I left that boundary deliberately, the same way a ship-moment reminder is a reminder and not a block: the mechanical part is putting the question in front of you at the right moment, every time. Answering it honestly stays a person's job. The aim is not to remove judgment, it is to guarantee judgment gets exercised at the moments that matter, with the relevant evidence already in view.

That is the series. Memory that outlives the run, verification that does not trust a step's own report, and enforcement that runs without being remembered. None of the three is exotic alone. The compounding comes from wiring them together: the enforced read puts the standard in front of the agent, the verification rungs keep the standard honest, and the recurrence metric reports whether any of it worked, in the only currency that counts: mistakes that stopped repeating.

*The model generates. The loop governs. The standard holds.*
