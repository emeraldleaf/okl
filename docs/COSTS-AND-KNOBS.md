# What okl costs, and how to turn it down

Part of okl's documentation; the [README](../README.md) is the short version. The headline numbers and the receipt are in the README's "What it costs"; this page has what `okl init` writes, every knob, how to turn parts off, and the opt-in architecture review.

**In your repo:** `okl init` writes `.okl/` (config, the local database, a `.gitignore`
covering both) and, when it wires Claude Code, two hook scripts plus their registration. In a
git repository it also installs a pre-push hook that runs the drift gate (`--no-git-hook`
skips it). `--ci` installs `.github/workflows/okl-verify.yml`, which runs the gate on every
PR, instead of the hook. A hook an earlier `init` installed stays: `--no-git-hook` only stops
`init` installing it, and `okl init --uninstall` removes it.
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
  at a median of 721, 1,424 and 113 tokens a prompt ([RETRIEVAL.md](RETRIEVAL.md)). Give your
  own lessons triggers (`okl triggers`, `/triggers`) so they reach the first tier.
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
- **The prompt hook takes two of these from the environment**: `OKL_BRIEFING_LIMIT=N`
  becomes `--limit N`, and `OKL_BRIEFING_COMPACT=1` sends only the action list. They are
  for a model with a small context window; see
  [Small context budgets](SUBAGENTS.md).
- **`interests`** is the one to reach for on a mature shared store. Tags filter
  inclusively — an org record passes when it is untagged or shares any one tag with your
  interests, so declaring `python` keeps out a record tagged only `dotnet`, but not one
  tagged `dotnet,security` when you also declared `security`. Only a record's
  `applies_to` excludes by stack.
- **Scope records `repo:` rather than `org`** when a lesson is local. Org scope is a claim
  that every project in the organization should see it, and it costs every project's
  budget to be wrong about that.

## Turning parts off

`OKL_BRIEFING_LOG=0` stops okl logging which lessons each briefing showed, the log
`okl metric` reads to report exposure. The log keeps the time, the repo and the lesson ids,
never the task: a briefing's task is usually your prompt.

`OKL_QUIET=1` keeps the briefing but hides the one-line *okl · briefed …* notice. Switch a
hook off by name with `OKL_DISABLED_HOOKS=briefing` (the pre-task read),
`OKL_DISABLED_HOOKS=encode` (the end-of-session question), or both, comma-separated.
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
the two hook scripts, their exact entries in `.claude/settings.json`, okl's `.mcp.json`
server, `.github/workflows/okl-verify.yml` and its pre-push hook — and nothing else: another tool's hooks in
the same events stay, a file you edited is kept and named, and `.okl/` (your store) is
never touched; delete it yourself if you mean to. Nothing outside the repo was ever written.

The two Claude Code hook scripts, the pre-push hook and the CI workflow each carry a
`# okl-fingerprint:` line, the hash
of the rest of the file (settings and `.mcp.json` are merged entry by entry instead). That
is how `init` and `--uninstall` tell an untouched okl file (of any fingerprinted version:
upgraded or removed freely) from one you edited. Files installed before 0.7 carry no
fingerprint, so unless one is byte-identical to the current version, `init` keeps it and
`okl init --force` is what upgrades it. `init` keeps an edited file unless you pass
`--force`; `--uninstall` always keeps it. There is no local state, so this works the
same for a teammate who cloned the repo. okl never writes through a symlink: a hook,
settings or workflow path that is a link, or sits under one, is refused and named.

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
numpy the search takes about 4 ms at 10,000 records and 15 ms at 50,000, after reading the
vectors out of the store in 15 ms and 92 ms), and one vector
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
