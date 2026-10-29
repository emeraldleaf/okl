# Changelog

## Unreleased

The briefing now shows in full what clears a line set on real prompts that should get
nothing, read over write-time *triggers*, and names everything else that matched in a line
each, instead of showing up to twelve lessons by the word floor. The line was measured on a
benchmark built to decide (REPORT §4w; the design and its evidence:
[docs/RETRIEVAL.md](docs/RETRIEVAL.md)):

- held-out recall rose from 74.4% to 90.0%;
- lessons briefed per query fell from 11.8 to 4.7;
- prompts with no subject that got a briefing fell from 149 of 268 to 9;
- on prompts a person typed, against a real store of recorded lessons (REPORT §4x and §4y,
  held out), the line alone surfaced about a third of the applying lessons the floor did. So
  the default names the rest: it reaches 102 of the 115 applying lessons any version found,
  against the floor's 90. It shows 1.8 lessons a prompt in full instead of 7.7, 17.8% of which
  apply against 9.8%, and costs a median of 721 tokens a prompt against 1,424.

- **Two tiers are the default** (#291, REPORT §4y). A lesson is shown in full when its title,
  symptom, aliases and triggers hold three of the task's subject words, or two nearly as rare
  as a word in one record; at most five are. Everything else that matched (what cleared the
  line past five, and what the word floor keeps) is listed under "Also matched", one line each:
  id, title and the start of the fix, up to `--limit`. The agent reads any of them with `okl
  show <id>`. A listed lesson is not logged as briefed. A message a harness wrote (a task
  notification, a sub-agent's report) is briefed nothing, under every decision.
  `--decision calibrated` gives the first tier alone; `--decision floor` shows every match in
  full. `OKL_DECISION` or `"decision"` in `.okl/config.json` sets either for every check.
- **Lessons carry `triggers`**: whole phrasings of the moments a lesson applies, the request or
  error that led to it first. Set them with:
  - `okl record --trigger "..."` (repeatable);
  - `okl update <id> --trigger "..."` (an empty value clears them);
  - `okl_record` and `okl_update` over MCP;
  - a `triggers` list in a pack.

  `okl show` lists them. The bundled packs carry 1,730. `okl record` without one says on
  stderr what triggers do; the Stop hook, `/record` and the encoding-loop skill ask for them.
- **Upgrading: run `okl seed --refresh`, then `/triggers`.** `okl seed --refresh` brings the
  bundled packs' triggers into a store seeded before them, without importing the rest of each
  pack, and keeps what you added to those lessons (#214, below). Lessons you recorded have no triggers until you add them, and the default briefs them
  only when a prompt shares three words with their title, symptom or aliases. On a real store
  it found 3 of 55 applying recorded lessons that way (REPORT §4x). `/triggers` drafts them
  (`okl triggers` lists them; `okl update <id> --trigger "..."` adds one by hand). Until both
  are done, the hook's line says so.
- **`okl warm`, a local model that briefs by meaning too** (#293, REPORT §4z). `okl warm
  start` keeps EmbeddingGemma-300m (int8) loaded in a local process, `okl warm index` embeds a
  store's lessons, and from then on a check (or `--warm on`) adds 8 times a
  lesson's best cosine with the prompt to the line's score. On real held-out prompts it showed
  46 applying lessons in full against 38, at 23.0% precision against 17.8%, adding a median of
  114 ms to a prompt. It holds about 1.6 GB of memory from startup (it runs one inference before
  it serves), above the bound set before measuring, so by default it runs only for a local store
  you have indexed; an indexed shared database can use it with `"warm": true`. It applies to
  checks okl runs locally under the calibrated and tiered decisions: not to `--decision floor`,
  and not through a shared service, which answers with `warm_unavailable`. `"warm": false` or
  `OKL_WARM=0` turns it off, `okl warm stop` keeps it off until `okl warm start`, `index` or
  `serve`, and a store never indexed is briefed as before. The `warm` extra installs it.
- **`okl triggers` and `/triggers`.** `okl triggers` lists a store's own advice lessons that
  have no triggers. `/triggers` (Claude Code) drafts ten for each from the lesson itself and
  applies them once you confirm. Under the default and calibrated decisions, the hook's line
  names how many of a store's own lessons lack triggers once there are three or more. One or
  two are not named, and the floor decision does not count them, so a quiet line does not mean every
  lesson has triggers: `okl triggers` lists them all. On a real store, giving recorded lessons
  triggers raised what the briefing found (REPORT §4x).
- **Briefing size.** On real prompts the median briefing is 721 tokens, against 1,424 under the
  floor (REPORT §4y). On one representative task it is about 1,390 tokens, against 730 for the
  first tier alone and 1,730 under the floor's twelve
  ([receipt](evals/results/briefing-size-20261027-0132.json)). The action list (`--format
  actions`, `--compact`) carries the one-line entries too: about 350 tokens at `--limit 3`.
  On a prompt that asks for no work, the second tier names something about as often as the
  floor briefed.
- **Three behaviours that change with the default:**
  - a gate that catches a briefed defect is shown in full only when it clears the line itself;
    otherwise it can be named in a line (the floor keeps it);
  - `--hybrid`: a record found by meaning alone is shown in full only under `--decision
    floor`; under the default it can be named in a line;
  - what the cap of five cuts is named in a line, and `dropped_by_cutoff` counts what the
    second tier's limit cut.
- **A retrieval benchmark, `evals/bench/`.** It covers the seed corpus, 519 generated queries
  and real prompts kept local, with a split held out until the choice was written down. Every
  alternative measured on it is in REPORT §4w, the ones that lost included: two current
  cross-encoder rerankers as the decision, five embedding models and two late-interaction
  models.
- **`okl seed` keeps what a pack leaves out, and never stamps a lesson** (#214). A re-seed
  rewrote every field and blanked those the pack does not set, so `files` and triggers added
  with `okl update` went, and with the files their proof, leaving drift nothing to check. After
  a re-seed that changed a lesson's files, the next one also dropped its stored check. Now the
  pack owns what it says and its silence keeps the store's value; the stored check stays while
  the files do; and a pack's `"verified": true` stamps only a lesson new to the store.
- **The drift snapshot refuses to lose rules** (#213). The store is per clone, so a teammate's
  `okl verify` rewrote `okl-drift.json` without the rules only another clone held, and they
  left CI's gate unannounced; a worktree with no `.okl/config.json` wrote one for a repo named
  after its folder. Every refresh now compares with the committed snapshot and refuses to drop
  a rule this store does not hold, or to change its repo, naming them. Retiring a lesson still
  takes it out. `okl export --drift --allow-shrink` writes it anyway.
- **The okl MCP server starts without your shell's PATH** (#206). `.mcp.json` named a bare
  `okl`, so a Claude Code session launched from an IDE had no okl tools ("Executable not found
  in $PATH: okl") while its hooks worked. The server now starts through
  `.claude/hooks/okl-mcp.sh`, which finds okl as the hooks do, from the path `okl init` pinned;
  the plugin starts its copy. Re-run `okl init` to upgrade an existing `.mcp.json`.
- **The person's line says what the tiered default did.** It said "4 more listed by title" about
  a list only the agent sees; it says "4 related listed for the agent". With nothing in full, it
  no longer calls candidates below the line "weak matches on a single word", the floor's words.

## 0.9.0

okl now needs Python 3.11 or newer: 3.10 is past end of life, and no filelock or pillow
release that installs on it is free of the advisories open against it (0.8.9 stays
installable there). The relevance floor weighs a one-word match by how common the word is,
which refuses three of the six no-match prompts instead of one at no recall cost; `okl recap
--report` says how a session went; `okl seed --refresh` takes a pack's newer lessons without
the rest of the pack; the reranker's model leaves the system temp directory; and a
check-time model load stays offline after an online one in the same process.

- **okl needs Python 3.11 or newer** (#285). Python 3.10 reached end of life on 2026-10-01, and the libraries the `hybrid` and `rerank` extras pull in have moved on: no release of filelock or pillow that installs on 3.10 is free of the advisories open against it (filelock 4.1.0 has six, one high; pillow 12.3.0 has twelve, one critical), and the fixes need 3.11. On 3.10, pip keeps installing 0.8.9, the last release for it. The files okl copies into a repo still run on 3.10, since they run on that repo's Python. For contributors: CI drops its 3.10 job, adds 3.15 (released 2026-10-09), and checks that `uv.lock` matches `pyproject.toml` (it had drifted for weeks, which is where the alerts came from), and Dependabot now updates both through its `uv` ecosystem.
- **The relevance floor weighs a one-word match by how common the word is** (#277, REPORT §4v). A record that shares one word with the task in its title or symptom is briefed on that word only when at most one record in twenty carries it; a word in five or fewer records always counts, so a small store keeps the old rule; two shared words and a one-word alias admit as before. Measured by the probe at one commit against the control: no recall row moved (held-out, authored or the probe's own) and three of the six no-match prompts are now refused at a three-lesson budget, where one was ("give me a doc for that too" 11 → 2, the search prompt 12 → 6). The share is a scan of the store per check, 12 ms at 323 records. The pipeline diagrams and the README's floor sentence name the rule; `evals/common_word_grid.py` is the selection grid and `evals/probe_rephrase.py --common-share` the probe's switch.
- **`okl recap --report`: how a session went** (#279). From the local store's own logs and git, over a window (`--since` as ISO 8601 or `90m`, `6h`, `2d`; otherwise the transcript's start, otherwise a day): prompts briefed and the lessons shown most, lessons shown while stale, lessons recorded and retired with their reasons, check runs with every failure named, commits, the lessons that govern files changed in the window, and what is stale now. Markdown by default, `--format json` for scripts. It says what it does not cover yet: corrections made with `okl update`, which carry no timestamp, and anything a shared service logged. 0.4 s on this repo's store.
- **`okl seed --refresh`: pick up a pack's newer lessons without taking the rest of the pack.** A store that was seeded with the starter subset could not receive the symptoms and aliases the packs gained (REPORT §4o, §4p) except by importing whole packs, which pours a .NET or geospatial pack into a Python repo. `--refresh` re-imports only the records the store already holds, from the packs they came from, keeps their verification as every re-seed does, writes an edge only when both ends were refreshed, finds the bundled packs from the store's own seed ids when no path is given, and names the packs it was seeded from that are not bundled (a repo's own file) so they can be passed by path.
- **Two retrieval follow-ups measured, nothing changed in behaviour** (REPORT §4u). The admission rule §4t proposed for the reranker (first-stage cosine and second-stage rank together) is settled on the selection set: no line admits a lifted lesson without admitting chat filler (`evals/admission_grid.py`). The floor's two-word rule for a candidate only the semantic arm returned was pre-registered and measured: it admits the one lesson it was built for and the cutoff still drops it behind fifteen kept records, so the knob (`core.SEMANTIC_WORD_FLOOR`) ships at None, beside `core.FETCH_MULTIPLIER` and `evals/window_grid.py`, which found both neutral on the selection set. The probe gains `--semantic-words`. The next retrieval question is the order among kept records, not the floor.
- **The reranker's model is cached under the cache home, not the system temp directory.** fastembed's default cache is `$TMPDIR/fastembed_cache`, which macOS prunes on its own schedule, so a model that loaded offline one day was "not cached" the next and `okl check --rerank` fell back to the first-stage order. `okl embed` now fetches it to `$XDG_CACHE_HOME/okl/models` (`~/.cache/okl/models`), or to `FASTEMBED_CACHE_PATH` when that is set. The embedder is unaffected (model2vec reads the Hugging Face hub cache). Run `okl embed` once online after upgrading; the old copy in the temp directory is not read.
- **A check-time model load stays offline after an online one in the same process** (#290). huggingface_hub reads `HF_HUB_OFFLINE` once, at import, so in a process whose first load was online (`okl embed` fetching the reranker), later loads that set the variable still went to the network first: twelve connection attempts before the cache answered, and a test suite that stalled for minutes when the network was slow. The CLI was unaffected, since each command is its own process. okl's offline switch now sets huggingface_hub's own constant beside the variable and restores both, honouring `TRANSFORMERS_OFFLINE` as the library does.

## 0.8.9

The retrieval work since 0.8.8, each step measured and most of it shipped off: a relevance
floor before the cutoff, a symptom and aliases on every advice record, an optional semantic
arm, and three arms that stay experiments (an index of every lesson, the near misses, a
cross-encoder second stage); hygiene metrics; the measured claims re-checked against their
receipts; the short README with the essays in `docs/`.

- **A cross-encoder second stage, measured and shipped off** (#258, REPORT §4t). `okl check --rerank` runs a local ONNX cross-encoder (`Xenova/ms-marco-MiniLM-L-6-v2`, installed with the new `rerank` extra, cached once by `okl embed`) over the first 24 candidates (fused when `--hybrid` is on) on each record's title, symptom and aliases, and reorders them before the gates; `"rerank": true` in the config or `OKL_RERANK=1` turns it on for every check, the service's check request carries it, each briefed record carries its `rerank_score`, and without the extra or the model the first-stage order stands and the JSON says why. The model was chosen from five local cross-encoders, and the static embedder kept against five contextual ones, on a selection set that is not the held-out set (receipts `rerank-select-20261023.txt`, `embedder-select-20261023.txt`). Measured by the probe at one commit against one store: one more held-out paraphrase of eight and one held-out bug report fewer, one of the probe's own tickets fewer, the precision prompts' counts unchanged, about 0.5 s a check with the model loaded. The pre-registered falsifier fired, so the stage ships as an experiment flag, off. The probe gains `--rerank` and prints the median check latency; `evals/rerank_select.py`, `evals/rerank_spike.py` and `evals/embedder_select.py` are the selection scripts.
- **`okl check --near-misses`**: the records that matched the task and were left out, by the floor or the cutoff, as id and title, at most twelve lines. Off by default. The pre-flight in REPORT §4s showed it could name the governing lesson in 3 of the 10 held-out tasks the briefing misses, on tasks where the briefed arm already reproduced nothing, and that the other 7 are not in the full-text candidate window at all; so no live run, and the harness's `nearmiss` arm stays for a later instrument.
- **The index arm, as an experiment** (#258, REPORT §4r). `okl check --index` appends every other live lesson in scope as id and title with one line telling the agent to `okl show` a relevant one before writing code; the service and client carry the flag. The A/B harness gains `--arms baseline,briefed,indexed`, a `GENERATOR_TOOLS` setting that lets `claude -p` run `okl show` through a logging shim, per-sample fetch records in the receipt, and `evals/heldout_tasks.jsonl` (24 blind rephrasings as harness tasks). Measured (REPORT §4r, receipt `ab-20261023-1303`): given about 300 titles and an instruction to read a relevant one, the agent fetched the governing lesson once in 71 samples, so the arm stays an experiment and the hook gains no index; the harness pieces stay for the next variant. Pre-flight now gates the task file the run executes, and the fetch log counts only a successful `okl show`. The `doc-init-flags` rule's check is `ci/check-init-flags.py`, which also reads the guide's prose.
- **An optional semantic arm beside the full-text search, measured and not made the default** (#258, step 3). `okl embed` writes one vector per record from a local static embedding model (`minishlab/potion-retrieval-32M`, installed with the new `hybrid` extra, downloaded once); `okl check --hybrid` fuses the nearest records with the full-text candidates (`linear`, a convex combination, or `rrf`), and a candidate whose cosine reaches 0.40 passes the relevance floor by meaning; `"hybrid": "linear"` in the config or `OKL_HYBRID` turns it on for every check. At check time the model loads from the local cache only, so a hook never reaches the network, and without the extra, the model or the vectors the briefing is the full-text one and the JSON says why. Measured with no paid model call (REPORT §4q): one more held-out paraphrase of eight found, nothing on tickets or bug reports, one record more on two of six short prompts, 0.8 s per prompt for the model load; a first pass at a 0.25 line and with any semantic candidate subject to the word rules is recorded and was revised. The vector search is a numpy matrix product (3 ms at 50,000 records); the ADR carries the amendment and the next tier. New: `evals/hybrid_grid.py` and its receipt, `evals/probe_rephrase.py --hybrid`.
- **Lessons carry `aliases`: the words a developer uses when one bites** (#258, the second vectorless arm). A record may carry a "; "-separated list of phrases ("logged out on refresh; session lost"), indexed with the symptom at its weight in SQLite and Postgres (an older store rebuilds its index once on open); its words count toward the relevance floor's two shared words, and a one-word alias matched whole counts as the record's subject. `okl record --alias` (repeatable), `okl update --alias` (an empty value clears), `okl show`, the MCP tools, the service and seed packs (a JSON list) carry the field. All 136 org-scoped Rules, Defects and Gates in the seed packs gained two to eight aliases, written from each record's own content. Measured with no model (REPORT §4p): on a held-out set of 24 rephrasings written blind from the eval tasks, ticket 6→7, paraphrase 2→3, bug report 5→5 of 8; the probe's own bug-report row 3→8 and paraphrase 0→1 (sentences the author had read); the six short precision prompts unchanged on seeded stores; every governing lesson kept. A first pass in which any alias word counted as a record's subject answered a short prompt with twelve records again and was revised before shipping. New: `evals/compare_seed_briefings.py` (two seed trees, eight briefings, held-out recall and precision before and after), `evals/heldout_variants.json`, `evals/probe_prompts.json`.
- **The measured claims match every committed receipt, after an independent verification (2026-10-22).** The README and REPORT §2b put the noise floor at 21 points or more (two runs of §4m's instrument; 26 points across the §4j boundary), where both still said 17; two tasks, not three, have never reproduced unbriefed, and the rate limiter's counts are quoted from the receipts (1 of 41 unbriefed, 2 of 44 briefed), with a test that recomputes the sentence. REPORT §5 finding 7 recuts its pool to the seven runs through §4h (68 of 163 against 11 of 164, the same 42% against 7%), reports §4i's run beside it with the eight-run figure the launch posts quoted, since §4i pre-registered the layout change as a new series, and names the three smoke receipts outside the pool; the README, the anatomy sheet and the docs quote the seven-run pool; §4n says what its identity test covers. `evals/preflight.py` reads `OKL_BRIEF_INTERESTS` as the harness does, so the gate checks the briefing the run will use (receipts 1323 through 2254 ran filtered past an unfiltered gate, with react_fetch's rule absent from the arm), with a test. `docs/RELATED-WORK.md` gives ContextCov its fourth, model-judged module, states Memory Transfer Learning's trajectory finding as the paper does, and scopes its "leaves open" claims to the seven papers read (#264).
- **The A/B harness refuses a run whose working tree moved.** It records HEAD when a run starts and again when it writes the receipt; a difference marks the receipt `working_tree_moved` and not usable, with both commits named, because the briefed arm renders from the checkout and a branch switch mid-run briefs the later samples with other code (REPORT §4o).
- **Every advice record gets a symptom, and `okl seed` says when one is missing** (#258, step 2). A prompt that describes what went wrong finds a lesson through its symptom; twenty org Rules, Defects and Gates in the seed packs had none and were reachable only by a prompt that used their title's words. Each now has one, written in the words a developer would use when it bites. `okl seed` prints one line per file naming the records that lack a symptom (the same hygiene pass that warns on trace-shaped and over-scoped records), and the load-your-rules guide carries the authoring rule.
- **A relevance floor before the top-12 cutoff** (#257). The search is an OR of the task's subject words, so a short or generic prompt used to fill every slot with records sharing one word with it. A record is now briefed only when it shares two subject words with the task, or one that is in its title or symptom, or one when the task has only one word; a record below the floor stays when it links one step to a kept one. What the floor left out is counted (`weak_matches`), each briefed record names its `matched_terms` in the JSON, and both the briefing and the hook's one-line notice say when nothing matched closely. The pipeline diagram gains the stage.
- **Hygiene: stale-use and over-scope, reported and warned about** (#252, #255). The exposure log now keeps which briefed lessons the briefing marked as changed since their last check (a new `drifted_ids` column; older rows read as none), and the client logs after the drift marks rather than before. `okl metric` gains a hygiene block: stale-use (briefings that included such a lesson, over the briefings logged) and over-scope (live org lessons whose title, symptom or fix names one repository's world), each with its denominator and the lessons it flags, plus a count of trace-shaped org lessons; `--format json` carries it, and the service serves it at `/metric/hygiene`. `okl seed` prints the same two findings as warnings before importing, and `--strict` exits 2 instead, for CI on a ledger repo. One detector module (`okl.hygiene`) feeds both, so the metric and the warning cannot disagree.
- Docs: `docs/RELATED-WORK.md`, a dated page with one row per 2026 paper on memory for coding agents: what each measured, with figures read from the PDFs, and where okl stands beside it. Linked from the README's "How okl differs" section. Products stay out of it on purpose.
- **The README is a short version again, and says what okl is in its readers' terms.** It
  opens with the install line and the measured figure, puts a what-goes-wrong-and-what-catches-it
  table and a which-agent-which-part table in text (the six cards used to live only inside the
  overview image), states how okl differs in four lines, and ends with questions. The essays
  moved to `docs/` with their content intact: where this sits, verification, design choices,
  costs and knobs, what `okl init` writes, every command, subagents, seeding, the scaffold and
  the shared service. One noun throughout: a lesson. Every sentence a test or a drift rule
  pins (the corpus count, the token costs and their receipt, the reproduced-defect list, the
  install line, the init flags) is unchanged.
- **okl describes itself as verified memory for coding agents, and the loop that keeps it
  true (#235)**: the README headline, the PyPI and MCP Registry descriptions, the plugin and
  CLI descriptions, and the overview and anatomy sheets, which are re-rendered.
  `docs/overview/render_linkedin.py` is the recipe for the 4:5 feed cut of the anatomy.

## 0.8.8

No change to what okl does; this release carries the README to PyPI.

- **The README, the overview and a new anatomy sheet say what okl is for: load your
  rules, hold your agent to them, keep learning as you build (#208, #210).** The overview
  no longer claims more than the code does: a stamp with no run behind it is unproven
  rather than refused, and the briefing before every task is labelled as Claude Code's.
  The anatomy sheet follows one lesson all the way round in okl's own output.
- **A guide to loading the rules, ADRs, standards and specs a team already has (#211).**
  `docs/LOAD-YOUR-RULES.md` covers the import, proving the lessons that govern code,
  keeping them in step with their source docs, teams, and keeping docs and comments
  current, including what okl does not do yet. The README names `/seed-from-docs`.
- **The pipeline diagram traces the query `okl check` runs (#209).** It had searched the
  raw task sentence since 0.8.6 moved the briefing to the task's subject words, so its
  counts were not the briefing's. The older Excalidraw diagram is retired.
- **The pooled figure the launch posts quote is in REPORT §5, finding 7 (#208)**, with a
  test that recomputes it from its eight receipts.

## 0.8.7

- **A new repo's pushes get a note, not an error (#204).** Until a lesson governs a file,
  the drift gate has nothing to check, and the pre-push hook printed "NOTHING CHECKED" and
  "DRIFT NOT CHECKED" on every push, which read like a failure. It now says there is nothing
  to gate yet and how to start. A missing or unreadable store still gets the loud warning,
  and `okl drift --gate` and CI are unchanged. Re-run `okl init` to refresh the hook.

- **`okl init` names all six MCP tools.** It said the server offers okl_check, okl_record
  and okl_search; since 0.8.3 it also has okl_get, okl_update and okl_retire. Found by a
  fresh install of 0.8.6 from PyPI.

- **The README leads with what okl is.** Its first screen says "Guardrails and a learning
  loop for AI coding agents" and shows the one-page overview, which sat under "How it
  works", about 370 lines down.

## 0.8.6

- **A prompt with no text briefs nothing.** An image or a file sent alone reached the prompt
  hook as an empty prompt, and the hook briefed the last commit's subject instead: twelve
  lessons about unrelated work. The hook now says there is nothing to brief on, to the
  agent and the person, without asking okl (an okl before this release answers an empty
  task with every lesson). `OKL_TASK` still overrides, and a run with no prompt event at
  all keeps the last-resort task.

- **A prompt with no subject is no longer briefed (okl review R7, #178).** Every word of a
  prompt was OR-ed into the briefing's search, so "ok go", "do it" or "what about this one?"
  matched enough of a store to fill the 12-lesson cap. The briefing now searches on the
  prompt's subject words: single characters and a curated list of function words and chat
  filler are left out, each term counts once, at most 40 are used, and a prompt with no term
  of three or more characters briefs nothing. Short subject tokens such as `id`, `ci` and
  `db`, and `get`, are kept, and so is a filler word inside a dotted name, so "Next.js" still
  briefs. `okl search` is unchanged. An empty prompt also no longer falls
  through to a search that matched every lesson.
- **A precision check for the briefing (okl review R8, #179).** `evals/precision.py` scores 30
  filler prompts on a store built only from the seed packs git tracks, and fails when one
  briefs more than 3 lessons: before this change 18 did, 12 of them at the cap; now none.
  It also reports which lessons take the most slots. REPORT §4l pre-registers the A/B run
  this retrieval change needs before it ships.

- **A one-page overview at the top of "How it works".** Guardrails and a learning loop on one
  page, in light and dark, rendered from `docs/overview/okl-overview.html`; the detailed
  diagram stays below it. `ci/check-diagram-figures.sh` now reads HTML diagram sources too.

- **The README's comparison credits the neighbours that do invalidate.** It said mem0, Zep,
  Letta and Cognee let memories accumulate; Zep closes a contradicted fact on a timeline and
  mem0's model updates or deletes one. Utopia, an enterprise bitemporal knowledge graph, is
  added. What none of them does is tie a memory to your code, which is the row's point.

- **The A/B judge reads the whole submission (#182).** It read only the first 8,000
  characters, so a long submission reached it cut off mid-line: §4l lost a 15,585-character
  sample the judge called no code. It now reads up to 40,000 characters, a longer submission
  is unevaluable rather than judged on a cut copy, and each receipt records the window.
  REPORT §4m pre-registers the change of instrument.

## 0.8.5

- **The Stop question names the lessons the session touched (okl review R4, first slice).**
  It asked once, generically, whether the session learned anything, and told the agent
  how to update or retire a lesson but never which ones to look at, so lessons were added
  and almost never corrected. A new `okl recap --transcript <path>` lists up to five
  lessons the session was briefed on most often, read from the prompt hook's context in a
  Claude Code transcript, and up to five whose governed files the session changed
  (uncommitted, or committed since it began), with the command for each case: retire,
  update, re-verify, or say it was irrelevant. The agent proposes a change in one line and
  makes it once the person agrees. The Stop hook adds it to its question; with an okl too
  old to have `recap`, or a transcript it cannot read, the question is as before. It reads
  a 200 MB transcript in under a second.

## 0.8.4

- **Every run of a lesson's check is kept, pass or fail (okl review R3, first slice).** The
  stamp keeps only a lesson's last pass, so a check that failed, the run that caught a
  change, left nothing but a line on stderr, and a check that has caught regressions looked
  the same as one that never failed. `okl verify`, and `okl reverify` through it, now keeps
  each run (command, expected signal, outcome, commit) in a new `check_run` table: its own
  table, so an older okl rewriting a lesson's row cannot lose it. `okl show` prints how
  often the check passed and failed and its last failure; `okl_get` returns the latest
  runs and the counts. A shared service gets `POST /check-run`; against an older service,
  or if the write fails, verify warns that the run was not logged and its result stands.

- **Every unbriefed prompt now says so (okl review R21).** `OKL_OFFLINE=1` let a prompt
  through when okl could not run, with a line on stderr that neither the agent nor, in
  most views, the person ever saw: the agent started the task as if a check had found
  nothing. The prompt hook now hands the agent a notice that it was not briefed, with okl's
  reason and that the absence of a briefing is not a clean check, and shows the person one
  line saying the same. Without `OKL_OFFLINE`, a prompt okl cannot brief is still blocked.

- **A pinned okl that cannot start no longer blocks a prompt another okl could brief
  (#152).** A venv `okl` whose python was removed, by a Homebrew upgrade for example, still
  exists and is executable, so the hooks accepted the pin and the prompt hook blocked on its
  exit 126 even with a working okl on `PATH`. When a command fails to start within 2 s, the
  prompt hook now moves on to the next layer (`OKL_BIN`, then the pin, then `PATH`, then
  `python3 -m okl`), never running a command that already failed, and adds the one it
  passed over, with its fix, to the line you see. A command that ran and then exited 127,
  such as a `docker run` whose image lacks okl, is not run again: at three layers it could
  have taken the hook past Claude Code's 30 s limit. A working pin costs nothing extra;
  with nothing else to run, the block names the pin and says to re-run `okl init`.

- **A 200 that is not JSON is no answer, not a refusal (okl review R10).** Something other
  than okl can answer at the service's address with a web page: a proxy's sign-in page,
  or a web app on the port `OKL_SERVICE_URL` names. The client's JSON parse failed with a
  `ValueError`, which `okl check` reported as "OKL REFUSED THE CHECK" and the MCP tools as
  a refusal. It is now reported as unreachable, showing the start of what came back, and
  after a write it says MAYBE, since the service behind the page may have stored it.

- **The MCP `okl_record` tool says MAYBE RECORDED when a write may have landed.** It caught
  only `ValueError`, so a shared service that took the lesson and never answered reached
  the agent as an opaque tool error, and one that could not be reached did too.
  `okl_update` and `okl_retire` already said MAYBE. It now says the service may have
  stored the lesson, to look with `okl_search` before recording it again, and that
  recording it again with the same id is safe; a refused connection says NOT RECORDED.

- **The A/B harness no longer counts a sample with no code as a clean run (#164).** The judge
  now says whether the submission implemented the task at all. A plan, a description, a
  question or a refusal is unevaluable: a failure, kept out of both arms' denominators and
  counted toward the usability bar, with the code's length and an excerpt so the verdict
  can be audited. §4j's briefed `idor_endpoint` sample was a plan the harness scored clean.
  Receipts also record the model each alias resolved to (review item R12), and the harness
  refuses a judge that resolves to the generator's model under a different command string.
  REPORT §4k pre-registers the change of instrument.

## 0.8.3

- **Retiring a lesson is a verb, with a reason (okl review R2).** "Retracted" was the only
  way out, retracting meant re-recording (which wiped the lesson), and `okl check` never
  read SUPERSEDES, so a replaced lesson was briefed beside its replacement.
  - `okl retire <id> --reason "..."` (and the `okl_retire` MCP tool) keeps every field.
    Without a flag the lesson is wrong: status retracted, briefed as AVOID. `--by <new-id>`
    marks it superseded and writes `<new> SUPERSEDES <id>`: briefings leave it out before
    the cut, so it never takes a live lesson's slot, and print one line pointing to the
    replacement by id. `--obsolete` takes it out of briefings. A resolved defect is not
    retired and keeps briefing against its return.
  - The reason goes to a new `retirement` table rather than a column on the lesson, so an
    older okl rewriting the lesson's row cannot lose it. `okl show` and `okl_get` list a
    lesson's retirements.
  - Only `okl retire` changes a retirement: `okl update` and `okl record` refuse the retired
    statuses, and neither `okl seed` (eight bundled lessons say "live") nor `--replace`
    brings a retired lesson back.
  - A replacement must be live and visible wherever the lesson it replaces was, which also
    rules out a cycle. The pointer follows the latest replacement through a chain to a
    live one; a superseded lesson with no replacement this repo can see stays briefed.
    Retired lessons no longer use up the search's window. Retiring a lesson again with
    the same reason and replacement changes nothing once the first call has finished; a
    retry after a call that failed part-way finishes it without logging the reason twice.
  - Drift, the committed snapshot, the governs-nothing advisory and the briefing's STALE
    mark skip retired lessons, and `okl retire` on one that governs files refreshes
    `okl-drift.json` (the MCP tool cannot, so it says to run `okl export --drift`).
    Exposure metrics skip them too, and `okl dedup` recommends `okl retire --by` instead
    of a hand-written SUPERSEDES link `okl check` never read.
  - A shared service gets `POST /retire`.
  - Upgrade every okl that writes to a store before retiring lessons in it: an older
    okl's `seed` resets a retired status, and its `verify` refuses the new statuses.

- **Refining a lesson no longer wipes its proof (okl review R1).** Recording a lesson again
  with its `--id`, which the Stop hook, `/record` and the encoding-loop skill all taught as
  the way to refine one, replaced the whole row: its verification, its governed files and
  its creation date were lost, and it quietly left drift.
  - `okl update <id> --<field> ...` (and the `okl_update` MCP tool) changes only the fields
    given and keeps the rest, the proof and the first creation date included. Changing
    `--files` clears the stamp, because a check of other files proves nothing about these;
    it keeps the stored check, so `okl reverify` re-runs it, and refreshes `okl-drift.json`
    as `okl verify` does. An empty value clears an optional field, `--ttl-days ""` too.
    Updating a `seed:` lesson warns that the next `okl seed` restores the pack's text.
  - `okl record --id <existing>` is refused (exit 2), naming `okl update`; `--replace`
    (which needs `--id`) overwrites the lesson deliberately and keeps only its first
    creation date. The MCP `okl_record` tool does not offer `replace`: an agent is pointed
    at `okl_update`. `okl seed` still updates its own lessons in place, and now keeps their
    first creation date too.
  - `okl show <id>` (and `okl_get`) prints one lesson whole, with its proof.
  - Every briefed lesson carries its `[id]`, so an agent can act on a lesson it was just
    shown. That adds about 150 tokens to a full briefing on the bundled packs (~1,620 to
    ~1,770; receipts in `evals/results/`), and REPORT §4j registers it as a change of
    treatment for the A/B. Its run (2026-10-10, `ab-20261010-2314.json`) read 4/23 unbriefed against 0/23
    briefed (one briefed sample returned a plan, not code, and is not counted; #164): the ids are safe on the task set, and the unbriefed arm's own 26-point fall
    from §4i starts a new series. The layout pre-flight confirms no content was lost, and its
    summary line no longer prints a growth as "-5% smaller".
  - A shared service gets `POST /update` (a closed, typed body), `GET /node/{id}` (any id,
    `/` included; an unknown one is `{"node": null}`, so a 404 means an older service) and
    `replace` on `/record`. Its read-modify-write endpoints are serialised, since two
    concurrent updates lost a change without an error. A client recording an id against a
    service older than this refuses, instead of letting it overwrite: upgrade the service
    with the client. Every write now checks that text fields are text and `ttl_days` a
    whole number, so a wrong type is refused before it is stored. The client also closes
    every HTTP error response it catches: each holds its socket, and R1 made 400s and 404s
    routine, so the leak failed the Python 3.14 suite.
  - The Stop hook, `/record`, the skill, the README and the guide now teach `okl update`.
- **The MCP server reports okl's version (#159).** Its `initialize` reply carried an empty
  `serverInfo.version` on mcp 2.x and the SDK's own version on mcp 1.x, because okl passed
  none. It now passes the installed okl version on both, and a test reads it from a real
  `initialize` over stdio. The MCP build test also reads mcp 1.x's tool replies now, so it
  passes on both SDK majors as its docstring claims.
- **The Stop hook, the encoding-loop skill, CLAUDE.md and the README no longer say an org
  lesson reaches every repo.** By default each repo has its own store, so a lesson recorded
  with `--scope org` reaches another repo through a pack that repo loads. They now say
  that; `org` still means a lesson true in any repo.

## 0.8.2

- **A shared service that stalls, drops the connection or answers garbage now fails the
  briefing closed, in time.** The client translated a failure to connect, but not a
  service that accepted the connection and then never answered (a bare `TimeoutError`),
  hung up without replying (`ConnectionResetError`, `RemoteDisconnected`), or sent back
  something that is not HTTP or is cut off mid-reply (`BadStatusLine`, `IncompleteRead`,
  as from `OKL_SERVICE_URL` pointed at the wrong port): `okl check` died with a
  traceback and exit 1. Each try also waited 10 s, and the prompt hook tries three
  times, so a stalled service held the hook about 31 s; Claude Code cancels a
  UserPromptSubmit hook after 30 s and lets the prompt through, so the agent started
  with no briefing. All of these are now reported as unreachable (exit 2, with a reason
  naming the service and the cause), the timeout is 5 s, and the hook retries a failure
  that came back within 2 s, the store rebuild the retry exists for, but not one that
  took 3 s or more. The 5 s applies to each address a host resolves to and to each read,
  not to the whole call: a stall on one address blocks in about 5 s, and a dual-stack
  host whose firewall drops connections, which took 31.5 s even at 5 s a try, in about
  10 s. A DNS lookup that hangs is still bounded only by the resolver. A test reads the
  hook's retry rules and keeps its worst case under Claude Code's limit. **`okl record`
  and `okl verify` no longer say a write was lost when it may not have been:** these
  failures arrive after the request was sent, so the service may have stored it, and
  "NOT RECORDED" sent people to record the lesson again, as a second copy. They now say
  "MAYBE RECORDED" (search before recording again, or reuse `--id`) and that verifying
  again is safe.
- **Public claims about the A/B now match the receipts.** README, REPORT.md and a shipped
  seed comment named an IDOR, and once a React fetch, among the defects the A/B
  reproduced; those tasks never reproduced at baseline in any committed receipt. The
  defects that did are listed by name, the rate limiter's briefed-only reproductions are
  stated, spa_tokens is described as reduced (97% → 55%) rather than prevented, and the
  cross-model findings carry their single-run, cross-judge caveats. A shipped seed
  Decision quoted the quarantined 2026-07-17 figures as "Measured"; it now cites the
  committed series. Three tests hold these to the receipts.
- **`evals/layout_preflight.py` no longer counts its briefings as exposure.** It fetched one
  briefing per eval task through the normal client without `OKL_BRIEFING_LOG=0`, so each run
  wrote 8 rows of false exposure into the store `okl metric` reads. It now switches the log
  off, as the A/B harness does.

## 0.8.1

- **The Claude Code hooks run an okl whose path contains a space (#140).** Both hooks cut
  the path to okl at its first space, so an okl in a virtualenv under a project folder
  with a space in its name, or installed under a folder like `Application Support`, could
  not be run. With no other okl on `PATH`, the prompt hook then blocked every prompt,
  blaming a file that existed, and the Stop hook skipped its question without saying so.
  Both now keep the path whole, as the pre-push hook already did. A pinned
  `<python> -m okl` is used only if that python can still import okl, so a venv whose okl
  was uninstalled is skipped instead of run; with that form pinned, the check adds about
  60 ms to each prompt and each stop. **`OKL_BIN` and `okl_bin` now take only what
  `okl init` writes, as the pre-push hook already did: a path to okl, or
  `<python> -m okl`.** A launcher with arguments, such as `uv run okl`, used to be split
  into words and now is not; put it in a script and point `OKL_BIN` at that.
- **The Stop hook, `/record` and the encoding-loop skill no longer promise a gate a repo
  may not have.** They said a drift gate "goes red" when a lesson's code changes, which
  was false in a repo set up with `--no-git-hook` and no `--ci`. They now say what
  happens everywhere: the briefing and `okl drift` mark the lesson STALE until its check
  passes again, and a drift gate, where the repo has one, fails. The README and the guide
  said a lesson stays red "until someone re-runs" its check; they now say until it passes,
  since a failing re-run leaves it red, or until the code is put back as it was when it
  passed (drift compares content).

## 0.8.0

- **Drift is gated locally by default; the GitHub workflow is opt-in.** In a git repository
  `okl init` now installs the pre-push drift gate, not `.github/workflows/okl-verify.yml`.
  The workflow spends a private repo's Actions minutes and does nothing on another CI, so
  `--ci` adds it; `--no-git-hook` skips the hook, and with neither init says drift is gated
  nowhere. **Upgrading changes nothing for a repo that already has okl's workflow:** with
  no recorded choice, init keeps the workflow wherever it is installed and adds no hook.
  Both choices are recorded in `.okl/config.json`, so later runs give the same answer.
  **A repo with no okl workflow gets the hook on its next `okl init`.** Since #20 a lesson
  stamped without an observed check (a seed file's `"verified": true`, for one) is drift,
  so prove those lessons with `okl verify` first, or pass `--no-git-hook`, or the hook
  blocks the push. `--ci` installs the workflow *in place of* the hook; `--ci --git-hook`
  gives both. A hook an earlier `init` installed stays: `--no-git-hook` only stops init
  installing it, and `okl init --uninstall` removes it.
- **`okl scaffold` no longer installs okl's drift workflow.** It still stamped
  `okl-verify.yml` after the workflow became opt-in. Run in the order scaffold suggests
  (scaffold, then `okl init`), init found the workflow, recorded CI as on and installed no
  pre-push hook; run the other way round, init recorded no CI beside a workflow that then
  warned "Drift not checked" on every run. okl's drift gate is now `okl init`'s alone: the
  pre-push hook by default, the workflow with `--ci`. The method kit's own workflow,
  `method-gates.yml`, is unchanged. `okl init --ci --dry-run` also now gives the real reason
  it installs no hook (okl's workflow gates drift) instead of blaming a `--no-git-hook`
  nobody passed.
- **`okl verify` writes no `okl-drift.json` that nothing reads** (#114). Where init
  recorded no CI workflow, verify used to create the snapshot anyway, leaving an untracked
  file after every verify. It now writes none there unless a snapshot is already committed
  (another CI or a hook may gate on it), and says how to make the first one:
  `okl export --drift`, then commit it.
- **`okl init --git-hook` installs a pre-push drift gate** (#90), for a repo with no CI or
  one that would rather not spend Actions minutes on it. The hook runs `okl drift --gate`
  and blocks a push only on drift; when nothing could be checked (no store yet, no lesson
  governing a file, okl not found) it warns and lets the push through. It is installed
  where git runs hooks, so `core.hooksPath` (Husky) is honoured; a pre-push hook okl did
  not write is never replaced, even with `--force`, and init prints the line to add to it
  instead. A hooks directory outside the repo (a global `core.hooksPath`, a linked
  worktree) is refused. The choice is remembered like `--no-ci`; `okl doctor` reports the
  hook and `okl init --uninstall` removes it. A local hook is per-clone and
  `--no-verify` skips it, so on a team it complements a CI gate rather than replacing it.
- **A lesson last checked on another branch says so** (#126). One local store serves every
  branch, so a lesson verified on branch B carried B's commit when drift ran on branch A.
  If the governed files differed, drift reported it stale with dates that could
  contradict each other ("changed 10-07, after its last check on 10-08"). Now that drift
  hit, and the briefing's STALE mark, say the check ran on a commit outside this branch's
  history and name it. If the files still match, the check passed on the same content, so
  it is not drift, but its evidence depends on the other branch. `okl drift` lists those
  lessons below the report without changing the gate's exit code: content comparison is
  what lets a squash merge pass. `okl verify` and `okl export --drift`, which write the
  snapshot CI reads, warn about them, and `okl reverify` now re-checks them here.
- **A briefing no longer crashes on a lesson stamped without evidence.** Since #20, drift
  marks such a lesson in the briefing, but the mark had no verification date and the
  renderer read one (`KeyError: 'verified'`), so the briefing could not be printed. It now
  reads *UNPROVEN*, with the command that settles it.
- **`.okl/config.json` is owner-only when it holds the service token** (#98). `okl connect
  --token` stores the bearer credential there, and the file was written with default
  permissions (`-rw-r--r--` on macOS), so every local user could read it. It is now
  written to a new owner-only file (mode 0600) that replaces the old one, so even a reader
  who already had the old config open never sees the token. A config with no token keeps
  the default mode. On CI and shared machines, `OKL_TOKEN` in the environment
  is still the better place for the token.
- **A verification stamp with no observed check behind it is drift** (#20). `okl drift`
  read the store's `verified_at` alone, so a lesson stamped without evidence, such as a
  seeded record that declares `files`, cleared the gate exactly like one whose check had
  passed. The committed-snapshot path has refused that since #36; the live-store scan and
  the briefing's STALE marks now apply the same test. Such a lesson is reported as
  "stamped …, unverified", and `okl verify` with a real check clears it.
- **Re-running `okl init` keeps the repo's configured name.** It fell back to the folder's
  name, so a repo configured as `quartzose` in a folder named `Quartzose` was renamed on
  every re-run, and re-running init is how hook copies are upgraded. A rename detaches the
  repo's `repo:<name>` lessons. Now a plain re-run (and its `--dry-run`) keeps the name in
  this directory's own `.okl/config.json`; an explicit `--repo` still renames, and says
  which lessons stop briefing. A new repo nested inside another okl repo still takes its
  own folder's name.
- **okl logs which lessons each briefing showed, and `okl metric` reports it** (the first
  piece of #129). Every `okl check`, whether from the prompt hook, the CLI or MCP, appends
  the time, the repo and the ids of the lessons it showed; a shared service logs the
  briefings it answers. `okl metric` now adds how many briefings were logged and since
  when, the lessons this repo can be briefed that were never shown (oldest first, as
  candidates to review or retire), and those shown most with no stored check (candidates
  for one). Before anything is logged it says so instead of listing every lesson as
  unseen. No task or prompt text is stored. `OKL_BRIEFING_LOG=0` turns the log off; the
  eval harness sets it, so test runs do not count as exposure. A failed log write never
  costs the briefing.
- **`okl --version`** prints the installed release. A repo whose hooks run a pinned okl
  (`okl_bin` in `.okl/config.json`) had no way to ask which one it was.
- **Contributors:** the figures the docs quote are now tests (`tests/test_docs.py`). The
  corpus counts in README.md and CLAUDE.md must match `seed/`. Every briefing size in the
  README, the MCP `okl_check` description and the how-it-works diagram must match the one
  receipt the README cites, and that receipt must have measured today's corpus. Adding a
  seed lesson now fails CI until the sizes are measured again
  (`python3 evals/briefing_size.py`), which is what keeps "every bundled seed pack" true.

## 0.7.9

- **The prompt hook can send a smaller briefing, for a model with a small context window.**
  A full briefing is roughly 1,600 tokens on every prompt. Set `OKL_BRIEFING_COMPACT=1` and
  the hook sends only the action list (the new `okl check --compact`); set
  `OKL_BRIEFING_LIMIT=5` and it draws on five lessons instead of twelve. Both together come
  to about 380 tokens. A limit that is not a whole number above zero is ignored, and an okl
  too old for `--compact` briefs in full instead of blocking the prompt.
- **The briefing sizes the docs quote are measured, together, by `evals/briefing_size.py`.**
  The MCP `okl_check` description said the full briefing was ~2,300 tokens and the README
  said ~1,650; on today's 183 seed records it is ~1,620, and the action list is ~230 at
  `--limit 3` and ~810 at 12. The receipt is in `evals/results/`.
- **A withdrawn record of any type is briefed as withdrawn.** Only a retracted Claim was
  treated that way; a Decision or Rule with status `retracted` was still briefed as live
  guidance, a retracted Decision under "made on purpose; do not silently reverse". Now any
  retracted record is listed as "AVOID: … do not restate this as fact".
- **`okl verify <id>` without `--run` shows how to prove the lesson** (#115): the lesson, the
  files it covers, the tests that already mention them, and a ready-to-run, shell-quoted
  `okl verify` command. It stamps nothing and exits 2. `okl drift` and `okl reverify` say in
  plain words what to do next.
- **A Python canon: `okl seed python-canon`.** 22 lessons that translate the .NET packs'
  engineering rules to Python. Each one cites the sources that agree on it (PEPs 20, 257,
  544 and 735; the mypy, pytest and import-linter docs; Google's Python style guide; the
  Scientific Python development guide) and the okl change that adopted it. It covers the
  dependency rule as an import-linter contract, docstrings, type hints, size limits, strict
  pytest, errors, mocks, why `isinstance()` against a Protocol proves nothing about
  signatures, one composition root, value objects at seams, a contract test over every
  implementation, typing syntax by Python floor, choosing one type checker and one
  docstring format, and two dated defects. Nothing in it claims verification: verify each lesson against your own repo.
  `okl init` imports it when it creates a new, empty store in a Python repo; a repo whose
  store already holds lessons runs `okl seed python-canon`.
- **A command run where okl was never set up now refuses (exit 2) instead of writing to a
  stray `./okl.db`** (#117). `okl record` and `okl seed` used to exit 0 having saved their
  lessons where no hook, check or CI job looks, and `okl coverage` reported a clean zero.
  Every CLI command that needs a store now says so and stops, and `okl verify` refuses
  before running its check: run `okl init` first, or name a store with `OKL_DATABASE_URL`
  or `okl connect <url>`. Listing packs (`okl seed`) still works anywhere. `okl serve` still
  defaults to `./okl.db` when nothing names a store (#125).
- **A shared service answers an unknown link relation with a 400**, not a 500 the client
  reported as an outage (#119).
- **More "could not run" cases exit 2**, as the CLI's contract says: `okl seed <dir>` when the
  directory holds no packs, and `python -m okl.ownership --stamp` on a file it cannot read
  (it raised a traceback). The MCP `okl_check` tool reports a refused request (a 401, or no
  store named) as "OKL REFUSED THE CHECK" rather than a raw tool error.
- **`okl serve` and `okl mcp` without their extra exit 2** and name the install command
  (`observed-knowledge-ledger[service]` or `[mcp]`); they raised a traceback, and serve
  named a package that no longer exists.
- **The scaffolded eval runner exits 2 when it has no cases file**, as it already did for
  an empty one: nothing was measured either way.
- **okl closes its SQLite connections** (#116). Python 3.13 warns about every connection
  that is never closed, and okl opened one per command.
- **Tested on Python 3.10 to 3.14** (#116); CI had tested 3.12 alone. 3.10 reached end of
  life on 2026-10-01, and is still supported for now.
- **The shipped `okl-verify` workflow** recognises okl's own source checkout by
  `src/okl/__init__.py` instead of `src/okl/cli.py` (#120). Re-running `okl init` upgrades
  an installed copy you have not edited.
- **Contributors:** okl's own dev tools moved from the published `[dev]` extra to a PEP 735
  dependency group (#121). Install with `pip install -e . --group dev` (pip 25.1 or later)
  or `uv sync`.
- **Internals:** the CLI is now a package, `okl.cli`, with one module per command group
  (#120); `okl.cli:main` is unchanged. The MCP `okl_record` tool takes keyword arguments
  only, which is how MCP clients already call it (#118).

## 0.7.8

- **Re-seeding keeps a lesson's verification** (#110). `okl seed` replaced each row, so
  every re-seed re-stamped its lessons as verified now and wiped their evidence and
  commit. A repo that keeps its lessons in a seed file and re-seeds after an edit could
  therefore never drift, and its next drift snapshot carried stamps with no evidence. A
  re-seeded lesson now keeps its stamp, evidence and commit while its governed files are
  the same, and is cleared when they change. New lessons and `okl record` re-records
  behave as before.
- **`okl drift` names this repo's lessons whose files match nothing committed** (#109), beside the
  drift report and as `governs_nothing` in its JSON. Drift saw the deletion as the last
  change, so such a lesson watched nothing and nothing said so. Re-pointing it, dropping
  its files or retiring it is a decision, so the exit code is unchanged.
- **`okl init --no-ci`** skips the GitHub Actions workflow (#111), for a private repo that
  would pay for its minutes or one that runs another CI. The choice is recorded in
  `.okl/config.json`, so later runs keep it; `--ci` turns it back on, and `okl doctor`
  says when drift is not gated in CI.

## 0.7.7

- **The docs say what okl is not for** (#99): always-on rules and commands go in
  `CLAUDE.md` / `AGENTS.md`, procedures in a skill or runbook, style in a formatter or
  linter, open bugs in the issue tracker, secrets nowhere near the store. Everything with
  a symptom and a fix belongs in okl.
- **Drift compares the commit a check passed at, not the clock** (#102). `okl verify`
  records HEAD, and a rule has drifted when its governed files differ between that commit
  and HEAD. Comparing times missed a change committed in the same second as the check,
  since git keeps commit time to the second, and read a commit from a clock running ahead
  as a change the check never saw. A change and its revert no longer count either. The CI
  gate, `okl drift`, `okl reverify` and the briefing's STALE mark share the one verdict.
  Verifications from before this, or whose commit a clone lacks after a squash, still
  compare times. The commit is written into the evidence ahead of the time stamp, which
  binds it in `okl-drift.json` (a hand edit is refused, as an edited time already is)
  and keeps older okl versions reading the snapshot. Stores gain the column on open.
  One mixed-version limit: an older okl's `okl reverify` cannot parse the commit in this
  version's evidence when the check has an expected signal, so it lists those lessons as
  needing a first check rather than running a weaker one. Upgrade the clients that share
  a store together.
- **`okl verify` warns when the governed files have uncommitted changes**: the check saw
  them, but the record points at the commit without them, so the lesson would read as
  drifted once they are committed.
- **A STALE lesson in a briefing says what to do**: re-run its check with `okl reverify`,
  and if it fails, fix the code or change the lesson on purpose.

## 0.7.6

- **An entry for the official MCP Registry** (`server.json`, `io.github.emeraldleaf/okl`).
  Registry clients start a PyPI server as `uvx <package> <args>`, and uvx runs the command
  named after the package; okl's only command was `okl`, so that failed. The CLI now also
  installs as `observed-knowledge-ledger`, and the entry adds the MCP SDK
  (`--with mcp>=1.2`) that okl keeps in its optional `mcp` extra.
- **The PyPI page links back to the repo**, its issues, the changelog and the getting
  started guide. It had no project links.

## 0.7.5

- **Ready for the official MCP Registry.** The README carries the registry's ownership line
  (`mcp-name: io.github.emeraldleaf/okl`), which the registry checks against the PyPI
  package before it will list the server.
- **The prompt hook retries a briefly unavailable store before blocking.** Three tries over
  about a second, so a prompt that lands while a repo rebuilds its gitignored store is
  briefed instead of refused. A store that stays gone still blocks, with okl's reason; an
  okl that cannot start is not retried. The fix had lived only in one repo's edited copy
  of the hook (#91).
- **Briefings mark lessons whose code changed after their last check** (#93). A briefed
  lesson that governs files changed since its last `okl verify` is tagged *STALE*, with the
  file and dates and `okl reverify`; one that governs files but has never passed a check is
  tagged *UNVERIFIED*. The briefing's footer and the per-prompt notice count them. Only
  `okl drift` and CI said this before; the agent reading the lesson did not. Computed on
  the client, so it also works against a shared service.

## 0.7.4

- **`okl verify` / `okl reverify` treat a timeout as a failed check.** A check that
  outlived `--timeout` raised an uncaught error, so `okl reverify` stopped in a traceback
  and every later lesson went unchecked.
- **`okl_search` results lead with the lesson id**, so an agent can pass it to
  `okl_record` to update the lesson instead of adding a near-duplicate.
- `.coverage` is no longer tracked.

## 0.7.3

- **A first run that works with no choices.** `okl init` detects the stack and sets
  interests from it, and seeds an empty local store with 20 portable starter lessons plus
  the bundled packs for that stack, so the first prompt is briefed. `--no-seed` opts out.
  Starter lessons are references into the packs, so importing a full pack later updates
  the same rows.
- **You can see okl working.** Each briefed prompt shows one line, *okl · briefed N
  lesson(s): …*, via `okl check --format hook`; `OKL_QUIET=1` hides it. The hook falls back
  to the plain briefing if the installed okl predates the format.
- **Record by saying it.** The `okl_record` MCP tool takes `id` (re-recording updates the
  lesson) and `applies_to`, so any MCP agent can record what the CLI can; a new `/record`
  command drafts a lesson from the conversation and records it once you confirm. The
  getting-started guide leads with this, covers other agents, and keeps the CLI as the
  mechanism underneath.
- **Choosing how hard to enforce a lesson.** The Stop hook's question, `/record` and the
  guide now walk the same levels — briefing only, watched by CI (`--files` + `okl verify`),
  build-breaking (a test or CI check), always-on (`CLAUDE.md`/`AGENTS.md`) — and the plugin
  now ships the `encoding-loop` skill that holds the full table.
- **`okl reverify`** re-runs the stored check of every drifted lesson after listing the
  commands and getting a confirmation (or `--yes`).
- **`okl verify` creates `okl-drift.json`** the first time a lesson that governs files is
  verified, so there is no separate export step.
- **The plugin's hooks step aside in repos never set up with `okl init`**; Decisions reach
  the briefing; the service keeps `applies_to`; a getting-started guide
  (docs/GETTING-STARTED.md); a docs audit's ~74 corrections; clean example re-runs.

## 0.7.2

- **`okl record --verified` is refused.** It stamped a lesson verified with no evidence,
  while the README said live verification refused it and the shipped `encoding-loop` skill
  told agents to pass it. It now exits 2, writes nothing, and points at `okl verify`, the
  only live route to a stamp. Historical, already-verified records still import through
  `okl seed`, and CI's snapshot reader already rejected evidence-less stamps.

## 0.7.1

- **A Quickstart, and `okl init` wires Claude Code without an existing `.claude/`.**
  A fresh-install walkthrough of the README found the path spread over ~350 lines and
  one trap: `init` installed hooks only when `.claude/` already existed, which many repos
  lack, so the pre-task briefing silently never ran. `init` now also wires Claude Code
  when `claude` is on PATH, or with `--claude` (`--no-claude` opts out; okl's own plugin
  always wins, so nothing is wired twice), and `--dry-run` says which applied. The
  README gains a four-step Quickstart and "what a normal day looks like", and stops
  teaching `record --verified` (the assertion the verification section quarantines),
  seeding by file path (packs load by name), and committing a drift snapshot before any
  rule governs files (CI reads an empty one as broken, and fails).

- **The doc-orphans gate sees images** (#68). It walked `docs/*.md` only, so a diagram
  nothing linked to was invisible to it; it now checks images too and reads the committed
  tree. It found an unlinked results chart carrying unreceipted figures, now deleted,
  along with the unlinked architecture diagram (#67).
- **Docs caught up with the eval report** (#66): the diagram's figures, the README's
  top-k cutoff claim, and the Stop hook's header.

## 0.7.0

- **A dead okl path no longer turns the block into a warning** (#64). The marketplace
  E2E found the pre-task hook exiting 2 and the prompt going through anyway: the pinned
  `okl_bin` pointed into a deleted venv, bash wrote `No such file or directory` into the
  hook's stderr, and Claude Code read that phrase as "hook script missing" — a
  non-blocking configuration error. Both hooks now use a resolver layer (`OKL_BIN`, the
  pin, PATH, `python3 -m okl`) only if it can actually run, so a stale pin falls through
  instead of being executed; the block names the dead pin and never relays that phrase.
  Receipt: `evals/results/e2e-20260927-marketplace/` — install from the marketplace
  works, `okl doctor` catches the double wiring, and the A/B of old hook vs new in the
  same dead-pin repo.
- **Two worked examples, each with receipts** (#59, #62): `examples/python-fastapi/` and
  `examples/dotnet-minimal-api/` — a small orders service, three bait tasks from the eval
  set (IDOR, client-supplied price, unbounded search) and `run_demo.sh`, which plays each
  task in a control copy and a briefed copy with a real coding agent and keeps the diffs,
  final messages and the exact briefing. n=1 per arm, so illustration, not measurement:
  `price_tamper` and `rate_limiter` discriminate on both stacks (the control writes the
  defect, the briefed arm applies the recorded fix in the framework's own idiom);
  `idor_endpoint` does not, because the examples' own comments telegraph ownership.
  *Corrected 2026-10-10:* those first runs leaked each arm's role through its folder name.
  In the clean 2026-09-29 re-runs only the .NET `price_tamper` discriminates;
  `rate_limiter` is a ranking miss on both stacks and the Python `price_tamper` an
  application miss (examples/*/README.md).
  The .NET one is the stack most of the bundled lessons came from.
- **Coexistence receipt** (#60, `evals/results/e2e-20260927-coexist/`): okl's project
  hooks beside another memory plugin loaded for the session. okl's loop worked; the other
  tool captured `okl record` as a tool use (one lesson, two stores); `okl doctor` named
  it. It also corrected a shipped claim — that tool's Stop summariser ran **once** beside
  okl's blocked stop, not twice; doctor now says what was seen.
- **The test suite is deaf to a real store named in the environment** (#61). An exported
  `OKL_DATABASE_URL` leaked into two `pytest` runs and wrote 28 fixture records into the
  real store. An autouse fixture now strips `OKL_DATABASE_URL`, `OKL_SERVICE_URL` and
  `OKL_TOKEN` for every test; proven the way the incident happened (suite run with the
  variable exported, store count unchanged).

- **okl is a Claude Code plugin** (#45): `/plugin marketplace add emeraldleaf/okl` then
  `/plugin install okl@okl`. It carries the hooks, the MCP tools and the seeding commands;
  the CLI is still installed with pipx. `okl init` skips hook and MCP registration when the
  plugin is enabled, and `okl doctor` reports a repo wired both ways. The scaffold's
  `hooks/hooks.json` gained the top-level `hooks` key the plugin loader expects.
- **Fresh-install end-to-end run** (REPORT §10, receipt `evals/results/e2e-20260926/`):
  the whole loop from a wheel in a repo that had never seen okl. Every surface worked;
  two findings. In `claude -p` the Stop question's reply replaces the printed answer, so
  headless runs should set `OKL_DISABLED_HOOKS=encode` (README says so); and `okl init`'s
  pack recommendation is stack-keyed, so a Python repo is pointed at almost nothing (#54).

- **A blocked prompt says how okl failed.** The pre-task hook's block now names okl's exit
  code and what it usually means (not found, refused, error, killed by a signal) and
  whether okl's error output was captured at all. A live block read only "exited non-zero
  without a reason", and nothing recorded could explain it afterwards.

- **The briefing names each record once — 36% fewer characters across the 8 eval tasks.**
  Every record that became a routed action was printed twice: as the action, and again in
  full under its section. The action now carries the cause, a gate's symptom, what a gate
  catches and the stale marker, and the section skips it. A briefing with no routed
  actions is unchanged. A test holds the invariant (each record listed once, no field lost), and
  `evals/layout_preflight.py` proved the change lossless on all 8 eval tasks before any
  model call. This is the eval harness's treatment, so REPORT §4i pre-registers a new run.
  Eval receipts now record `okl_commit`.

- **`okl init` no longer overwrites your edits, and `okl init --uninstall` exists** (#49).
  `init` rewrote the hook scripts on every run, silently discarding a local change. Every
  file okl installs now carries a `# okl-fingerprint:` line (the hash of the rest of the
  file): an untouched okl file of any version is upgraded, an edited one is kept unless
  `--force`. `--uninstall [--dry-run]` removes okl's files and exact registrations and
  nothing else — another tool's hooks, edited files and `.okl/` stay.
- **`OKL_DISABLED_HOOKS=briefing,encode`** switches either hook off by name.
- **The Stop question lists what failed this session.** Up to five distinct failed tool
  calls, newest first, read from the transcript path Claude Code passes the hook; harness
  validation errors and permission denials are left out. They are candidates for the agent
  to judge, never records: capture stays deliberate, and nothing runs on every tool call
  or calls a model.
- **The hooks anchor to the project** (#48): run from wherever the session's directory had
  drifted, the pre-task hook blocked every prompt as "unreachable" when okl had in fact
  refused as not configured. Both hooks now `cd` to `$CLAUDE_PROJECT_DIR`, and a block
  prints okl's own reason.

## 0.6.0

**Renamed on PyPI: install `observed-knowledge-ledger`.** `org-knowledge-layer` 0.6.0 is a
final, code-free release that installs it and keeps the `okl` command working.

### Renamed: Observed Knowledge Ledger

- **The PyPI distribution is now `observed-knowledge-ledger`** (was `org-knowledge-layer`).
  The name says what is different about okl — knowledge proven by observed checks, kept
  with its evidence — where "knowledge layer" named the crowded category it is not
  competing in. `okl` itself is unchanged: the command, the import package, `.okl/`,
  `OKL_*` variables and `okl-drift.json`. The old name gets one final release (0.6.0,
  `packaging/org-knowledge-layer`) that contains no code and depends on the new one,
  extras included, so existing installs and CI steps keep working. A test holds the old
  name to an allowlist of files, so the rename cannot leave a check behind.
- **README positions okl against the Claude Code memory plugins** (#41): claude-mem,
  agentmemory, ECC and beads, from reading their source.

### Numbers that say what they rest on

- **`okl metric` states its coverage and counts recurrences it could not see** (#31). It
  printed `recurrence-after-arming: 0 … ✓` while the store held three recurrences: it only
  counted defects with a gate attached (7 of 66) without saying so, and it could not read
  the seed packs' `defect RECURS_IN <repo>` form at all. It now reports how many defect
  classes the number can speak for, lists recurrences that had no gate separately, and
  prints no tick. **`okl metric --format json` changed shape** to the report
  (`armed`, `unarmed`, `defects`, `defects_with_gate`). The service's
  `/metric/recurrence` keeps its original `recurrence_after_arming` and `count` keys, now
  derived from the same report, and adds `report`; `Client.recurrence()` keeps its v0.5
  rows the same way, beside the new `Client.recurrence_report()`. Only a `Gate` arms a
  defect now (a Rule that `CATCHES` one no longer counts as a gate). Against a service too
  old to send `report`, the CLI exits 2 and says coverage is unknown rather than guessing.
- **`okl drift --gate` no longer passes having checked nothing** (#21). An unconfigured
  directory is refused (and no `okl.db` is created by asking); a store with no rule
  governing any file reports "NOTHING CHECKED" and exits 2 under `--gate`; the all-clear
  states how many rules it checked. The shipped `okl-verify` workflow turns exit 2 into a
  "Drift not checked" warning when the job has no store, and fails when it had one.
- **`okl doctor` names memory tools that collide with okl** (#40). claude-mem,
  agentmemory, ECC and beads each hook the same events okl does: okl's Stop hook blocks
  the first stop, so their Stop hooks run twice; the capture-everything tools also record
  `okl record`, putting one lesson in two stores; and each injects context beside okl's
  briefing. `okl doctor` (exit 1 when any is found) and `okl init` name each tool found,
  where, how it collides and what to do. `okl doctor` only reads settings; `okl init`
  writes its own hook registration as before, keeping every other tool's entries.
- **CI can check drift without a store** (#36). `okl export --drift` writes
  `okl-drift.json`, the rules drift reads (ids, titles, globs, verification evidence, no
  lesson bodies); `okl drift --snapshot` reads the committed copy only, and refuses an
  entry whose `verified_at` does not match its `okl verify` evidence stamp. `okl verify`
  refreshes an existing snapshot. The shipped workflow uses it when no service is set,
  which also covers fork PRs. Seeding the rules in CI instead would have been a false
  all-clear: `record()` stamps them verified at load time. Drift's advice line no longer
  recommends `okl record --verified`.
- **`okl init` names an empty store and how to fill it** (#27), listing the bundled seed
  packs that fit the repo's declared stack. `okl seed`'s "matches your interests" marker
  now matches on stack too: a pack about .NET no longer matches a React repo because a few
  of its records are tagged `security`.

### Retrieval

- **Tags are searchable** (#14), weighted below every prose field, and content matches
  always rank ahead of records that only match on a tag.

### Fixed

- **The scaffold's recording instruction passes `--id`** (#19), so the same lesson recorded
  in two sessions is one record, not two.

## 0.5.0

### The vocabulary is no longer fixed in the package

- **A store can declare its own subject tags.** `KNOWN_TAGS` remains, but as the *floor*
  every store ships with rather than the whole vocabulary. Widen it by recording a
  `Vocabulary` node, whose title is the tag:

  ```bash
  okl record --type Vocabulary --scope org --title rust --body "Rust services."
  okl record --type Rule --scope org --tags rust --title "Prefer ? over unwrap in handlers"
  ```

  Before this, a Go, Rust or PowerShell team could not file a lesson under its own language
  without forking the package, which is a hard stop on adoption for a tool whose claim is
  that a lesson learned in one place reaches another. What the closed vocabulary was *for*
  survives: it catches the typo that files a record where nobody looks, and closed-per-store
  still does, so `rustt` is refused in a store that declared `rust`. What changes is who may
  grow it. `STACK_TAGS`, which gates `applies_to`, is deliberately not extended.

- **`frontend` and `prose` added to the floor.** Neither is specific to one org: any repo
  that renders markup has frontend lessons, and any repo that governs its writing has prose
  ones. `react` was the nearest existing tag for the first and is wrong, being a stack tag.

### Fixed

- **The hooks no longer tell you to run `pip install okl`, which cannot work.** PyPI refuses
  `okl` as confusable, so the distribution is `org-knowledge-layer` and `okl` is only the
  console script. The wrong name was in the `UserPromptSubmit` hook's not-found message,
  which fires *exactly* when someone has no working install and sent them to a 404 that
  reads as "this tool was never published." `okl init` stamps that hook into every repo it
  touches, so the error propagated with adoption. Re-run `okl init` to pick up the new file.
- `cli.py`'s MCP hint said `pip install okl[mcp]`; now `pip install 'org-knowledge-layer[mcp]'`,
  quoted because zsh globs unquoted brackets.


## 0.4.1

### Security — affects the CI workflow already in your repo

- **The shipped CI verifier no longer writes your bearer token to disk.** It ran
  `okl connect --token`, which persisted `OKL_TOKEN` into `.okl/config.json` on the runner
  for no reason: the client reads `OKL_SERVICE_URL` and `OKL_TOKEN` from the environment
  directly, so setting them at job level does the same work with the credential never
  touching the filesystem. Re-run `okl init` (or `okl scaffold`) to pick up the new file.
- **Both shipped workflows are hardened.** `okl-verify.yml` and `method-gates.yml` now
  declare least-privilege `permissions`, a concurrency group, `pipefail`, and
  `persist-credentials: false`, and pin their actions to commit SHAs rather than mutable
  tags. They satisfied none of that before.
- `.github/dependabot.yml` ships with the kit, because pinning to a SHA without an update
  path is how a repo ends up on a two-year-old action and calls it hardening.

### Added

- **Opt-in architecture review in CI.** `ci/review-agent.sh` runs the reviewer over a PR
  diff and fails on must-fix findings. **Off unless you set the `REVIEW_CMD` repository
  variable** to a CLI that reads a prompt on stdin — `claude -p` (authenticates with an
  existing Claude Code login, no separate API key), `ollama run <model>` (local, free), or
  any other. Unset, it prints one line and passes. It is the only gate in the kit that
  calls a model, which is why it is the only one that is opt-in. Documented in the README
  and the kit manifest.


## 0.4.0

### Behaviour changes worth reading before upgrading

- **Stack tags now filter exclusively.** A record naming a stack (`dotnet`, `react`,
  `geospatial`, `python`, `python-rag`) is only shown to a repo that declared that stack
  in its `interests`. Previously any shared tag let it through, so a rule tagged
  `dotnet,method` reached every repo interested in `method` — a subject 75 records carry.
  **If you declare `interests`, expect fewer records after upgrading.** That is the point,
  but it is a change in what your briefings contain. Repos that declare no interests are
  unaffected, and untagged records still always pass.
- **`symptom` and `fix` are now searchable.** They were not, which meant a record written
  the way the docs tell you to write it — short title, the distinguishing words in the
  symptom — could not be retrieved at all. Existing stores rebuild their index on first
  open; you do not need to re-record anything.

### Added

- **`okl dedup`** reports near-duplicate records for review. Lexical and explainable:
  per-field weighted Jaccard over title, symptom and fix, IDF-weighted from your own
  corpus. It never merges or drops anything — the measured score bands for true
  paraphrases and for distinct-but-related records overlap, so the call is a person's.
  The same check runs as an advisory when importing an agent-proposed pack.
- **`/seed-from-docs`** mines the specs, ADRs and rules files you already wrote into typed
  records. Built around one distinction: a record is a standing instruction that outlives
  the work item it came from, so "deep offsets use keyset pagination" belongs and "add
  pagination to /orders this sprint" does not.
- A pack declaring `_proposed_by` is refused unless every node carries a `found_by`
  citation, so the rule the seeding commands state is enforced at import rather than
  remembered by a reviewer.

### Fixed

- `Client._remote_url` validates the URL scheme once. A `service_url` from config could
  name `file://`, turning a remote read into a local file read.
- `OKLUnreachable` is now `OKLUnreachableError`, with the old name kept as an alias so
  existing `except` clauses still work.
- Drift timestamps are timezone-aware; `utcfromtimestamp` is deprecated from Python 3.12
  and returned a naive datetime that read as local time when compared across machines.

### Internal

- `_Backend` is a `typing.Protocol` whose docstring states the behavioural contract, with
  one conformance test both backends run — the defect it guards (Postgres satisfying every
  signature while running an unranked match) was invisible to signatures alone.
- mypy, and ruff widened from 6 rule families to 15 including security and complexity,
  both wired into CI alongside a secret scan, the method gates and a coverage floor.


## 0.3.1

### Security

- **Setting `OKL_TOKEN` now also removes `/openapi.json`, `/docs` and `/redoc`.** They
  were left serving 200 to anonymous callers by the 0.3.0 work that closed every data
  route, because FastAPI mounts them itself — they are not handlers, so the per-handler
  auth sweep could not reach them. They leak no records, but they publish the endpoint
  list, every schema, and which routes want a credential. With no token set the
  interactive docs remain available, since that case is a developer's laptop.

## 0.3.0

Everything here came from running three things that had been written but never
executed: the MCP server, the Postgres backend, and a deployment.

### Security

- **The service token now covers reads.** Previously `OKL_TOKEN` gated writes only, so
  an unauthenticated `GET /nodes` returned the entire store — every recorded defect,
  retired identifier and architecture decision. Every route now requires the token when
  it is set, except `/health`, which is left open for schedulers and returns no record
  content.
- **`okl connect --token` no longer commits your secret.** The token is stored in
  cleartext in `.okl/config.json`, and a comment claimed the directory was gitignored
  while nothing wrote a `.gitignore`. `okl init` and `okl connect` now write
  `.okl/.gitignore`.
- **A rejected check no longer reports success.** A 401 surfaced as `ValueError` rather
  than `OKLUnreachable`, so an unauthorized `okl check` exited 0 with a traceback — which
  a pre-task hook reads as "no rules apply". It now fails closed with exit 2, as does
  every other command, via a backstop in `main()`.

**Breaking:** if you run a service with `OKL_TOKEN` set, clients must upgrade too.
Clients older than 0.3.0 send no credential on `GET` requests and will get 401s from
`okl drift` and the recurrence metric. Upgrade the service and its clients together, or
unset `OKL_TOKEN` during the rollover.

### Fixed

- `uvicorn okl.service:app` served a module-level `None`: the process started, bound the
  port, passed a port-liveness check and returned 500 to every request. The app is now
  built lazily in a module `__getattr__`, so the standard ASGI entrypoint works while
  importing the module still does not touch the database.
- The MCP server could not start under `mcp` 2.x, which renamed `FastMCP` to
  `MCPServer` — and the error handler told you to install the extra you had just
  installed. Both names are tried, and the real import error is reported.
- Every MCP `okl_record` call with `scope="repo"` failed. The repo default used
  `setdefault`, which cannot replace an explicit `None`, and the MCP tools pass every
  field explicitly.
- MCP validation errors raised as an opaque "Error executing tool". They now return the
  complaint, so an agent that invents a tag is told the vocabulary.

### Added

- `docs/DEPLOY.md`: the shared-service deployment path, including a throwaway Postgres
  for trying it locally and what each failure mode looks like. Every command in it was
  run against a real Postgres and a real service.
- Tests covering the live MCP server, the ASGI entrypoint, service auth on reads, the
  fail-closed 401, and the config `.gitignore`.
- The Postgres/SQLite parity test now runs in a scratch schema it creates and drops. The
  first version opened with `DELETE FROM node` against whatever `OKL_TEST_POSTGRES_URL`
  pointed at, which would have destroyed the store of anyone who set it to their real
  service.

## 0.2.0 and earlier

See the git history.
