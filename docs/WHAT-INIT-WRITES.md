# Wire a repo: what `okl init` writes

Part of okl's documentation; the [README](../README.md) is the short version. Run `okl init --dry-run` first; it lists every path and writes nothing.


```bash
cd my-repo
okl init --repo my-repo        # writes .okl/config.json; wires Claude Code if .claude/ exists or `claude` is on PATH (--claude / --no-claude)
okl connect https://okl.myorg.dev   # optional: point at the shared service (else local file)
```

## What `okl init` writes to your repo

Run `okl init --dry-run` first: it lists every path and writes nothing. In full, `init`
touches only the current directory, and only these:

| Path | What it is |
|---|---|
| `.okl/config.json` | repo name, subject interests, and the path to your `okl` binary |
| `.okl/.gitignore` | keeps `.okl/` (config and store) out of git, with no edit to your own `.gitignore` |
| `.okl/okl.db` | the local store (local mode only; seeded with the starter lessons and your stack's packs unless `--no-seed`) |
| `.claude/hooks/userpromptsubmit-okl-check.sh` | **executable**; runs when you submit a task, injects the briefing |
| `.claude/hooks/stop-okl-encode.sh` | **executable**; runs at session end, asks what was learned |
| `.claude/settings.json` | registers those two hooks (merged in place; your existing keys are preserved) |
| `.mcp.json` | registers the okl MCP server — only when the `mcp` extra is installed |
| `.github/workflows/okl-verify.yml` | **a CI workflow** running the drift gate on pull requests — only with `--ci`, or where an earlier okl installed it |
| `.git/hooks/pre-push` (or your `core.hooksPath`) | **executable**; in a git repository with no okl workflow, or with `--git-hook`; runs the drift gate before a push and blocks only on drift; never written over another tool's hook |

Re-running `init` is safe: it keeps the repo name already configured here (`--repo` renames,
which stops the old `repo:<name>` lessons from briefing), upgrades okl's own files, keeps any you edited (say so
with `--force` to replace them), and merges settings without duplicating entries.

The executable ones deserve a second look before you run it: the Claude Code hooks are
shell scripts that execute automatically during agent sessions (the check hook can *block* a
task when the store is unreachable — that is the fail-closed design), and the pre-push hook
runs on every `git push` and blocks it on drift (with `--ci`, the workflow runs in your
Actions instead). All are plain text you can read first, in
[`src/okl/scaffold/hooks/`](../src/okl/scaffold/hooks/),
[`src/okl/scaffold/git-hooks/`](../src/okl/scaffold/git-hooks/) and
[`src/okl/scaffold/ci/`](../src/okl/scaffold/ci/). Nothing executes at install time; nothing
is written outside the directory you run `init` in; nothing contacts a network unless you
run `okl connect` and point it somewhere yourself.

`init` writes `.okl/config.json`. When it wires Claude Code (the repo has a `.claude/`
directory, `claude` is on PATH, or you passed `--claude`), it also installs two hooks:
a `UserPromptSubmit` hook that runs `check` on
the prompt you actually typed and puts the briefing into the model's context (the
enforced read — it must be this event: `PreToolUse` stdout never reaches the model,
which an end-to-end test caught the hard way), and a session-end hook that blocks the first stop
of a session that changed files with one question — *did this session learn anything
worth `okl record`ing?* — so the write side of the loop gets a mechanical prompt too,
not just a convention. It fires once per session and never loops.

**Other agents (AGENTS.md):** `okl scaffold` (not `init`) writes the repo canon to both
`CLAUDE.md` and `AGENTS.md` — one content, two filenames, so Codex/Cursor/anything
reading the AGENTS.md convention gets the same rules Claude Code does (byte-identity is
test-enforced). The hooks themselves are Claude Code-specific; other agents get the
canon via AGENTS.md and the store via the MCP server (`okl mcp`).

That split matters: on Claude Code the pre-task read is *enforced* (fail-closed hook);
everywhere else it is *available* (a tool call or a shell command), which is
discretionary — the thing enforcement exists to avoid. The hook scripts themselves are
plain bash reading JSON on stdin, so nothing in them is Claude-specific; what is missing
for other agents is the config that registers them, and whether the agent fires an event
early enough to matter. Codex CLI documents a `userpromptsubmit` hook, which is the right
shape; Copilot, Gemini CLI and Cursor have hook systems worth checking against your
version; OpenCode's plugin API captures tool events but, as of this writing, no
pre-prompt event — so there the read stays a tool call rather than a gate. Verify against
your agent's current docs before trusting any of that. Wiring one up is a well-shaped
contribution — see [CONTRIBUTING.md](../CONTRIBUTING.md).

Hooks run in whatever environment the agent harness spawns — often without your venv or
pipx bin dir on PATH — so both hooks resolve the `okl` binary in layers: the `OKL_BIN`
env var, then the `okl_bin` path `init` pins into `.okl/config.json` (machine-local),
then PATH, then any `python3` that can `import okl` (`python3 -m okl`). `OKL_BIN` and
`okl_bin` hold a path to okl (spaces are fine) or `<python> -m okl`; a launcher with
arguments, such as `uv run okl`, belongs in a script they point at. If a command
resolves but cannot start (a venv `okl` whose python was removed), the check hook moves
on to the next layer. If nothing runs, the check hook blocks with install
instructions (fail closed) while the encode reminder silently disables (best-effort by
design). `OKL_OFFLINE=1` lets the prompt through anyway, and says so: the agent is told
it was not briefed and why, and you see one line saying the same.
With no shared service configured it uses a local `.okl/okl.db` — single-machine
mode, good for trying it before you deploy anything.
