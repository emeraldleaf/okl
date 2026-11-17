# What okl costs, and how to turn it down

Part of okl's documentation; the [README](../README.md) is the short version. The headline numbers and the receipt are in the README's "What it costs"; this page has what `okl init` writes, every knob, how to turn parts off, and the opt-in architecture review.

**In your repo:** `okl init` writes `.okl/` (config, the local database, a `.gitignore`
covering both) and, when it wires Claude Code, three hook scripts plus their registration. In a
git repository it also installs a pre-push hook that runs the drift gate (`--no-git-hook`
skips it). `--ci` installs `.github/workflows/okl-verify.yml`, which runs the gate on every
PR, instead of the hook, and `--no-ci` leaves it out; `init` records both choices in
`.okl/config.json` (`"ci"` and `"git_hook"`), so a later run keeps them. A hook or workflow
an earlier `init` installed stays: `--no-git-hook` and `--no-ci` only stop `init` installing them, and
`okl init --uninstall` removes them.
CI has no store of its own (the local one is gitignored), so give it one: once a lesson
governs files, commit `okl-drift.json` (`okl verify` refreshes it; `okl export --drift`
writes it; a snapshot of the rules drift reads, no lesson bodies), or set the
`OKL_SERVICE_URL` secret. Without either, the step warns "Drift not checked" rather than
passing as if it had. Do not commit a snapshot holding zero rules: CI reads a configured
store that checked nothing as broken, and fails.
Not on GitHub Actions? The gate is one command; [Getting started §4](GETTING-STARTED.md#4-run-the-drift-gate-without-github-actions)
covers GitLab, Azure Pipelines and the pre-push hook.
`okl scaffold` is separate and optional — nothing installs it unless you ask.

## The knobs, cheapest first

```bash
okl check --task "..." --format actions   # imperatives only, about half the size
okl check --task "..." --format json      # the raw result, for scripts
okl check --task "..." --format hook      # what the Claude Code hook prints: the briefing plus
                                            #   the one-line notice you see (OKL_QUIET=1 drops it)
okl check --task "..." --limit 3          # fewer records; the briefing says how many it trimmed
okl check --task "..." --decision calibrated  # only what is shown in full: no one-line list
okl check --task "..." --decision floor   # every match by the word floor, in full, up to --limit
okl init --interests "python,security"    # drop records tagged for stacks you do not use
```

- **`--format actions`** is the single biggest saving and loses the least: you keep every
  "when you see X → do Y" and drop the explanatory prose.
- **`--limit N`** caps how many records are drawn on. The full briefing reports how many
  it trimmed; `--format actions` does not, so a short actions list can hide a miss
  without saying so.
- **`--decision`** is how candidates become a briefing. The default, `tiered`, shows in full
  at most five lessons that share three subject words with the task (or two rare ones) in
  their title, symptom, aliases and triggers, and names the rest of what matched in a line
  each, up to `--limit`. `calibrated` is the first tier alone, the smallest briefing; `floor`
  shows up to `--limit` that share two words, all in full. On real prompts against a real
  store, the default reached 102 of 115 applying lessons, the floor 90 and `calibrated` 38,
  at a median of 721, 1,424 and 113 tokens a prompt before the briefing's marks, which add
  about 5% ([RETRIEVAL.md](RETRIEVAL.md)). Give your
  own lessons triggers (`okl triggers`, or `/triggers` in Claude Code) so they reach the first tier.
  `"decision"` in `.okl/config.json` or `OKL_DECISION` sets it for every check.
- **`--warm on`** adds what a lesson means to the words it shares, from a model `okl warm start`
  keeps loaded in a local process (EmbeddingGemma-300m, int8; the `warm` extra; `okl warm index`
  once per store, again after lessons change). On real held-out prompts it showed 46 applying
  lessons in full against 38 and added a median of 114 ms to a prompt. It holds
  about 1.6 GB of memory from startup (it runs one inference before it serves), so by default it
  runs only for a local store whose lessons `okl warm index` has embedded, and a shared database
  uses it with `"warm": true`; `"warm": false` or `OKL_WARM=0` turns it off, and `okl warm stop`
  keeps it off until `okl warm start`, `index` or `serve`.
  It applies to a local store's calibrated and tiered checks,
  not to a shared service or `--decision floor`. When the model does not answer, the briefing is
  the usual one; `--format json` says why in `warm_unavailable`
  ([REPORT §4z](../evals/REPORT.md)).
- **The Claude Code prompt hook takes two of these from the environment**: `OKL_BRIEFING_LIMIT=N`
  becomes `--limit N`, and `OKL_BRIEFING_COMPACT=1` sends only the action list. They are
  for a model with a small context window; see
  [Small context budgets](SUBAGENTS.md).
- **`interests`** is the one to reach for on a mature shared store. Tags filter
  inclusively — an org record passes when it is untagged or shares any one tag with your
  interests, so declaring `python` keeps out a record tagged only `dotnet`, but not one
  tagged `dotnet,security` when you also declared `security`. Only a record's
  `applies_to` excludes by stack. `okl init --interests` keeps the list as `"interests"` in
  `.okl/config.json`.
- **Standing lessons** are named on every task briefing in the repo, one line each, whatever
  the task says. `okl standing add` and `remove` choose them, at most ten, and keep them as
  `"standing"` in `.okl/config.json`. A lesson the briefing already names is not repeated, and a
  file briefing gets none. `OKL_STANDING=0` leaves them out.
- **Scope records `repo:` rather than `org`** when a lesson is local. Org scope is a claim
  that every project in the organization should see it, and it costs every project's
  budget to be wrong about that.

## Turning parts off

`OKL_BRIEFING_LOG=0` stops okl logging which lessons each briefing showed, the log
`okl metric` reads to report exposure. The log keeps the time, the repo and the lesson ids,
never the task: a briefing's task is usually your prompt.

`OKL_QUIET=1` keeps the briefing but hides the one-line *okl · briefed …* notice. Switch a
hook off by name with `OKL_DISABLED_HOOKS=briefing` (the pre-task read),
`OKL_DISABLED_HOOKS=encode` (the end-of-session question), `OKL_DISABLED_HOOKS=read` (the
lessons briefed when the agent reads a file), `OKL_DISABLED_HOOKS=edit` (the lesson checks
after an edit), or several, comma-separated. The edit hook costs one read of `.okl/config.json`
an edit until you approve a check with `okl on-edit add`, which keeps each approval there under
`"on_edit"`: the lesson's id and a hash of its command and expected output. After that, it costs
the approved checks' own run time, at most 30 seconds each and 50 an edit
(`okl on-edit run --timeout` and `--budget`).
`okl on-edit add --quick` offers only the checks whose last passing run took 10 seconds or less
(`--under N` to choose another limit, above 0 and up to 30). A check never timed costs one run of
it to time, with `okl reverify --untimed`, which shows the commands and asks first. While no check
is approved, `okl on-edit` and `okl init` count the quick ones, reading each lesson's check log once,
on a local store only: about 17 ms on okl's own store, 48 ms on a made-up store of 1,000 lessons and
231 ms on one of 5,000, growing with the number of lessons that carry a check.
**Set `OKL_DISABLED_HOOKS=encode` for headless runs (`claude -p`, CI agents, scripts):**
print mode emits only the final message, and a blocked stop makes the reply to "what did
we learn?" that final message — the answer you asked for is then only in the transcript.
Hooks inherit the caller's environment, so the variable set on the `claude` command is
enough (`evals/REPORT.md` §10). The
pre-task hook is the read side and the Stop hook is the write side, and they are
independent — running the read without the write is a reasonable way to start, and turning
off `encode` is the usual choice beside a tool whose own Stop hooks already run.

Nothing is load-bearing on the hooks: `okl check` and `okl record` work from the terminal,
from CI, and through the MCP server whether or not any hook is installed.

To remove okl from a repo: `okl init --uninstall` (add `--dry-run` to preview). It removes
the three hook scripts, their exact entries in `.claude/settings.json`, okl's `.mcp.json`
server, `.github/workflows/okl-verify.yml` with the `.github/okl-version` pin beside it, and
its pre-push hook, and with `--owner` okl's CODEOWNERS block and its deny rules — and nothing
else: another tool's hooks in the same events stay, a file
you edited is kept and named, and `.okl/` (your store) is never touched; delete it yourself
if you mean to. Nothing outside the repo was ever written.

The three Claude Code hook scripts, the pre-push hook and the CI workflow each carry a
`# okl-fingerprint:` line, the hash
of the rest of the file (settings and `.mcp.json` are merged entry by entry instead). That
is how `init` and `--uninstall` tell an untouched okl file (of any fingerprinted version:
upgraded or removed freely) from one you edited. Files installed before 0.7 carry no
fingerprint, so unless one is byte-identical to the current version, `init` keeps it and
`okl init --force` is what upgrades it. `init` keeps an edited file unless you pass
`--force`; `--uninstall` always keeps it. There is no local state, so this works the
same for a teammate who cloned the repo. okl never writes through a symlink: a hook,
settings or workflow path that is a link, or sits under one, is refused and named.

## The review after writing (on by default)

The Stop hook asks the agent, before it finishes a session that changed files, to run
`okl check --change` and check the code it wrote against the lessons
([REPORT §4at](../evals/REPORT.md)); `okl init --no-review-after-writing` turns it off and
`okl init --review-after-writing` turns it back on (`init` records the choice as
`"review_after_writing"` in `.okl/config.json`), and `OKL_REVIEW_AFTER_WRITING=0` (or `1`)
decides for one session.
The cost is the list: every lesson in scope, one line each, about 270 bytes (roughly 60 tokens) a lesson, so about 80 KB
for 300 lessons, read once per session that changed something, plus the lessons the agent
then opens with `okl show`. Nothing is cut, because in id order a cut would drop lessons at
random. A list longer than about 24,000 characters comes in pages, each short enough to
arrive whole, and page 1 names the command for each further one (`okl check --change --page N
--of <fingerprint>`; a page of a review whose files or lessons changed since page 1 is refused).
Claude Code saves a command's output past about 30,000 characters by default to a file and shows
the agent 2 KB of it. In 23 of 86 measured review sessions the list came back cut that way, and
in 7 of the 49 that never handed the right lesson on, its line never reached the agent; all 7
failed (REPORT §4bk). okl calls
no model for this; the agent's own turns are the cost. Measured on
20 of this repository's changes with 280 lessons in scope (REPORT §4au), one review took a
median of about 170,000 tokens, nearly all of them cached context the session re-reads, about
$0.21 at API prices and 43 seconds. That cost, and a catch rate below the bar §4au set, kept it
off by default until 0.17.0. Since §4ay the agent checks each lesson it picks in its own fresh
sub-agent (in Claude Code on Sonnet, the model it was measured with, so its checks do not run on
a larger session model; the session itself still runs on its own), which costs more again: in that test, ten lessons asked one at a time took about
seven times the cost and six times the time of a single pass. With the agent choosing its own
lessons (REPORT §4az, receipt `review-e2e-20261111-1543.json`), a session with the review cost
$0.73 API-priced on average and a median of 214 seconds, and passed in 0.2 of its sessions (5 of 25,
on 2 of the 5 past bugs tested), against none for the earlier one-pass review: short of the bar for
turning it on. Checking the ten in turn in one session would cost a single pass, but the agent then
gave the lesson the change broke a one-line verdict (REPORT §4bg, a first look), so the review keeps a
sub-agent per lesson. It has been on by default since 0.17.0, and its gain has since been measured
on 43 graded past bugs of this repository (REPORT §4bj, receipt `review-graded-20261116-0321.json`): a session with
the review cost $0.85 API-priced on average and a median of 281 seconds, against $0.10 and 108 seconds
with none, and passed 0.267 of its sessions against 0.023, a gain of 0.244 (95% interval 0.14 to 0.36),
just under the 0.25 set in advance, with an interval that includes it. On the 31 bugs whose lesson was
written before the change the gain was 0.145. Since the gain fell under that bar, the default rests on
my judgement that a missed lesson costs more than these sessions do. Turn it off if the cost matters
more to you. The reasoning, its gap and what would reverse it are in
[the decision record](decisions/2026-11-15-review-after-writing-on-by-default.md).

### The log of what the review did

In Claude Code, the Stop hook also logs the review, so the default can be judged on real sessions: at
each stop after the first it runs `okl recap --log-review`, which reads the session's transcript and
its sub-agents' under `~/.claude/projects` and writes one row about the review to your store (ids,
paths, counts and model names; no code, command line or session text). `okl recap --reviews` reads
the rows back, with a review's tokens as the work (input, output, cache creation) and its cache reads
said apart: a call re-reads the session's whole context, so a short review shows millions of cache
reads that cost far less than the work. No model is called, and the agent is not told. The cost is time at the stop: the hook
waits for it. Timed as a full process (`evals/review_log_time.py`, receipt
`evals/results/review-log-time-20261115-0848.json`), the largest real transcript on my machine, 569 MB,
took about 0.9 seconds. The hook cuts it off at about 5 seconds, so a slower read costs a missed row,
never a held stop. Where the review after writing is off for the repo,
nothing is logged. To keep the review and drop only the log, set `OKL_REVIEW_LOG=0` for a session, or
`"review_log": false` in `.okl/config.json` for the repo (the environment wins; any other value is
refused). A directory never set up with `okl init` is never logged, even with a store URL exported.
The row goes wherever the store is: a shared database named by `OKL_DATABASE_URL` receives it, and a
shared service (`OKL_SERVICE_URL`) is refused.

## Architecture review in CI (off by default)

The kit ships a reviewer that reads a PR diff against your encoded rules and fails the
build on a must-fix finding. It is **off unless you ask for it**, and it is not tied to any
vendor. Set the `REVIEW_CMD` repository variable to any CLI that reads a prompt on stdin:

```bash
gh variable set REVIEW_CMD --body "claude -p --model sonnet"   # Claude Code CLI, installed on the runner
gh variable set REVIEW_CMD --body "ollama run qwen2.5-coder"   # local model, no API cost
gh variable set REVIEW_CMD --body "llm -m gpt-4o"              # any other CLI
```

Two things worth knowing:

- **In CI, the runner needs the CLI and a credential.** The scaffolded job does not install
  whatever `REVIEW_CMD` names, and if that command is not on the runner's PATH the step
  skips with a soft pass. Install it in the workflow and give it the secret it needs (the
  job passes `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` through when set). Your personal
  Claude Code login does not reach a hosted runner.
- **Run locally, `claude -p` needs no separate API key.** It authenticates with the Claude
  Code login you already have. Verified headless with `ANTHROPIC_API_KEY` unset.
- **Locally you do not need this at all.** The reviewer is a subagent
  (`.claude/agents/architecture-reviewer.md`); ask your agent to run it on your changes and
  it costs nothing beyond the session you are already in. The CI job exists for the case
  where no human and no agent is in the loop — a PR nobody reviewed.

Unset, the step prints one line saying it is off and exits 0. Every other gate in the kit is
deterministic and free; this is the only one that calls a model, which is why it is the only
one that is opt-in.

## The semantic arm (`--hybrid`), off by default

Measured in REPORT §4q and not made the default. Turning it on costs a 131 MB static model on
disk (`pip install 'observed-knowledge-ledger[hybrid]'`, then `okl embed` once online), about
0.8 s per prompt for the model load (the hook runs `okl check` as a new process each time; with
numpy the search takes about 4 ms at 10,000 records and 24 ms at 50,000, after reading the
vectors out of the store in 15 ms and 80 ms), and one vector
per record in the store, refreshed by `okl embed` after the records change. It buys one more
paraphrased task in eight finding its lesson on the held-out set, nothing on tickets or bug
reports, and one record more on two of six short prompts. Before it, the two free arms did
more: a `symptom` on every lesson and `aliases` in your team's words (`docs/LOAD-YOUR-RULES.md`,
items 7 and 8). It briefs a record found by meaning alone only under `--decision floor`; under
the default it can only reorder what clears the line. Past roughly 100,000 vectors the search needs an approximate index; the
retrieval ADR names that tier and its trigger.

## The second stage (`--rerank`), off by default

Measured in REPORT §4t and not made the default. It costs a 92 MB ONNX cross-encoder
(`pip install 'observed-knowledge-ledger[rerank]'`, then `okl embed` once online caches it under
`$XDG_CACHE_HOME/okl/models`, which is `~/.cache/okl/models` unless you set that variable, or
under `FASTEMBED_CACHE_PATH` when you set it; the temp directory fastembed would use by default
is pruned by the OS), about 0.5 s per check with the model loaded and 0.9 s for a process's first call (the hook runs
`okl check` as a new process each time, so each check pays the load), and nothing in the
store. It reorders the first 24 candidates by how well each record answers the task. On the
held-out set that moved one paraphrase into the briefing and one bug report out, left the
precision prompts' counts unchanged, and the pre-registered falsifier fired. The relevance
floor still decides what is briefed, on words and cosine, because the cross-encoder's scores
on records of one to three sentences do not separate a lesson from chat filler.
