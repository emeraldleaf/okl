# How okl decides what to brief

Part of okl's documentation. The [README](../README.md) is the short version of okl. This page
covers one question in depth: before every prompt, which lessons should okl put in front of
your coding agent, and when should it put in nothing? It starts in plain language, defines
every term it uses, and then gives the design with the evidence for each choice, the
alternatives that lost and why, and how all of it was measured. Every figure names a committed
receipt in [evals/results/](../evals/results/) or a paper read from its own pages.

Written 2026-10-26 for #291. The pre-registration and the full result are §4w of
[the eval report](../evals/REPORT.md).

## The short version

**The job.** okl keeps lessons: rules your team follows, defects you already paid for,
decisions you made on purpose. Before your agent starts on a prompt, okl picks the few lessons
that apply and puts them in front of it. Pick the right ones and the agent avoids a known
mistake. Pick wrong ones and it reads noise: research on long contexts finds that even one
irrelevant passage can lower a model's answer quality (Chroma's
[Context Rot](https://www.trychroma.com/research/context-rot), 2025 [12]). So the job has two
halves of equal weight: brief the lesson that applies, and brief **nothing** when nothing does.

**Why it is hard.** A developer describes the work in their own words ("users keep getting
logged out after a refresh"); the lesson is written in the words of whoever learned it ("keep
access tokens out of web storage"). They can share no word at all. And most prompts in a real
session have no subject of their own: "ok", "merge it", "what about the other one?". Measured
on 550 such prompts from real sessions, okl's original pipeline briefed something on more than
half of them. On real tasks it briefed nearly eight lessons a prompt, and about one in eleven of
them applied.

**What okl does now**, in three steps:

1. **When a lesson is recorded**, it gets *triggers*: a handful of phrasings of the moments it
   applies, in a developer's own words: the task you would be doing, the error you would see,
   the other names people use for it. The prompt or error that actually led to the lesson is
   the best trigger of all.
2. **When a prompt arrives**, okl searches every lesson's text, triggers included.
3. **Then it decides**: a lesson is briefed only when what it says it is about shares enough of
   the prompt's subject: three subject words, or two rare ones. That line was set on 282 real
   prompts that should get nothing, so that at most about one in twenty such prompts gets
   anything; 268 more, which the line never saw, test it. Never more than five lessons. And a message the agent's harness wrote (a task
   notification, a sub-agent's report) is never briefed: nobody typed it.
4. **Nothing that matched is hidden.** What clears the line is shown in full. Everything else
   that matched (what cleared the line past five, and what the original word floor keeps)
   gets one line each: its id, title and the start of its fix, up to twelve. The agent can
   read any of them with `okl show <id>`.

**What it bought** (the benchmark below, numbers from committed receipts):

| | the original pipeline | triggers + the calibrated decision |
|---|---|---|
| the lesson that applies is briefed (held-out queries) | 74.4% [68.5, 80.4] | **90.0% [86.7, 93.3]** |
| lessons briefed per query | 11.8 | **4.7** |
| real prompts with no subject that got anything | 149 of 268 (55.6%) | **9 of 268 (3.4%)** |
| work per prompt | a full-text search | the same search, a word count and a rarity scan of the store; no model |

**And what it costs, on real prompts and a real store** (REPORT §4x, held out: 120 prompts a
person typed, judged with their context, against a store of 143 recorded lessons and the seed
packs):

| | the original pipeline | the line alone | + triggers on recorded lessons | **the default: two tiers** |
|---|---|---|---|---|
| applying lessons named (of 115 any version found) | 90 | 31 | 38 | **102** |
| lessons shown in full per prompt | 7.7 | 1.6 | 1.8 | **1.8**, and 7.6 named in a line |
| share of the lessons shown in full that apply | 9.8% | 16.5% | 17.8% | **17.8%** |

(REPORT §4x and §4y, receipt `real-20261026-heldout-tiers.txt`.) The benchmark's queries are
fuller than what people type, so on real prompts the line alone trades recall for precision: a
lesson it shows is about 1.7 times as likely to apply, but it surfaced about a third of what
the original did. So the default names the rest in a line each. It reaches more applying
lessons than the original, at about half its size: a median of 721 tokens a prompt against
1,424 (`real-20261026-heldout-size.txt`). An agent acted on a lesson named in one line about as
it did on the lesson in full, without opening it (REPORT §4aa). That rests on the one task where
nothing else showed the same fix, so it is a small result, not a settled one.

A team's own lessons need triggers to reach the first tier: `okl triggers` lists the ones that
have none, `/triggers` drafts them in Claude Code, and the briefing says how many are missing.
`--decision calibrated` gives the line alone, the smallest briefing; `--decision floor` keeps
the original rule, every match in full.

**A warm model, once you index a store.** A small embedding model (EmbeddingGemma-300m), added to the word
count rather than replacing it, took held-out recall from 90.0% to **95.2%** on the benchmark
(at full precision; the int8 file `okl warm` runs measured 92.0% against 92.4% on the selection split),
most of it on paraphrases. The prompt hook starts a new process for every prompt, and loading
the model there costs a second or two, so `okl warm` keeps it loaded in a local process instead
(int8, a 309.5 MB file). On real held-out prompts it showed 46 applying lessons in full against 38,
at 23.0% precision against 17.8%, and named 107 against 102, adding a median of 114 ms to a prompt
(REPORT §4z). It holds about 1.6 GB of memory from startup (it runs one inference before it serves), more than the
bound set before measuring. So it runs only where you ask for it: once `okl warm index` has
embedded a local store's lessons (the `warm` extra), its briefings use it, and `"warm": false` in
`.okl/config.json` or `OKL_WARM=0` turns it off. That default is a decision recorded in §4z, not a
passed prediction.

**What did not earn a place**, each measured on the same benchmark or settled by the research
read for it: a cross-encoder reranker, a knowledge graph or ontology, generating text at query
time, and putting an index of every lesson in the context for the agent to fetch from. Why each
lost is under [What is not in the pipeline](#what-is-not-in-the-pipeline-and-why).

## Words used here

- **Lesson**: one record in okl's store: a rule, a past defect, a gate, a decision. It has a
  title, a body, a *symptom* (what you see when it applies), *aliases* (other names for it), a
  fix, and now *triggers*.
- **Briefing**: the lessons okl injects before a prompt. The *decision* is the step that picks
  them from the candidates the search found.
- **Recall**: of the queries that have a lesson that applies, the share whose briefing contains
  it. *hit@k*: the share where that lesson is among the first k candidates.
- **Abstention**: briefing nothing. The **false-briefing rate** is the share of prompts that
  should get nothing which got something.
- **Full-text search, BM25**: matching on shared words, weighting rare words above common ones.
  okl uses SQLite's FTS5, which ranks by BM25.
- **IDF** (inverse document frequency): how rare a word is across the store. A word in one
  lesson is rare; a word in every lesson tells you nothing.
- **Embedding, dense retrieval**: turning text into a vector so that texts with similar meaning
  sit close together, even with no words in common. A **cross-encoder reranker** reads the
  prompt and a candidate together and scores how well they match.
- **Write-time expansion**: adding text to a document when it is stored, so that later
  searches find it (doc2query, HyPE). **Query-time expansion** does the same to the prompt on
  every search (HyDE), which needs a model on every prompt.
- **Calibration**: choosing a threshold from data so that it means something measurable.
  **Split conformal prediction**: a calibration method with a guarantee. Score held-aside
  examples of what should be refused; set the line just above the right order statistic;
  then, for new examples drawn from the same population, the share that crosses the line is at
  most the target rate, whatever the score's distribution.
- **Selection split, held-out split**: the benchmark's queries are divided. Designs are chosen
  on the selection split. The held-out split is run once, after the choice is written down, so
  the result cannot have been tuned to it.
- **Bootstrap interval**: a 95% range for a result, found by resampling the benchmark many
  times. Here it resamples whole lessons, because three queries about one lesson are not three
  independent tests.

## The design, step by step

### 1. Triggers: index the moments, not only the lesson

The largest gains in okl's retrieval history came from writing down, for each lesson, the
words people use when it bites. A *symptom* line on twenty lessons took the probe's bug-report
row from 2 to 3 of 8 (REPORT §4o); *aliases* on every advice lesson took it from 3 to 8 of 8
(§4p). Triggers generalise that. Each
lesson carries a handful of whole phrasings, of three kinds: the work you would be doing when
it matters, what you would observe once it had already gone wrong, and the other words people
use for the same situation.

This is write-time document expansion, a well-studied idea.

- **Doc2Query** generates the questions a passage answers and indexes them with it. Filtering
  those down to the good ones (Doc2Query--) made BM25 markedly better: MS MARCO RR@10 went from
  0.185 for BM25 to 0.279 with eighty generated queries per passage, and to 0.323 keeping the
  best 30% of them [2].
- **HyPE** generates hypothetical prompts per chunk and indexes them separately. On a narrow,
  single-topic corpus, the closest published analogue to a team's lesson store, recall rose
  sharply: on 1,324 chunks and 80 questions, its retriever's claim recall at 10 went from 36.8
  to 81.4, while generating a hypothetical answer at query time (HyDE) gave 36.4. Across its six
  datasets the gains did not reach significance at 0.05 [1].
- **Anthropic's Contextual Retrieval** does a version of it for both BM25 and embeddings: each
  chunk gets a short, model-written context before it is indexed [13].

Two findings from that literature shaped how okl stores triggers:

- **Generated text works best in its own index**, fused with the document's, rather than
  appended to it. For a dense retriever, appending the generated queries was mixed (FiQA
  nDCG@10 0.332 to 0.322), while a separate index fused with the document's improved all five
  datasets (SciFact 0.657 to 0.729) [3].
- **Expansion helps weak first-stage retrievers and can hurt strong ones**: it "improves scores
  for weaker models, but generally harms stronger models" [4]. okl's first stage is full-text
  search, the weak kind, so expansion is where the gain is.

Triggers live in their own full-text column, weighted like the symptom. A lesson recorded in a
session can carry *observed* triggers, the prompt or error that led to it, which no model
has to imagine: `okl record --trigger "..."`, repeatable. The seed packs' triggers were written
by a model from each lesson's text, under a protocol that kept them blind to the benchmark's
queries ([how](../evals/bench/GENERATION.md)).

### 2. Search

Unchanged in kind: SQLite FTS5, BM25, over every field, now including triggers. Thirty-six
candidates per prompt. A semantic arm (local embeddings) and a cross-encoder reranker remain
available behind flags; neither earned a place by default (below).

### 3. The decision: a line set on the prompts that should get nothing

The original pipeline had a *floor*: keep a candidate that shares two words with the prompt,
or one in its title or symptom, then brief up to twelve. A single shared word is weak evidence,
and twelve is a lot to read. The calibrated decision replaces both.

- **The score.** How many of the prompt's subject words the candidate's *about-text* holds: its
  title, symptom, aliases and triggers, what the lesson says it is about and when it applies
  (not its body, which explains). Ties are broken by how rare those words are in the store,
  relative to the rarest a word there can be, so the score means the same at thirty lessons and
  at thirty thousand.
- **The line.** Set by split conformal prediction on half of the 550 real prompts with no
  subject, at a target of 5%: the line sits just above the score that 95% of those prompts'
  best candidates stay under. In words: **three shared subject words, or two nearly as rare as a
  word found in one lesson.** On the other half, which the line never saw, it briefed
  9 of 268 (3.4%).
- **The cap.** At most five lessons, best first.

Why this score and not another: on the selection split, scoring by the *share* of the prompt's
subject a lesson covers was useless (a one-word prompt fully covered scores the same as a
thirty-word bug report, so the line saturates at 1.0); summed rarity worked but abstained more;
the shared-word count with a rarity tie-break was best (§4w's selection table).

Choosing a threshold from labelled examples, rather than by hand, is the approach the
reranker-abstention literature recommends. There, a linear model over the sorted top-10
reranker scores abstained better on average than reference-free heuristics, from about forty
labelled queries, though it did not hold up under a change of domain [6]. Conformal prediction
adds a guarantee to it [15, 16].

### 4. The second tier: name what the line leaves out

On real prompts the line was too selective. Of the 76 applying lessons it missed on the tuning
half, 73 were among the 36 candidates: 57 fell below the line, sharing one word with what the
lesson says it is about, or two common ones, and 14 cleared it but were cut by the cap of five
(REPORT §4y). A cross-encoder can reorder such candidates but cannot say which belong (§4t).
So the decision keeps its line for what is shown in full and names the rest:

- **What is named.** What cleared the line past the cap, then what the original word floor
  keeps (two shared subject words, or one in the title or symptom that few lessons share), each
  once, up to twelve.
- **How.** One line each: the id, the title, and the first sentence of the fix, cut at a word
  to 160 characters, under "Also matched (N)". The agent reads the whole lesson with `okl show
  <id>` or the `okl_get` tool.
- **What it costs.** About 64 tokens a line, against about 160 for a lesson shown in full. On
  prompts that ask for no work it names something about as often as the original pipeline
  briefed (43 of 60 held out), so a median such prompt costs 362 tokens instead of 72.

A listed lesson is not logged as briefed, so `okl metric` and `okl recap` count only what was
shown in full.

### 5. The gate: prompts nobody typed

Claude Code delivers task notifications, sub-agent reports and system reminders as user turns,
and the prompt hook saw each one as a prompt to brief. In the session that built the benchmark
that was dozens of briefings of up to twelve lessons each, on text like `<task-notification>`.
Such a prompt is now briefed nothing, under either decision.

## What is not in the pipeline, and why

| candidate | what was measured or read | verdict |
|---|---|---|
| an embedding model in the hook | seven local models (REPORT §4w). Added to the word count, the best, EmbeddingGemma-300m, took held-out recall from 90.0% to 95.2%, mostly paraphrases. Loading it in a new process costs about 2 s, on every prompt | on once a store is indexed: `okl warm` keeps it loaded in a local process, about 1.6 GB (REPORT §4z) |
| a cross-encoder reranker | two current cross-encoders as the decision: 22.5% and 31.3% recall at the line that holds subject-less prompts near 5%, at 1.2 and 2.5 s a prompt (REPORT §4w). A reranker's scores rank one prompt's candidates; they are not comparable across prompts | off: it cannot tell when to brief nothing, and costs over a second per prompt |
| a knowledge graph or ontology | independent evaluations find graph retrieval ties or loses on single-hop lookups and abstains worse on queries with no answer (on MultiHop-RAG's queries with no answer in the corpus, plain RAG was right 96.01% of the time against 85.71% for HippoRAG 2 and 19.27% for community GraphRAG's global mode, and on NQ plain RAG scored 64.78 F1 against HippoRAG 2's 61.03 [7]; HippoRAG 2's own gains concentrate on multi-hop sets (2Wiki recall@5 90.4 against 76.5; NQ 78.0 against 75.4) [8]; on MemoryAgentBench's accurate-retrieval tasks BM25 averaged 60.5, above GraphRAG 40.9, Zep 37.5 and Mem0 32.6 [9]); okl's own stack-tag classification hid relevant lessons and measured worse (REPORT §4d) | not built; okl's typed relations (a gate *catches* a defect, a rule *supersedes* another) are used after ranking, never to find lessons |
| query-time generation (HyDE, rewriting) | needs a language model on every prompt, seconds on a laptop; HyPE's comparison found query-time HyDE gained nothing where write-time expansion gained a lot (on a single-topic corpus of 1,324 chunks and 80 questions, its retriever's claim recall at 10 went from 36.8 to 81.4, while generating a hypothetical answer at query time (HyDE) gave 36.4; across its six datasets the gains did not reach significance at 0.05 [1]) | not built |
| an index of every lesson for the agent to fetch from | the agent fetched once in 71 tries (REPORT §4r); agents rarely pull context they are not handed (in Vercel's evals a skill was never invoked in 56% of cases and scored the same 53% as no docs [10]; a study of coding agents and contribution rules found the policy file opened in 12 of 347 runs [11]) | not built |
| reciprocal-rank fusion | lost to a tuned convex combination in the fusion literature (a tuned convex combination beat RRF (MS MARCO NDCG@1000 0.454 against 0.425), its one weight converging with under 5% of the training queries [5]) and on okl's own probe (§4q) | `linear` fusion is the semantic arm's mode |

## How it is measured

**The benchmark** (`evals/bench/`):

- **Corpus**: the twelve committed seed packs, 183 records, rebuilt on every run so anyone can
  reproduce a receipt.
- **Queries**: 519 (a ticket, a paraphrase and a bug report per advice lesson), written by one
  model from the lesson alone, under a protocol written before any query existed. Its
  structural rules are checked mechanically; the paraphrase may not use any content word from
  the lesson's title.
- **Prompts that should get nothing**: 550 real prompts with no subject of their own, from one
  developer's Claude Code sessions, labelled by a Claude sub-agent among 1,367. They, and the
  real task prompts sampled for judging, are never committed, published or quoted; receipts
  carry counts and a hash.
- **Splits**: queries divided by lesson into a selection half (249) for choosing and a held-out
  half (270) run once; null prompts halved into a calibration half and an unseen half.
- **Intervals**: 95% bootstrap intervals over lessons for recall, Wilson intervals for rates.

**Results** (§4w; receipts named there):

| held out: 270 queries | the original pipeline | + triggers only | **+ triggers and the decision** | + an embedding model (needs a loaded process) |
|---|---|---|---|---|
| the lesson that applies is briefed [95%] | 74.4% [68.5, 80.4] | 84.1% [79.3, 88.5] | **90.0% [86.7, 93.3]** | 95.2% [93.0, 97.4] |
| bug reports / paraphrases / tickets, of 90 each | 78 / 52 / 71 | 84 / 63 / 80 | **86 / 73 / 84** | paraphrases 81 |
| that lesson ranked first by the search, before the decision | 40.4% | 68.1% | 68.1% | |
| lessons briefed per query | 11.8 | 11.8 | **4.7** | 4.5 |
| prompts with no subject that got anything | 149 of 268 | 149 of 268 | **9 of 268** | 12 of 268 |

Read across the columns:

- **Triggers fix the order.** The right lesson moves from first place on 40% of queries to 68%.
- **The decision turns that order into a short briefing, and into silence when nothing
  applies.** The briefing drops from twelve lessons to under five, and the prompts with no
  subject drop from more than half briefed to one in thirty.
- **The model adds the paraphrases that word matching misses.**

Every alternative measured on the selection split, the ones that lost included, is in §4w with
its receipt.

**On real prompts, against a real store** (REPORT §4x). Synthetic queries can flatter a system
built from text the same model family wrote. In one study, systems scored higher on synthetic
than on real queries, with a bias toward systems that match the generator's model, significant
for MAP though not for NDCG, on 82 queries [14]. Both the queries and the triggers here came
from Claude models.

A second instrument (`evals/bench/real_prompts.py`) measures what the benchmark cannot:

- **Prompts.** Prompts a person actually typed, each with the turns before it.
- **Store.** A real store, as it stood at each prompt.
- **Judging.** Every lesson any version briefs is judged, with the prompt's context, as
  applying or not, blind to which version briefed it.

It also has a tuning half and a held-out half, with predictions written down before the
held-out half was run. Its findings:

- **Most real prompts have nothing to brief.** Only a third to two fifths of task prompts had
  any lesson the judge said applied.
- **The calibrated decision is more precise and finds less.** It briefs a fifth as many
  lessons as the original or fewer, each about 1.7 times as likely to apply, and surfaces a
  quarter to a third of the applying lessons the original did.
- **Two tiers find the most.** Showing the line's lessons in full and naming the rest reached
  102 of 115 applying lessons held out, against the original's 90, at about half its size
  (REPORT §4y, pre-registered).
- **Recorded lessons need triggers.** Without them, the decision found 3 of the 55 applying
  recorded lessons on the tuning half. With triggers written for them (blind to every prompt),
  it found more and more precisely: on the held-out half, 38 applying lessons at 17.8%, against
  31 at 16.5%. That is the best balance of precision and recall of every option measured,
  lower lines and a capped floor included.
- **Conversation context did not help.** Adding the previous prompt, or the agent's last
  reply, to the search made the briefing less precise than the calibrated decision alone.
- **A code-only fallback did not earn a place.** Scoring a lesson without triggers on its body
  too found one more lesson held out, at slightly lower precision.

An earlier, smaller judged run (REPORT §4w) sampled 100 prompts, 15 of which turned out to be
the A/B harness's own tasks; §4x supersedes it.

## Threats to validity

- **One model family wrote the queries and the triggers.** The judged-precision run on real
  prompts is the check, not a cure; observed triggers from real sessions are the long-term one.
- **One developer's prompts calibrated the line.** The guarantee holds for prompts like those.
  Another team's line is its own calibration; the procedure is in `evals/bench/run_v2.py`.
- **The benchmark's corpus is 183 records** (173 advice lessons), all with triggers. A live
  store holds lessons recorded without them, and the decision needs them: `okl record` asks for
  them, `okl triggers` lists the lessons that lack them, and the briefing says how many do.
- **The second tier is named, not shown.** Reach counts a lesson named in a line; whether an
  agent opens it, or acts on the line alone, is the next measurement. Its noise is the
  original's: 9.1% of everything named applies (REPORT §4y).
- **The benchmark measures retrieval, not behaviour.** Whether an agent writes better code with
  fewer, better-chosen lessons is a separate experiment on okl's agent harness.

## Reproduce it

```bash
python3 evals/bench/extract_prompts.py        # your own sessions' prompts, kept local
# label them NULL / TASK (see GENERATION.md), then:
PYTHONPATH=src python3 evals/bench/run.py --label control --split heldout
PYTHONPATH=src python3 evals/bench/run.py --label treatment --split heldout \
    --decision calibrated --triggers evals/bench/triggers.jsonl
PYTHONPATH=src python3 evals/bench/run_dense.py --split heldout --model google/embeddinggemma-300m \
    --base shared_words --weights 0,8 --triggers evals/bench/triggers.jsonl   # the model arm
```

## References

Read from each paper's own pages or tables on 2026-10-26 (pages and tables noted in #291).

1. Vake, Vičič, Tošić. *Bridging the Question-Answer Gap in Retrieval-Augmented Generation: Hypothetical Prompt Embeddings* (HyPE). University of Primorska and InnoRenew CoE. IEEE Access 13 (2025), [arXiv:2607.29402](https://arxiv.org/abs/2607.29402). Tables 3–5.
2. Gospodinov, MacAvaney, Macdonald. *Doc2Query--: When Less is More.* University of Glasgow. ECIR 2023, [arXiv:2301.03266](https://arxiv.org/abs/2301.03266). Table 1, §5.
3. Kuo, Chiu, Ma, Cheng. *Doc2Query++: Topic-Coverage based Document Expansion and its Application to Dense Retrieval via Dual-Index Fusion.* National Taiwan University. Preprint, [arXiv:2510.09557](https://arxiv.org/abs/2510.09557). Table 5, §4.2.4.
4. Weller, Lo, Wadden, Lawrie, Van Durme, Cohan, Soldaini. *When do Generative Query and Document Expansions Fail?* Johns Hopkins University and AI2. EACL 2024, [arXiv:2309.08541](https://arxiv.org/abs/2309.08541). Abstract.
5. Bruch, Gai, Ingber. *An Analysis of Fusion Functions for Hybrid Retrieval.* Pinecone. ACM TOIS 42(1), 2023, [arXiv:2210.11934](https://arxiv.org/abs/2210.11934). Table 2.
6. Gisserot-Boukhlef, Faysse, Malherbe, Hudelot, Colombo. *Towards Trustworthy Reranking: A Simple yet Effective Abstention Mechanism.* Artefact Research Center and CentraleSupélec. TMLR 2024, [arXiv:2402.12997](https://arxiv.org/abs/2402.12997). Tables 1, 4, 5.
7. Han et al. *RAG vs. GraphRAG: A Systematic Evaluation and Key Insights.* Michigan State University. [arXiv:2502.11371](https://arxiv.org/abs/2502.11371) v3, 2026. Tables 1–2.
8. Gutiérrez, Shu, Qi, Zhou, Su. *From RAG to Memory: Non-Parametric Continual Learning for Large Language Models* (HippoRAG 2). The Ohio State University. ICML 2025, [arXiv:2502.14802](https://arxiv.org/abs/2502.14802). Tables 3–4.
9. Hu, Wang, McAuley. *Evaluating Memory in LLM Agents via Incremental Multi-Turn Interactions* (MemoryAgentBench). UC San Diego. ICLR 2026, [arXiv:2507.05257](https://arxiv.org/abs/2507.05257). Table 3.
10. Gao. *AGENTS.md outperforms skills in our agent evals.* Vercel, 2026-01-27. [vercel.com/blog](https://vercel.com/blog/agents-md-outperforms-skills-in-our-agent-evals).
11. Yang, He, Zhou. *A First Look at Coding Agents' Compliance with AI Contribution Rules in Open-Source Communities.* Peking University. [arXiv:2607.26819](https://arxiv.org/abs/2607.26819), §4.1.
12. Hong, Troynikov, Huber. *Context Rot: How Increasing Input Tokens Impacts LLM Performance.* Chroma, 2025-07-14. [trychroma.com/research/context-rot](https://www.trychroma.com/research/context-rot).
13. Anthropic. *Introducing Contextual Retrieval.* 2024-09-19. [anthropic.com/news/contextual-retrieval](https://www.anthropic.com/news/contextual-retrieval).
14. Rahmani, Ramineni, Yilmaz, Craswell, Mitra. *Towards Understanding Bias in Synthetic Data for Evaluation.* University College London. CIKM 2025, [arXiv:2506.10301](https://arxiv.org/abs/2506.10301). §5, Table 2.
15. Lei, G'Sell, Rinaldo, Tibshirani, Wasserman. *Distribution-Free Predictive Inference for Regression.* Carnegie Mellon University. JASA 2018, [arXiv:1604.04173](https://arxiv.org/abs/1604.04173). §2, eq. (2).
16. Angelopoulos, Bates. *A Gentle Introduction to Conformal Prediction and Distribution-Free Uncertainty Quantification.* [arXiv:2107.07511](https://arxiv.org/abs/2107.07511). Theorem 1.
