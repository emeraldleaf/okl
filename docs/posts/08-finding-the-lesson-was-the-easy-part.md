# Finding the lesson was the easy part

*Part 8: what happened when I tested whether a lesson in front of a coding agent changes the code it writes. The canonical copy is on [emeraldleaf.dev](https://emeraldleaf.dev/writing/finding-the-lesson-was-the-easy-part/); the measurements are in [REPORT §4as to §4au](../../evals/REPORT.md) and the reading in [Research on each layer](../research/okl-layers-2026-11-10.md).*

okl does two things. It puts a team's lessons in front of a coding agent, and it gives each lesson a check that is re-run when the code it governs changes and that can block the push. Both have evidence behind them. On eight seeded tasks, across seven runs, briefed agents reproduced a known defect in 7% of attempts against 42% without the briefing. And the second half, a lesson that carries a check, is what the research on agent memory keeps arriving at independently: compiled checks reached 88% compliance where the same rules as prompts reached 67%, and a memory layer on its own still left 57.5% of a user's rules broken.

Seeded tasks are built around known defects, though. This week I tested the harder claim, on real work: when okl puts a lesson in front of an agent, does the code come out different?

The short answer is that finding the right lesson turned out to be solvable, and it was not the hard part. The hard part is that many lessons do not say clearly enough when they have been broken, so neither the agent nor anyone grading it can tell. Getting there took five hypotheses, four of which failed, and I kept every one. Where it led is the reassuring part: the evidence points at the half of okl that checks lessons, not the half that shows them.

## Shown is not followed

okl logs which lessons each briefing showed. I joined that log against an answer key for 50 real changes to this repository, saying which lessons each change needed and whether it followed them. Lessons the agent had been shown were followed no more often than lessons it had not. The estimate even pointed the wrong way, by about nine points, with an interval wide enough to include zero (§4as).

It is observational, so it cannot say the briefing does nothing. It does say that *shown* is not *followed*, and that I had been measuring the first and assuming the second.

## Hypothesis: the words were wrong

The lessons a change breaks are usually about what the code does. It runs a shell command, it reads an environment variable, it writes a receipt. The task's own words rarely say any of that, so a search driven by the task cannot find those lessons. My idea was to wait until the code exists, have the agent explain what it does one mechanism per sentence, and search with the explanation instead.

I wrote the bar down before any explanation existed (§4at). On the 50 earlier changes, searching with the task's words put 14% of the broken lessons in the top five. Searching with the raw code put 13% there. Searching with the explanation put 14% there. Three different queries gave the same answer, so the query was not the bottleneck. Similarity search over a few hundred lessons returns lessons *about* a change, not lessons the change *broke*.

## Hypothesis: let a model read the list

So I took search out. A model got the explanation and every lesson's one-line summary, and named the ten the change most likely broke. It found 40% of the broken lessons in its ten, against 21% for search. It also found the lessons that bore on the change: 159 of the 356 needed lessons, against search's 87. This was on the half of the data I was allowed to tune on, so it is a lead, not a result.

What it could not do was tell which of those lessons the change had broken. A title says what a lesson is about. It does not say whether this code obeys it.

## Was that even a fair test?

Then a question I should have asked earlier. Every task was a pull request to okl itself, checked against okl's own lessons, and the same agent wrote the code and the lessons. That is a strange sample.

The fair test uses public repositories with long review histories, where a reviewer making the same point on a later pull request is a human label that the earlier lesson was broken. I found no published measure of how often that happens, and building the set properly is about thirty hours of human checking. I filed it as issue #413 rather than pretend the numbers from my own repository carry over.

## The review after writing

I built the step anyway, because it does something the briefing cannot: it runs after the code exists. `okl check --change` lists the changed files and every lesson in scope. It tells the agent to say what its code does, pick the ten lessons the change most likely breaks, read each one, check its code against it, and fix only what is broken.

Its first review was of its own change. It flagged six lessons the first version broke, among them a branch name beginning with a dash reaching git as an option, and a mistyped setting silently read as "off". Each is fixed, with a test. Then a separate architecture review found five more problems, including one neither of us had seen: run from a subdirectory, the step lost files created elsewhere in the repository.

## I wanted it on by default. The test said no.

Then I decided it should be on for everyone. My own rule is that a default needs evidence, so I asked for something quick, wrote the bar first, and ran it on 20 changes the method had never seen. The bar: catch at least 30% of the broken lessons, and wrongly flag at most one lesson on a typical change (§4au).

It picked 12 of the 23 broken lessons, then judged its own code fine for 8 of them. It caught 4, or 17%. It was quiet, with three false alarms across ten changes that broke nothing, but each review cost about 170,000 tokens, most of them cached. It missed the bar, so it ships off by default and on in my own repositories. I reverted the commit that had already turned it on.

## Three models, one coin

Seventeen percent could mean the reviewer was lenient or the answer key was strict, and the key was itself a model's judgement. So a third model, one that had made neither call, judged the disputed cases without seeing either verdict. I wrote down beforehand that it needed to agree on at least three of the four lessons the reviewer and the key both called broken, or its verdicts would count as noise. It agreed on two.

That is the finding. Asked whether a change breaks one of these lessons, three capable models agree about as often as not. A lesson three models cannot agree on is not one an agent can reliably follow, and not one anyone can reliably grade. Research on using models to label software artifacts says the same: when models disagree with each other on a task, it is not one to hand to them.

## Stop relying on judgement where it matters most

The breaks are concentrated. Across both answer keys, 124 breaks fall on 56 lessons, and the 20 most-broken lessons hold 65% of them (`break-concentration-20261110-1600.json`). That is a short list to harden.

The lessons a script can check now fail the build. The first sweep runs every command and every check where it cannot do its job. It found six of okl's own CI checks that crashed with the exit code meaning "found problems" when their inputs were missing, and two that passed having read nothing. The lesson that says exactly that is one of the ten this repository names on every task. It had been shown, and it had not been followed.

The vague lessons get rewritten. Whatever is left goes to the review.

## What the research says

Then I read, in three threads covering recording, presentation and retrieval, from the papers themselves rather than their abstracts. The agreement was striking, and it starts with what okl already does:

- **Checks beat prompts, and models pass their own work.** Correction that relies on tests and tools works, and unaided self-correction mostly does not. Judges were more than 50% more likely to mark an output as meeting a criterion it failed when the output was their own. A lesson whose check runs when the code changes, and which blocks the push until it passes, is the mechanism with the strongest support in everything I read. It is the centre of okl.
- **Confirm before you keep.** In SkillsBench, skills an agent wrote for itself scored 8 to 12 points below having no skills at all, while curated skills added 18 to 25 on the same setups. A study of memory management found that errors in stored experience compound, and argues for regulating what gets stored. okl lets the agent record lessons mid-session with no confirmation. That is its biggest departure from the evidence.
- **Context files help less than people assume.** A study of repository context files found that agents follow them, but they do not generally improve task success and they add over 20% to the cost. They earn their place for what an agent cannot infer.
- **Conditional wording is the weakest.** In a study of policy wording, "if relevant, do this" was followed less often than direct or explained instructions. That is how okl phrases its one-line lessons.
- **One sentence fixes stale guidance.** Agents followed a stale instruction file over the actual code nine times in ten. Adding one sentence telling them to follow the code when the two disagree moved code-following from 4.2% to 91.4%.
- **Vague criteria make judges disagree.** Breaking a criterion into yes/no questions raised agreement between judge models by 0.45.
- **Ask only on real ambiguity.** Asking the user helps on underspecified tasks, but models are poor judges of when to ask, so the triggers have to be structural.

## What changes

The lessons stay. How they reach the agent changes. Each task gets a short protocol:

1. **Brief.** Each lesson reads as an action: when this happens, do this, and it is done when this check passes, with the reason in one line.
2. **Commit.** Before writing code, the agent names the lessons that apply and how it will follow each.
3. **Act.**
4. **Verify.** It runs each lesson's check where there is one, and checks one lesson at a time where there is not.
5. **Escalate, rarely.** It asks me only on four triggers: reversing a recorded decision, two readings of a lesson that produce different code, an irreversible action, or a check whose fix conflicts with the task.

New lessons stay "proposed" until a check passes or I confirm them. The vague ones get yes/no conditions. And the measure that needs no judge comes next: real past bugs replayed at their base commit, graded by the test the real fix added, comparing today's briefing with the protocol.

## What this means if you are deciding whether to use it

Showing an agent its team's lessons helps on the defects those lessons describe; the seeded tasks show that. On open-ended real work, showing alone is the weakest thing okl does, which is also what the research found for memory layers that only show. What okl does differently is the part that held up all week: a lesson carries a check, the check re-runs when its code moves, and the push waits until it passes. The changes this week all move weight in that direction. The most-broken lessons became checks, the review after writing gives the agent a second pass with the code in hand, and the protocol asks it to say what it did with each lesson, so its account can be checked too.

## What the week was really about

Four of five hypotheses failed. Better queries did not help, my own repository was the wrong sample, the review did not earn a default, and a third model could not settle the question. Each failure narrowed where the real problem was, and none of them touched the part of okl that checks. The bar was written before every result, and every number has a receipt.

The tool checked itself throughout: its new step reviewed its own first draft and found real bugs, and its new sweep caught okl's own checks reporting nothing as success. That is the habit I am trying to build into an agent, and this week it applied to me as much as to the agent.
