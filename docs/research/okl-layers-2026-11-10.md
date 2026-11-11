# Research on each layer of okl

Read on 2026-11-10. Part of okl's documentation; [Related work](../RELATED-WORK.md) holds the
earlier reading of seven 2026 papers, and [Part 8 of the write-up](../posts/08-finding-the-lesson-was-the-easy-part.md)
tells the story that led here.

**Why this reading.** REPORT §4as to §4au found that lessons shown to the agent were followed no
more often than lessons not shown, that search could not find the lessons a change broke, that a
model reading every lesson's line could find them but then judged most of them followed, and
and that a third model could not settle the cases the reviewer and the key disputed (§4av later
found that two models agree well on cases not chosen for dispute). So the
question became whether each layer of okl follows what others have measured.

**How it was read.** Three threads, one per group of layers: recording and format; presentation
and use; retrieval, drift and evaluation. Each was read by a research agent from the papers' own
text, with at least two agreeing sources required for a recommendation and disagreement flagged.
That came to about 150 papers and four vendor prompting guides, and the full reports are the
appendices below. Before anything was quoted outside them, the figures listed under
[Checked at the source](#checked-at-the-source) were checked against each paper's own page.
Products are not compared here, as on the related-work page.

## Where okl stands

| | What the research supports | Where okl departs from it |
|---|---|---|
| **Recording** | Lessons as "when this, do that" with a stated boundary; abstract lessons over raw traces; explicit retire and supersede. | The agent records lessons mid-session and they are briefed at once. Studies that compared the two found that admitting only what was confirmed beat admitting everything, and in SkillsBench skills an agent wrote for itself scored below having none. 284 of okl's 379 live lessons have no check. |
| **Format** | Checkable conditions. Breaking a vague criterion into yes/no questions raised agreement between judges by 0.45 (CheckEval). | Broad process lessons ("wire a doc claim to a check") are the most broken. No lesson says when it does not apply. |
| **Presentation** | Direct instructions; a stated reason; the long material before the question. Code takes precedence over a stale instruction when told so in one sentence (4.2% to 91.4%). | The one-line tier says "if one fits this task, read it", the least-followed wording in a study of policy wording. The review after writing puts its steps before an 80 KB list. Lessons that arrive as tool output rank below instruction files. |
| **Use** | Correction with external feedback (tests, tools, checks) works. Gates have the strongest support of any okl mechanic. | The review asks the agent to judge its own code against each lesson, and judges are more than 50% more likely to pass their own output on a criterion it fails. |
| **Escalation** | Asking the user helps on underspecified tasks, with structural triggers. | okl has no escalation step, and "ask when unsure" is not a trigger models can use: they are poor judges of when they are unsure. |
| **Retrieval** | BM25 as a first stage; linear fusion; the reranker off; retrieval by governed paths; a model reading a candidate list, in score order. | Fixed caps (5 shown, 12 named) under a growing store; a largest-score-gap cut matched or beat fixed depths in the literature. The code-as-query test described the input, where the methods that helped wrote a text shaped like the target. |
| **Verification and drift** | A stored check stamped only on an observed pass; drift as a trigger to re-check. | Drift's precision is weak, and a deleted-identifier check is the cheap addition the literature supports. `okl review`'s 8 of 10 is recall on planted breaks, which overstate detectors. |
| **Evaluation** | Pre-registration, committed receipts, a judge that is not the generator. | The real-work answer keys are a model's labels treated as gold. When models disagree with each other on a labelling task, it is not one to hand to them (Ahmed et al., arXiv 2408.05534). A small random human audit makes such a key usable. |

## Changes, ranked by benefit against cost

Merged across the three threads. Each is a proposal to measure before it ships.

1. **Fix the answer key first.** Audit a small random sample by hand, sized for prediction-powered inference, and report agreement among people, between people and models, and between models. Every real-work figure rests on it. Cost: a few hours of one person's time.
2. **Hold agent-written lessons as proposed** until a check is seen red then green, or a person confirms against evidence; keep them out of briefings or mark them. The strongest agreement across the recording studies. Cost: a new state and a briefing filter.
3. **Rewrite the framing lines.** Direct wording instead of "if one fits"; the code-precedence sentence for unchecked lessons; the review's steps both before and after its list. Cost: text, tested on the seeded tasks first, since which wording works best differs by model.
4. **Rewrite the most-broken broad lessons as two to four yes/no conditions,** each naming a file, a pattern or a command, with a line saying when the lesson does not apply. Cost: low, starting with the 20 that hold 65% of breaks. *Measured since (REPORT §4av): on these 20, conditions did not raise agreement between judges, which was already high, and they raised false alarms, so they did not ship.*
5. **Gate the high-stakes lessons a script can check** (#415, under way).
6. **Rebuild the review.** okl preselects lessons from the diff instead of listing all of them; each lesson is checked on its own, in a fresh context, with the reasoning before the verdict; high-stakes items get a second model. Cost: medium.
7. **Add the per-task protocol:** brief, commit, act, verify, and escalate on four triggers (reversing a recorded decision; two readings that produce different code; an irreversible action; a check whose fix conflicts with the task), with the agent's report on each lesson re-checked by okl. Cost: low to medium.
8. **Retrieval:** a model reader as a second stage over a wider list in score order; a largest-score-gap cut instead of fixed caps; one retry of the query test with "write the lesson this change could break" as the query. Cost: low to medium.
9. **Drift:** a deleted-identifier trigger; measure `okl review`'s false positives on lessons that still hold. Cost: low.
10. **Evaluation:** per-task, paired intervals for the seeded A/B; guards for the outcome replay (the store rewound to the base commit, tests that fail before and pass after, bugs fixed after the model's training cutoff). Cost: low.

## What the research leaves open

- Whether stating a lesson's reason makes an agent follow it more often. The guidance says it helps the model generalise; no study measured compliance.
- Positive against negative phrasing, beyond weak evidence.
- Architecture decision records as context for an agent: no controlled study was found.
- Human intent against lessons drawn from an agent's own verified failures, head to head.
- Whether a static embedding behaves like the dense models the retrieval studies used.
- Cost: context files raised cost about 20% in one study and cut runtime in another.

## Checked at the source

Each of these was read from the paper's own page before it was quoted outside the appendices.

- SkillsBench (arXiv 2602.12670, v4): curated skills raised the average pass rate from 33.9% to 50.5%; skills the agent wrote for itself scored 8.1 to 11.5 points below none on its three dedicated configurations (§5.1.1).
- Gloaguen et al., *Evaluating AGENTS.md* (arXiv 2602.11988, v3): context files do not generally improve task success and raise cost by over 20%; agents follow them.
- Tsuchida et al., *Do Coding Agents Follow AGENTS.md?* (arXiv 2611.04367): conditional phrasing was followed less often than prescriptive or explanatory phrasing.
- Xu and Wu, *Stale Instruction Files Override the Code in Coding Agents* (arXiv 2610.30571): 90.1% of choices followed the stale file; one sentence moved code-following from 4.2% to 91.4%.
- Pombal et al., *Self-Preference Bias in Rubric-Based Evaluation* (arXiv 2604.06996): judges can be more than 50% more likely to mark a failed criterion satisfied when the output is their own.
- Lee et al., *CheckEval* (arXiv 2403.18771): decomposed binary questions raised average agreement across evaluator models by 0.45.
- Xiong et al., *How Memory Management Impacts LLM Agents* (arXiv 2505.16067): errors in stored experience compound; the abstract argues for regulating experience quality. Its per-agent figures are in the body, not checked here.
- Ahmed et al., *Can LLMs Replace Manual Annotation of Software Engineering Artifacts?* (arXiv 2408.05534): model–model agreement as a predictor of whether a task suits models at all. Its alpha figures are in the body, not checked here.

## Appendices: the three reports

The full reports, as the research agents wrote them, with every citation and what was read of
each paper. Figures not listed above were not re-checked.

- [A. Recording, format and human input](2026-11-10-capture-format.md)
- [B. Presentation and use](2026-11-10-presentation-use.md)
- [C. Retrieval, drift and evaluation](2026-11-10-retrieval-eval.md)
