# Enforcement, or good intentions

*Part 3 of 3: The loop that learns. How one developer's AI loop remembers, verifies, and enforces.*

The most instructive bug in my method wasn't in code. It was in the documentation of an agent that reviewed architecture. Six separate documents described it as a live enforcement surface. It had been invoked by nothing, ever. Every one of those documents was telling the truth about the design and lying about the system.

I have now learned this lesson in three different codebases, which is what finally made it stick: if a rule only lives in the prompt, sometimes the agent picks it up on its own, sometimes I have to remind it, and neither of those is a system. Probabilistic compliance from a model is still non-compliance from a control standpoint. Enforcement has to be mechanical or it's just good intentions.

## What mechanical looks like

In the loop I've been describing across this series, every rule that matters is wired to something that runs without anyone deciding to run it.

**The read is enforced, fail closed.** The moment a task is submitted, a hook retrieves the relevant lessons from the knowledge store and injects them into the model's context, before any work begins. If the store is unreachable, the hook blocks the task instead of proceeding, because "no lessons apply" and "I couldn't reach the lessons" look identical from the outside and only one of them is safe. Silence is never reported as safety. There's an explicit override for working offline, and it's explicit on purpose: proceeding blind should be a decision someone made, not a default someone fell into. One hard-won detail: my first version wired this to the wrong event, one whose output the model never sees. The hook fired on every edit, retrieved the right lessons, and printed them into a void, while every unit test passed. Only a behavioral test against a bare control repo exposed it. A hook that fires is not a hook that's heard. Test the channel, not the firing.

**The write is prompted at the only moment it can work.** Lessons die when sessions end, so a stop hook blocks the first stop of any session that changed files and asks one question: did this session learn something worth keeping? Either the lesson gets recorded, with its scope and tags chosen deliberately, or the session states that nothing durable was learned and finishes. It fires once per session and never loops. The first session running that hook got caught by it and had to record three lessons it had fixed but never encoded. The hook worked on its own author, which is the only referee a rule like this will accept.

**The gates run at merge time.** Retired identifiers can't resurface, retracted claims can't be restated, docs can't silently orphan, the instructions file can't bloat past its budget. Each is a small script that fails CI. None of them require anyone to remember anything.

## Installation is where enforcement quietly dies

Here's the failure mode I only caught by auditing my own installer: it did half the wiring and printed instructions for the rest. Install the hook, then "add it to your settings file." Copy this CI workflow. Register this tool. Four printed instructions, four surfaces that would never run for anyone who didn't do the homework, which over time is everyone.

So the installer's rule became: init must wire, not instruct. It registers the hooks in the agent's settings itself, idempotently, preserving whatever else is there. It installs the CI workflow instead of describing it. It registers the agent tools when the dependency exists, and deliberately refuses when it doesn't, because a registration pointing at a missing dependency is a broken tool, which is worse than none. The only things it's allowed to print are the things it genuinely cannot do, and it says those loudly: this isn't a git repository, so the drift layer is disabled until it is.

One layer deeper, same lesson: hooks run in whatever environment the agent harness spawns, which routinely lacks your dev shell's PATH. A hook that works on the author's machine and silently no-ops on everyone else's is the "surface nobody runs" bug wearing an environment-variables costume. The fix is a layered resolver: an explicit override, then a path pinned at install time by the shell where the tool demonstrably works, then PATH, then module execution by any interpreter that can import the package. The enforcement hook fails closed with instructions when nothing resolves; the reminder hook silently disables, because a best-effort prompt must never brick someone's sessions. Degrade by role.

## The honest part

The stop hook can be lied to. A session can answer "nothing durable learned" untruthfully and finish. I left that trust boundary in on purpose, the same way the ship-moment reminder in my .NET repo is a reminder and not a block: the mechanical part is putting the question in front of you at the right moment, every time. Answering it honestly stays a human's job. The system's aim isn't to remove judgment. It's to make sure judgment is exercised at the moments it matters, with the relevant evidence in view, instead of whenever someone happens to remember.

That's the series. Memory that outlives the run, verification that doesn't trust the step's own report, and enforcement that runs without being remembered. None of the three is exotic on its own. The compounding comes from wiring them together: the enforced read injects the memory, the verify rungs keep the memory honest, and the recurrence metric tells you whether any of it is working, in the one currency that matters, mistakes that stopped repeating.

*The model generates, the loop governs, and the team learns.*
