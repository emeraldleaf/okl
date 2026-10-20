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
Not on GitHub Actions? The gate is one command; [Getting started §4](docs/GETTING-STARTED.md#4-run-the-drift-gate-without-github-actions)
covers GitLab, Azure Pipelines and the pre-push hook.
`okl scaffold` is separate and optional — nothing installs it unless you ask.

## The knobs, cheapest first

```bash
okl check --task "..." --format actions   # imperatives only, about half the size
okl check --task "..." --format json      # the raw result, for scripts
okl check --task "..." --format hook      # what the Claude Code hook prints: the briefing plus
                                            #   the one-line notice you see (OKL_QUIET=1 drops it)
okl check --task "..." --limit 3          # fewer records; the briefing says how many it trimmed
okl init --interests "python,security"    # drop records tagged for stacks you do not use
```

- **`--format actions`** is the single biggest saving and loses the least: you keep every
  "when you see X → do Y" and drop the explanatory prose.
- **`--limit N`** caps how many records are drawn on. The full briefing reports how many
  it trimmed; `--format actions` does not, so a short actions list can hide a miss
  without saying so.
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
