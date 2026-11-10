# How research bears on how okl presents lessons and how agents use them

> Appendix B to [Research on each layer of okl](okl-layers-2026-11-10.md). Written on 2026-11-10 by a research agent that read each paper's own text; okl's maintainer asked the questions and checked the figures listed under *Checked at the source* in the main page against each paper's own page. Other figures here were not re-checked.

Research report, 10 November 2026. It covers the five original topics and three added during the task: how okl frames the lessons it supplies; how the agent should check its work and when it should escalate; and the model makers' own prompting guidance. Sections 1, 4 and 5 answer the original brief in about 1,470 words. Sections 2, 2b and 3 answer the additions and bring the body to about 4,000 words, past the original 1,500-word limit.

**How the sources were read.** I downloaded each cited paper's PDF from arXiv and extracted the text; the four vendor guides were read as web pages. I read the abstract plus the parts named in its citation. All figures come from the PDF text. A venue is given only where the PDF states it; otherwise the source is marked as a preprint. Nothing already in `docs/RELATED-WORK.md` is repeated. Several 2026 sources are single-author or unreviewed preprints: [2][3][4][5][15][34][49]. Their numbers are flagged where they carry a recommendation.

## Top findings

1. **Conditional wording is the weakest form, and agents rarely fetch optional knowledge.** A "read it if it fits" instruction is followed least of four tested wordings [4][8], and agents that choose what to load do worse than agents given the same material [14][15]. Together these predict okl's one fetch in 71 tries.
2. **Self-review is lenient for a known reason.** On rubric items the output objectively fails, judges are more than 50% more likely to say "satisfied" when the output is their own [25]. Models also miss errors attributed to themselves that they fix when the same errors are attributed to someone else [24]. okl's 8-of-12 result is this effect.
3. **External feedback works; intrinsic self-correction does not** [20][21][22][23]. That makes the gates the best-supported part of okl.
4. **Where text enters the context matters.** Text that arrives as tool output, or as a tool or skill description, ranks below instruction files and user prompts [6][9][5]. Lessons fetched with `okl show`, or attached to a file read, may arrive on that weaker surface.
5. **One sentence fixes stale descriptions.** "Follow the code when the documentation disagrees, and report each disagreement" moved code-following from 4.2% to 91.4% [5]. This fits UNCHECKED lessons, with a caveat for defect lessons.
6. **Asking pays only for real ambiguity, and models are poor judges of it** [39][40]. Good triggers are structural: an option that changes behaviour [41][43], or an irreversible action [42]. "Ask when unsure" is not one.
7. **The model makers agree with most of this, but not on where instructions go** [V1][V2][V4]. okl's review output puts its steps before the 80 KB list. Repeating them after the list satisfies all three guides (§2b).

## 1. okl's mechanics against the research

**Briefing before each prompt (5 in full, 12 one-line, up to 10 standing): mixed.**
- *Supported: agents follow injected instructions.* Context-file instructions are "well followed": a tool named in the file was used 1.6 times per task, against under 0.01 times when not named. Task success did not improve, and cost rose by over 20% [1]. A second study found no correctness effect either for an always-on file or for files read on demand [2]. okl's seeded 42%→7% result and its real-work null split the same way: a briefing changes the behaviour a lesson names, but it does not move broad outcomes.
- *Disagreement on cost.* One study found AGENTS.md cut median runtime by 28.64% and output tokens by 16.58% [57]; another found cost rose by over 20% [1]. Measure cost on okl's own tasks rather than assume either.
- *At this size, the number of lessons is not the limit.* In 1,650 sessions, file size (25–500 lines), position, splitting the file and conflicting lines had no detectable effect on one target rule [3]. Top models stay near-perfect up to about 150 simple instructions [7]. *Disagreement:* with realistic conditional and tool constraints (11.9 per prompt on average), the best model met every constraint in under 30% of instructions [8]. Complexity matters more than count.
- *Departs:* the 12 "also matched" lessons and the standing lessons arrive as one-liners behind a conditional fetch (§2).
- *Position:* put must-follow items first and the closing instruction last. Primacy bias grows with instruction density [7], and the middle of a context is used worst [11].

**Opening a lesson by id: departs.**
- Agents that choose which skills to load do worse than agents with the same skills force-loaded (Claude 51.2% against 55.4%). Claude's loading rate fell from 62% to 44% when it had to retrieve the skills itself [14].
- Given short stubs, agents fetched the full block on 1.4% of queries [15].
- Whether a tool call is needed can be decoded from the model's hidden states, yet actual calls mismatch need in 26.5–54.0% of cases. Most of the mismatch arises between belief and action, not in the belief [16].
- A fetched lesson arrives as tool output, which models are trained to rank lowest [9][6].

**Lessons added after a file read: right timing, possibly the wrong surface.**
- *Timing supported.* Compliance falls as a session goes on (about 5.6% lower odds per generated function, found post hoc) [3], and length alone hurts even with perfect retrieval [12][13].
- *Surface may depart.* If the hook's text reaches the model as part of a tool result, the hierarchy research predicts it is weighed as data [9][6].
- *Noticing is not acting.* Claude Code pointed out a conflict between the instruction file and the code in 79 of 80 runs, and still followed the file [5]. In bandit tasks, models gave a correct rationale 87% of the time yet acted greedily in 64% of those cases [19]. "Quoted to the user but not acted on" is this gap.

**Review after writing: departs on four counts, supported on one.**
1. *Self-review.* Intrinsic self-correction is unreliable [20][21]. Self-repair is limited by the quality of the model's feedback on its own code [22]. The failure is one of activation, not knowledge: models miss 64.5% of their own errors on average, and appending "Wait" cut that blind spot by 89.3% [24]. Judges pass their own failing rubric items [25], and self-recognition tracks self-preference [55]. Stronger models show more harmful self-preference when they are wrong [26], and self-refinement amplifies self-bias unless the feedback is external [56].
2. *Choosing from about 300 one-liners (about 80 KB).* That is past the roughly 150-instruction point where adherence starts to fall [7]. On 350 PRs, all 8 models found fewer issues as more context was added, and a 2,000-token structured diff summary beat a 2,500-token full context [34]. okl's selection recall of 12 of 23 is what this predicts.
3. *Step 1 asks the agent to describe its own change before judging it.* When a judge sees the agent's own success claim, it detects fewer failures: withholding the claim raised recall of dangerous misreports by 43.4 and 13.3 points [50].
4. *Over-flagging is real too.* LLMs misclassify correct code as failing its requirements, and elaborate prompts (explain, then propose corrections) make this worse [27]. okl's 3-of-10 false flags fit.
5. *The order is backwards for two of three model makers.* The steps come before the 80 KB list; Anthropic's and Google's guides put instructions after long data [V1][V4], and OpenAI's puts them at both ends [V2] (§2b).
- *Supported: per-item checking.* Checking each item separately helps: generated checklists [28], decompose–critique–refine [29], tool verification per constraint [30], and "factored" verification without the draft in view, because models repeat their own errors [31]. Self-correction works where answers break into parts [21]. Industrial reviewers that work pair a rule taxonomy with a separate precision filter (75.0% precision) [32], or keep the LLM for practices tools cannot check [33].

**Gates: strongly supported.**
- Correction works when the feedback is external and reliable [21][23].
- Runtime rule enforcement blocked over 90% of unsafe code-agent executions, at millisecond overhead [36].
- Enforcement built into the system gives guarantees prompting cannot: 77% of tasks solved with provable security, against 84% undefended [37].
- Rules that go against a model's default behaviour are followed 3.6–7.4 points less often [6]. Those are the best candidates for a gate.

**okl's measurements are consistent with the field.**
- Three models agreeing only half the time matches other results. Five LLM judges under five prompt strategies never exceeded AUROC 0.65 at detecting false success [49]. LLM verifiers are unreliable on complex instructions [38].
- The real-work null may partly be a measurement artefact. Aggregate compliance overstates following, because many rules match what the model would do anyway [6]. Comparisons of shown against unshown lessons need lessons that go against the model's default.

## 2. How okl frames the lessons it supplies

**What the research says.**
- *Conditional against directive wording.* One study inserted a single policy in four wordings into 86 tasks across four harness–model pairs [4]. The conditional wording was followed least wherever the wordings differed:
  - Claude Code with Opus-5: prescriptive 78.0%, explanatory 77.2%, prohibitive 70.7%, conditional 64.2%.
  - Claude Code with Sonnet-5: 71.6%, 49.4%, 17.3% and 35.6% in the same order.

  The authors' explanation: a conditional makes the agent first judge whether the rule applies, and that judgment gets skipped. A second study found that conditional constraints are among the hardest in agentic prompts [8]. Two further findings come from this one study only: giving a reason added nothing, and "never" wording did worse than direct wording on Sonnet-5 [4]. Disagreement: coherent supporting evidence does make models accept external information [54].
- *Asking for a commitment before acting.* Reciting the relevant evidence before solving recovered part of the long-context loss (up to 4%) [12]. Planning before coding raised pass@1 by up to 25.4% relative [52][53]. But saying is not doing [5][16][19]. Reasoning text also under-reports what drove the answer: models often revealed their use of a hint less than 20% of the time [48]. A commitment step focuses attention; verification still has to follow it.
- *Unverified lessons.* Use the code-precedence sentence [5]. Its authors separate rules ("run the tests before you commit") from descriptions of the code ("we use print"); the sentence is meant for descriptions.
- *Checklists* help when each item is its own yes/no question [28][29][30][31], but they do not remove self-preference [25].
- *Reporting.* Self-reports overstate success. "False success" was 45–48% of failures in single-control τ²-bench domains and 75.8% of AppWorld coding traces with a status claim [49]. Self-validated success overstated verified success for software-analysis agents [51], and a judge shown the agent's claim misses more failures [50]. So ask for a per-lesson report that points to evidence; okl checks the evidence and keeps the report away from any reviewer.

**Why the three measured weaknesses happen.**
- *One fetch in 71:* conditional wording [4], agent-chosen loading [14][15], the gap between knowing a tool is needed and calling it [16], and a 300-title list past the density limit [7].
- *Quoted but not acted on:* the knowing–doing gap [19][16], noticing without changing course [5], and the low rank of tool-surface text [6][9].
- *Shown lessons followed no more than unshown ones on real work:* task-level nulls [1][2], compliance that happens by coincidence [6], and adherence that decays within a session [3].

**Rewrites.**

| Current line | Proposed | Basis |
|---|---|---|
| `FIX: <title> [id] — when you see: <symptom> → <fix> why: <cause>` | `<fix, as an instruction> [id]. Matched on: <file or term okl matched>. Why: <cause>.` okl has already judged relevance, so state the action directly and keep the symptom as evidence, not as a condition. | [4][8] |
| `Also matched (12)… If one fits this task, read it with okl show <id> before you write code.` | Move the top lessons into full text. For the rest: `Before your first edit, write one line per lesson below: id — applies or does not apply — reason. Open each that applies with okl show <id> and follow it.` | [4][14][15][12][52] |
| `N lesson(s) marked UNCHECKED … treat them as advice, and confirm them against the code before relying on them.` | `N lessons are UNCHECKED: no check has confirmed them. Where one describes how this code works and the code disagrees, follow the code, and list each disagreement in your final reply (id, file, what differs). Where one warns of a defect, finding that defect elsewhere in the code does not disprove the lesson.` The second sentence is my inference and is untested. | [5][54] |
| `Decisions — made on purpose; do not silently reverse` | `Decisions: keep these as they are. If this task cannot be done without changing one, stop before editing and ask the user: name the decision, say what would change, and give two options with your recommendation.` | [4][42][41][43] |
| `Standing lessons… If one bears on this work, read it with okl show <id>.` | Add them to the disposition list above. For standing lessons that have a check, write `These checks run when you finish.` | [4][21][36] |
| `Nothing matched… Read any that fits before you proceed, and record anything you learn with okl record.` | `No lesson matched this task closely.` Drop both the conditional read and the request to record. | [1]; Phantom Guardrails (RELATED-WORK) |
| (none) | Last line: `When you finish, run the checks named above, and end your reply with a Lessons section: id — applied (file:line), check passed (command), does not apply, or disagreement (what you did).` | [11][7][5][49][51] |

## 2b. The model makers' prompting guidance against the papers

These guides are the vendors' own advice, not peer-reviewed. okl is agent-agnostic, so a point counts as settled only where the guides and the papers agree.

| Point | Anthropic [V1] | OpenAI [V2][V3] | Google [V4] | Papers | For okl |
|---|---|---|---|---|---|
| Be clear and direct | Yes | Yes; one firm sentence "is almost always sufficient" | Yes | Agree: conditional wording is weakest [4][8] | Word lessons as instructions (§2 table). |
| Give the reason | Yes: "Claude can generalize from the explanation" | Not stated | Not stated | **Disagree:** adding a reason made no difference on Opus-5, cut compliance from 71.6% to 49.4% on Sonnet-5, and helped gpt-oss [4]; one study, one rule | Keep "why", but put it after the instruction, and measure per model. |
| Say what to do, not what not to do | Yes (under output formatting) | "what to do or not to do" | Allows both; its own examples use negatives | Weak support: "never" wording was worst on Sonnet-5 [4] | Prefer positive wording (Decisions row). The vendors themselves are not consistent here. |
| Delimiters | XML tags | Markdown first, XML good, JSON poor for documents | Tags or Markdown, used consistently | No paper tested this | Wrap lessons in one consistent block, kept apart from the instructions. |
| Long data first, instructions last | Yes, up to 30% better | Both ends best; above the data if only once | Yes, plus a transition phrase | Middle is weakest [11]; with conflicting instructions, OpenAI's guide says the later one wins [V2] | Put a short version of the steps before the list and the full steps after it. This satisfies all three. |
| Quote the relevant parts first | Yes | Not stated | Not stated | Agree: reciting the evidence first helps [12]; factored checks [31] | In the review, quote the diff line for each lesson before giving a verdict. |
| Avoid over-prompting ("If in doubt, use [tool]", CRITICAL, MUST) | Causes overtriggering | GPT-5 overused search under "Be THOROUGH"; capitals are unnecessary | Avoid "overly persuasive language" | Agree: tool overuse exists [18] | Do not fix the one-in-71 fetch rate by shouting. Remove the need to fetch, or name the exact fetch (§2 table). |
| Verify before finishing | "verify your answer against [test criteria]" catches errors reliably, but Opus 5 over-verifies and such instructions should be removed for it | GPT-5: a self-made rubric before finalising | Template has a "Validate" step | Agree only when the criteria are concrete and external [21][23][29]; holistic self-review is lenient [25] | Verify against named checks and one yes/no question per lesson. Drop generic "verify your work" on models that verify unprompted. |
| Ask before hard-to-reverse actions | Yes, with examples | GPT-5: a lower threshold to ask before irreversible tools | Separate reads from writes; pause for permission | Agree [42] | Trigger (c) in §3. |
| Look things up before asking or guessing | "Never speculate about code you have not opened" | "use your tools to read files… do NOT guess"; a GPT-5 setting says do not ask to confirm assumptions | "Prefer calling the tool… over asking the user" | Agree: asking pays only for real ambiguity [39][40][41] | Research first; ask only on the §3 triggers. |
| Visible plan before acting | Rely on thinking on the newest models | GPT-5 is trained to give upfront plans and progress updates | A visible plan is "generally not necessary" for thinking models | Mixed [52][53][19] | Keep the commit step to a short disposition list, not a plan. |

## 3. Checking afterwards and escalating

**What the research says.**
- *When to ask.* Asking recovers up to 74% on underspecified tasks, yet models struggle to tell underspecified tasks from well-specified ones [39]. A scaffold that separates "is this underspecified?" from doing the work asked selectively: on the 156 tasks where it did not ask, it resolved 76.92%, against 77.56% for agents given full specifications [40]. The harness sets the ask rate as much as the model does: the same model asked in 31.8% of runs under one harness and 10.5% under another [42]. A useful filter keeps a question only if two plausible answers produce code that behaves differently. That method reached the best F1, with a 5.00% rate of questions on fully specified tasks [41]. Formally: ask only when more than one option survives a calibrated prediction set. Doing so cut help requests by 10–24% at a guaranteed success rate [43][44]; uncertainty over what the user intends is another usable signal [45].
- *Options with a recommendation.* In KnowNo, the help request *is* the set of surviving options [43]. Collaborative agents beat autonomous ones with real users (win rates 66–86%), but communication failed in 65% of cases [46]. People agree with a wrong AI more often when checking is costly [47], so a time-poor user will tend to rubber-stamp a recommendation. Attach the evidence that makes checking cheap. I found no coding-agent study comparing options plus a recommendation against the agent deciding alone.
- *Research before acting.* Models misjudge whether a lookup is needed in both directions: they skip needed calls [16][17] and overuse tools [18]. Make named lookups mandatory instead of leaving them to discretion.
- *Checking each constraint separately* is supported (§1, review) [28][29][30][31]. Two cheap additions: reason before the verdict, or append "Wait" [24][26]; and review the diff in a fresh context, as someone else's code, without the author's summary [24][50].

**Lesson types.**

| Type | After acting | Escalate only when |
|---|---|---|
| Decision | Confirm the diff leaves it intact (run its check if it has one). | The task cannot be done without reversing it. Ask before editing, with options and a recommendation [42][43]. |
| Lesson with a stored check | Run the check, fix on failure, re-run the tests. | Passing the check would mean breaking what the user asked for [21][23][36]. |
| UNCHECKED lesson | Read the governing files. Follow the code for descriptions, and report disagreements. | Never; report instead [5]. |
| Vague lesson | Look it up first: the full lesson, the files it names, its `found_by` evidence. | Two readings survive and they produce different code; ask with options. Otherwise choose one and state the assumption in the report [41][39][40]. |

**Per-task protocol.**
1. **Brief (okl).** Up to 5 lessons in full, worded as instructions. Then the disposition list, the decisions, and the checks okl will run.
2. **Commit (agent, before the first edit).** One line per briefed lesson saying whether it applies and why, plus, for each that applies, the step that will satisfy it [12][52][4].
3. **Act.**
4. **Verify.**
   - Run every stored check.
   - For each unchecked lesson that applies, answer one yes/no question against the diff, one lesson at a time, quoting the line [31][29][28].
   - For the top lessons, run a fresh-context pass over the diff alone, without the agent's summary [50][24][25].
   - Keep this step concrete: named checks and named lessons. Anthropic's guide warns that generic "verify your work" text causes over-verification on its newest Opus [V1].
5. **Escalate rarely, and only on these triggers:**
   - (a) the task needs a Decision reversed;
   - (b) after looking things up, two readings remain and they produce different code;
   - (c) the action is irreversible or wide in scope [42];
   - (d) a check fails and its fix conflicts with the task.

   Each escalation is one question, with options, a recommendation and the evidence. Everything else goes in the report.
6. **Report.** One line per lesson, with evidence. okl re-runs the checks itself when the agent stops, rather than trusting the report [49][51].

## 4. Ranked changes (expected benefit against cost)

1. **Rewrite the framing lines (§2 table).** Cost: text only. Benefit: the largest measured effects per word, a 14-point gap for conditional wording [4] and 4.2%→91.4% for code precedence [5]. Test on the seeded tasks first, because which wording works best differs by model [4].
2. **Reorder the review output.** Wrap the lesson list in one delimited block, put a short version of the steps before it, and put the full steps after it. Cost: trivial. Benefit: follows all three model makers' guides [V1][V2][V4] and avoids the middle of the context [11]. Change 5 shrinks the list itself.
3. **Stop relying on optional fetches.** okl picks the lessons, injects the top ones in full, and asks for a disposition on the rest. Cost: low. Benefit: addresses the one fetch in 71 [14][15][4].
4. **Turn high-stakes lessons that go against the model's default into gates.** Cost: per lesson. Benefit: the strongest evidence of any change [21][36][37][6].
5. **Rebuild the review.**
   - okl preselects lessons from the diff (governed files and matched terms) instead of listing all 300.
   - Each lesson gets one factored yes/no check, in a fresh context, without the author's narrative, with reasoning before the verdict.
   - High-stakes items get a second model.

   Cost: medium, probably similar to the current 170k tokens. Benefit: addresses the 8-of-12 leniency and the 12-of-23 selection recall [25][24][31][50][34][35].
6. **Add the escalation triggers to the protocol.** Cost: low. Benefit: plausible, but the evidence comes from neighbouring domains [41][42][43].
7. **Add the Lessons report, verified by okl when the agent stops.** Cost: low to medium [49][50][51].
8. **Fix the measurement.**
   - Re-run the shown-against-unshown comparison on lessons that go against the model's default only [6].
   - Use several judges and report their agreement [25][35].

## 5. What the research leaves open

- **Per-task injection is untested.** Every context-file study uses a static file. None tests lessons chosen by retrieval and changed on every prompt.
- **okl's preselection against the agent's.** Whether okl's deterministic preselection beats the agent's own selection for review is untested; okl's retrieval recall sets the ceiling.
- **Code precedence for defect lessons.** The code-precedence study tested conventions only [5]. Following the code could spread an existing defect.
- **Wording effects are model-specific** [4]. Re-test whenever the model changes.
- **Options with a recommendation for time-poor users.** There is no coding-agent evidence, and the overreliance research cuts against it [47].
- **What a commitment step changes.** It may change only the text, not the behaviour [19][16][48]. No coding-agent study measures compliance with and without one.
- **How much judges can agree.** No study gives an agreement ceiling for verdicts on whether a change breaks a repository-specific rule.
- **Intended against actual effect.** Most 2026 evidence comes from small samples: [2] and [3] say they are underpowered, [5] uses 40 projects, and [4] uses 86 tasks.

## Citations

All read from the arXiv PDF. "Read" lists the parts examined.

1. Gloaguen, Mündler-Sasahara, Müller, Raychev, Vechev. *Evaluating AGENTS.md: Are Repository-Level Context Files Helpful for Coding Agents?* Preprint, arXiv:2602.11988v3, 29 Sep 2026. https://arxiv.org/abs/2602.11988 (Read: abstract, §1, §4, App. B.)
2. Khatri. *Do Context Files Help Coding Agents? A Two-Agent Ablation Study on Real Repositories.* Preprint, arXiv:2607.27250v1, 28 Jul 2026. https://arxiv.org/abs/2607.27250 (Read: full text.)
3. McMillan. *Instruction Adherence in Coding Agent Configuration Files: A Factorial Study of Four File-Structure Variables.* Preprint, arXiv:2605.10039. https://arxiv.org/abs/2605.10039 (Read: abstract, §1.)
4. Tsuchida, Fan, Shimari, Kula, Matsumoto. *Do Coding Agents Follow AGENTS.md? The Effect of Policy Wording on Instruction Compliance.* Letter submitted to IEICE Trans. Inf. & Syst., arXiv:2611.04367v1, 3 Nov 2026. https://arxiv.org/abs/2611.04367 (Read: full text, Tables 3–4.)
5. Xu, Wu. *Stale Instruction Files Override the Code in Coding Agents: A One-Sentence Fix.* Preprint, arXiv:2610.30571v1, 22 Oct 2026. https://arxiv.org/abs/2610.30571 (Read: abstract, §1, method, recommendations.)
6. Huang, Que, Zeng, et al. (ByteDance Seed). *Harness-IF: Evaluating Instruction Following Across Instruction Surfaces in Coding Agents.* Preprint, arXiv:2608.11727v1, 12 Aug 2026. https://arxiv.org/abs/2608.11727 (Read: abstract, §1, §4.4, App. D.2.)
7. Jaroslawicz, Whiting, Shah, Maamari. *How Many Instructions Can LLMs Follow at Once?* Preprint, arXiv:2507.11538v1, 15 Jul 2025. https://arxiv.org/abs/2507.11538 (Read: abstract, §3–4.)
8. Qi, Peng, Wang, et al. *AgentIF: Benchmarking Instruction Following of Large Language Models in Agentic Scenarios.* Preprint, arXiv:2505.16944v1, 22 May 2025. https://arxiv.org/abs/2505.16944 (Read: abstract, §1, §3.)
9. Wallace, Xiao, Leike, Weng, Heidecke, Beutel. *The Instruction Hierarchy: Training LLMs to Prioritize Privileged Instructions.* Preprint, arXiv:2404.13208v1, 19 Apr 2024. https://arxiv.org/abs/2404.13208 (Read: abstract, §1–2.)
10. Geng, Li, Mu, et al. *Control Illusion: The Failure of Instruction Hierarchies in Large Language Models.* Preprint, arXiv:2502.15851v4, 4 Dec 2025. https://arxiv.org/abs/2502.15851 (Read: abstract.) Not cited in the body. Its finding that framing by authority or consensus outweighs system and user roles is a lead to test, from one source.
11. Liu, Lin, Hewitt, Paranjape, Bevilacqua, Petroni, Liang. *Lost in the Middle: How Language Models Use Long Contexts.* TACL 2024; arXiv:2307.03172v3. https://arxiv.org/abs/2307.03172 (Read: abstract.)
12. Du, Tian, Ronanki, et al. *Context Length Alone Hurts LLM Performance Despite Perfect Retrieval.* Preprint, arXiv:2510.05381v1, 6 Oct 2025. https://arxiv.org/abs/2510.05381 (Read: abstract, §1, mitigation.)
13. Levy, Jacoby, Goldberg. *Same Task, More Tokens: the Impact of Input Length on the Reasoning Performance of Large Language Models.* arXiv:2402.14848v2, 10 Jul 2024. https://arxiv.org/abs/2402.14848 (Read: abstract.)
14. Liu, Ji, An, Jaakkola, Zhang, Chang. *How Well Do Agentic Skills Work in the Wild: Benchmarking LLM Skill Usage in Realistic Settings.* Preprint, arXiv:2604.04323v1, 6 Apr 2026. https://arxiv.org/abs/2604.04323 (Read: abstract, §4.)
15. Nakasuji. *Skill Blocks: How Should an Agent Load Its Skill?* Preprint, arXiv:2608.14943v1, 14 Aug 2026. https://arxiv.org/abs/2608.14943 (Read: abstract, SearchQA results.)
16. Cheng, Fan, JafariRaviz, Rezaei, Feizi. *Model-Adaptive Tool Necessity Reveals the Knowing-Doing Gap in LLM Tool Use.* Preprint, arXiv:2605.14038v3, 22 Oct 2026. https://arxiv.org/abs/2605.14038 (Read: abstract.)
17. Ross, Mahabaleshwarkar, Suhara. *When2Call: When (not) to Call Tools.* arXiv:2504.18851v1, 26 Apr 2025. https://arxiv.org/abs/2504.18851 (Read: abstract.)
18. Qian, Acikgoz, Wang, et al. *SMART: Self-Aware Agent for Tool Overuse Mitigation.* arXiv:2502.11435v2, 24 May 2025. https://arxiv.org/abs/2502.11435 (Read: abstract.)
19. Schmied, Bornschein, Grau-Moya, Wulfmeier, Pascanu. *LLMs are Greedy Agents: Effects of RL Fine-tuning on Decision-Making Abilities.* Preprint, arXiv:2504.16078v1, 22 Apr 2025. https://arxiv.org/abs/2504.16078 (Read: abstract, §1.)
20. Huang, Chen, Mishra, et al. *Large Language Models Cannot Self-Correct Reasoning Yet.* ICLR 2024; arXiv:2310.01798v2. https://arxiv.org/abs/2310.01798 (Read: abstract.)
21. Kamoi, Zhang, Zhang, Han, Zhang. *When Can LLMs Actually Correct Their Own Mistakes? A Critical Survey of Self-Correction of LLMs.* arXiv:2406.01297v3, 3 Dec 2024. https://arxiv.org/abs/2406.01297 (Read: abstract, §1 summary.)
22. Olausson, Inala, Wang, Gao, Solar-Lezama. *Is Self-Repair a Silver Bullet for Code Generation?* ICLR 2024; arXiv:2306.09896v5. https://arxiv.org/abs/2306.09896 (Read: abstract.)
23. Gou, Shao, Gong, et al. *CRITIC: Large Language Models Can Self-Correct with Tool-Interactive Critiquing.* ICLR 2024; arXiv:2305.11738v4. https://arxiv.org/abs/2305.11738 (Read: abstract.)
24. Tsui. *Self-Correction Bench: Uncovering and Addressing the Self-Correction Blind Spot in Large Language Models.* COLM 2026; arXiv:2507.02778v3. https://arxiv.org/abs/2507.02778 (Read: abstract.)
25. Pombal, Rei, Martins. *Self-Preference Bias in Rubric-Based Evaluation of Large Language Models.* COLM 2026; arXiv:2604.06996v3. https://arxiv.org/abs/2604.06996 (Read: abstract.)
26. Chen, Wei, Zhu, Feng, Meng. *Do LLM Evaluators Prefer Themselves for a Reason?* Preprint, arXiv:2504.03846v3, 12 Dec 2025. https://arxiv.org/abs/2504.03846 (Read: abstract.)
27. Jin, Chen. *Uncovering Systematic Failures of LLMs in Verifying Code Against Natural Language Specifications.* arXiv:2508.12358v1, 17 Aug 2025. https://arxiv.org/abs/2508.12358 (Read: abstract.)
28. Cook, Rocktäschel, Foerster, Aumiller, Wang. *TICKing All the Boxes: Generated Checklists Improve LLM Evaluation and Generation.* Preprint, arXiv:2410.03608v1, 4 Oct 2024. https://arxiv.org/abs/2410.03608 (Read: abstract.)
29. Ferraz, Mehta, Lin, et al. *LLM Self-Correction with DeCRIM: Decompose, Critique, and Refine.* arXiv:2410.06458v2, 30 Jul 2026. https://arxiv.org/abs/2410.06458 (Read: abstract, §1.)
30. Zhang, Tang, Liu, et al. *Divide-Verify-Refine: Can LLMs Self-Align with Complex Instructions?* arXiv:2410.12207v2, 27 Feb 2025. https://arxiv.org/abs/2410.12207 (Read: abstract, §1.)
31. Dhuliawala, Komeili, Xu, Raileanu, Li, Celikyilmaz, Weston. *Chain-of-Verification Reduces Hallucination in Large Language Models.* arXiv:2309.11495v2, 25 Sep 2023. https://arxiv.org/abs/2309.11495 (Read: abstract, §3 variants.)
32. Sun, Xu, Li, et al. (ByteDance). *BitsAI-CR: Automated Code Review via LLM in Practice.* arXiv:2501.15134v1, 25 Jan 2025. https://arxiv.org/abs/2501.15134 (Read: abstract, §1.)
33. Vijayvergiya, Salawa, Budiselić, et al. (Google). *AI-Assisted Assessment of Coding Practices in Modern Code Review.* AIware 2024; arXiv:2405.13565v1. https://arxiv.org/abs/2405.13565 (Read: abstract.)
34. Kumar. *SWE-PRBench: Benchmarking AI Code Review Quality Against Pull Request Feedback.* Preprint, arXiv:2603.26130v1, 27 Mar 2026. https://arxiv.org/abs/2603.26130 (Read: abstract.)
35. Zeng, Shi, Han, et al. *Benchmarking and Studying the LLM-based Code Review (SWR-Bench).* arXiv:2509.01494v2, 5 Jun 2026. https://arxiv.org/abs/2509.01494 (Read: abstract.)
36. Wang, Poskitt, Sun. *AgentSpec: Customizable Runtime Enforcement for Safe and Reliable LLM Agents.* ICSE 2026; arXiv:2503.18666v3. https://arxiv.org/abs/2503.18666 (Read: abstract, §1.)
37. Debenedetti, Shumailov, Fan, et al. *Defeating Prompt Injections by Design (CaMeL).* Preprint, arXiv:2503.18813v2, 24 Jun 2025. https://arxiv.org/abs/2503.18813 (Read: abstract, §1.)
38. Su, Xu, Gao, et al. *Neuro-Symbolic Verification on Instruction Following of LLMs (NSVIF).* Preprint, arXiv:2601.17789v1, 25 Jan 2026. https://arxiv.org/abs/2601.17789 (Read: abstract, §1.)
39. Vijayvargiya, Zhou, Yerukola, Sap, Neubig. *Ambig-SWE: Interactive Agents to Overcome Underspecificity in Software Engineering.* ICLR 2026; arXiv:2502.13069v3. https://arxiv.org/abs/2502.13069 (Read: abstract.)
40. Edwards, Schuster. *Ask or Assume? Uncertainty-Aware Clarification-Seeking in Coding Agents.* Preprint, arXiv:2603.26233v3, 7 Sep 2026. https://arxiv.org/abs/2603.26233 (Read: abstract, results, discussion.)
41. Fang, Li, Zhang, et al. *CONTRA: Discovering and Qualifying Behavior-Changing Questions for Selective Clarification in LLM Code Generation.* Preprint, arXiv:2610.01769v1, 1 Oct 2026. https://arxiv.org/abs/2610.01769 (Read: abstract, method, results table.)
42. Ji, Zhang, Xu, et al. *Coding Agents Are Guessing: Measuring Action-Boundary Violations in Underspecified DevOps Instructions (UnderSpecBench).* Preprint, arXiv:2607.02294v1, 2 Jul 2026. https://arxiv.org/abs/2607.02294 (Read: abstract, takeaways, §VI.)
43. Ren, Dixit, Bodrova, et al. *Robots That Ask For Help: Uncertainty Alignment for Large Language Model Planners (KnowNo).* CoRL 2023 (PMLR 229); arXiv:2307.01928v2. https://arxiv.org/abs/2307.01928 (Read: abstract, §1, §3.)
44. Liang, Zhang, Fisac. *Introspective Planning: Aligning Robots' Uncertainty with Inherent Task Ambiguity.* NeurIPS 2024; arXiv:2402.06529v4. https://arxiv.org/abs/2402.06529 (Read: abstract, metrics.)
45. Zhang, Choi. *Clarify When Necessary: Resolving Ambiguity Through Interaction with LMs.* arXiv:2311.09469v1, 16 Nov 2023. https://arxiv.org/abs/2311.09469 (Read: abstract.)
46. Shao, Samuel, Jiang, Yang, Yang. *Collaborative Gym: A Framework for Enabling and Evaluating Human-Agent Collaboration.* ICLR 2026; arXiv:2412.15701v6. https://arxiv.org/abs/2412.15701 (Read: abstract.)
47. Vasconcelos, Jörke, Grunde-McLaughlin, Gerstenberg, Bernstein, Krishna. *Explanations Can Reduce Overreliance on AI Systems During Decision-Making.* arXiv:2212.06823v2, 26 Jan 2023. https://arxiv.org/abs/2212.06823 (Read: abstract.) Its first version predates 2023.
48. Chen, Benton, Radhakrishnan, et al. (Anthropic). *Reasoning Models Don't Always Say What They Think.* Preprint, arXiv:2505.05410v1, 8 May 2025. https://arxiv.org/abs/2505.05410 (Read: abstract.)
49. Advani. *From Confident Closing to Silent Failure: Characterizing False Success in LLM Agents.* Preprint, arXiv:2606.09863v1, 1 Jun 2026. https://arxiv.org/abs/2606.09863 (Read: abstract, §1.)
50. Zhu, Yu, Li, Chen. *Who Verifies the Agent's Success Claim? Self-Report Leakage in GUI-Agent Completion Judging.* Preprint, arXiv:2610.29609v1, 21 Oct 2026. https://arxiv.org/abs/2610.29609 (Read: abstract.)
51. Bouzenia, Cadar, Pradel. *Evaluating LLM Agents on Automated Software Analysis Tasks.* arXiv:2604.11270v3, 30 Jul 2026. https://arxiv.org/abs/2604.11270 (Read: abstract, results.)
52. Jiang, Dong, Wang, et al. *Self-planning Code Generation with Large Language Models.* ACM TOSEM; arXiv:2303.06689v5. https://arxiv.org/abs/2303.06689 (Read: abstract.)
53. Wang, Xu, Lan, et al. *Plan-and-Solve Prompting.* arXiv:2305.04091v3, 26 May 2023. https://arxiv.org/abs/2305.04091 (Read: abstract.)
54. Xie, Zhang, Chen, Lou, Su. *Adaptive Chameleon or Stubborn Sloth: Revealing the Behavior of Large Language Models in Knowledge Conflicts.* ICLR 2024; arXiv:2305.13300v4. https://arxiv.org/abs/2305.13300 (Read: abstract.)
55. Panickssery, Bowman, Feng. *LLM Evaluators Recognize and Favor Their Own Generations.* arXiv:2404.13076v1, 15 Apr 2024. https://arxiv.org/abs/2404.13076 (Read: abstract.) Supports [25]: self-recognition correlates linearly with self-preference.
56. Xu, Zhu, Zhao, Pan, Li, Wang. *Pride and Prejudice: LLM Amplifies Self-Bias in Self-Refinement.* arXiv:2402.11436v2, 18 Jun 2024. https://arxiv.org/abs/2402.11436 (Read: abstract.)
57. Lulla, Mohsenimofidi, Galster, Zhang, Baltes, Treude. *On the Impact of AGENTS.md Files on the Efficiency of AI Coding Agents.* arXiv:2601.20404v2, 30 Mar 2026. https://arxiv.org/abs/2601.20404 (Read: abstract.)

**Model makers' guidance** (vendor documentation, not peer-reviewed; read 10 Nov 2026; named as sources, not as recommended products):

- V1. Anthropic. *Prompting best practices* (Claude prompt engineering documentation). https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/claude-prompting-best-practices (Read: the sections "Be clear and direct", "Add context to improve performance", "Structure prompts with XML tags", "Long context prompting", "Control the format of responses", "Tool usage", "Overthinking and excessive thoroughness", "Leverage thinking", "Balancing autonomy and safety", "Minimizing hallucinations in agentic coding".)
- V2. OpenAI. *GPT-4.1 Prompting Guide* (cookbook). https://developers.openai.com/cookbook/examples/gpt4-1_prompting_guide (Read: instruction following, long context, delimiters, agentic reminders. The guide was written for GPT-4.1, so its placement advice may not carry over to later models.)
- V3. OpenAI. *GPT-5 Prompting Guide* (cookbook). https://developers.openai.com/cookbook/examples/gpt-5/gpt-5_prompting_guide (Read: agentic eagerness, tool preambles, contradictory instructions, self-reflection. It gives no placement advice for long context.)
- V4. Google. *Prompt design strategies* (Gemini documentation). https://aistudio.google.com/docs/prompting-strategies, redirected from ai.google.dev (Read: core principles, placement, structure, the agentic template. The page shows no date.)
