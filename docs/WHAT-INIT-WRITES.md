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
| `.claude/hooks/posttooluse-okl-read.sh` | **executable**; runs after the agent reads a file, briefs the lessons that govern it |
| `.claude/hooks/posttooluse-okl-edit.sh` | **executable**; runs after the agent edits a file, runs the lesson checks you approved for it with `okl on-edit add` (none until you approve one) |
| `.claude/settings.json` | registers those four hooks (merged in place; your existing keys are preserved) |
| `.mcp.json` | registers the okl MCP server — only when the `mcp` extra is installed |
| `.github/workflows/okl-verify.yml` | **a CI workflow** running the drift gate on pull requests — only with `--ci`, or where an earlier okl installed it |
| `.github/okl-version` | **one line, the okl release CI installs**, written beside the workflow so CI runs what your hooks run. `okl init` writes it for an okl installed from PyPI, and moves it when re-run after an upgrade, never backwards; a dev or editable okl leaves it alone. Written only where okl's workflow reads it: an edited workflow from before 0.11.0 is kept and does not, so init says so instead (`--force` replaces the workflow). Without it, CI installs the newest release. Commit it |
| `.github/CODEOWNERS` (or the CODEOWNERS file GitHub already reads) | **okl's block of owner-approved paths** — only with `--owner @you`: names you code owner of `docs/THESIS.md`, of every place GitHub reads CODEOWNERS from and of any `--owned` path, so a branch rule requiring code-owner review, which you set up, needs your approval for each change. Spliced into an existing file in its own line endings, changing no line of yours; `okl doctor` says whether GitHub enforces it ([docs/AGENT-IDENTITY.md](AGENT-IDENTITY.md)). Commit it |
| `.claude/settings.json` `permissions.deny` | **in Claude Code, with `--owner`: deny rules** for the usual ways to edit branch protection or rulesets through `gh api` (REST or GraphQL) and to merge past them (`gh pr merge --admin`, the merge API). They advise the agent; the branch rule is what enforces |
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
directory, `claude` is on PATH, or you passed `--claude`), it also installs three hooks:
a `UserPromptSubmit` hook that runs `check` on
the prompt you actually typed and puts the briefing into the model's context (the
enforced read — it must be this event: `PreToolUse` stdout never reaches the model,
which an end-to-end test caught the hard way), and a session-end hook that blocks the first stop
of a session that changed files with one question — *did this session learn anything
worth `okl record`ing?* — so the write side of the loop gets a mechanical prompt too,
not just a convention. It fires once per session and never loops. The third runs after the
agent reads a file (`PostToolUse` on `Read`): it returns `okl check --path` for that file as
`additionalContext`, which Claude Code puts next to the read's result, before any edit. Each
lesson is briefed once a session, again only while drift marks it; a file no lesson governs
gets nothing; when okl cannot answer it says so in one line. REPORT §4aj measured that the
briefing arrives (5 of 5 sessions); it did not show that it changes the edit. The fourth runs
after the agent edits a file (`PostToolUse` on `Edit`, `Write`, `MultiEdit` and `NotebookEdit`).
Until you approve a check with `okl on-edit add` it returns after one read of `.okl/config.json`,
without starting okl. Once one is approved it runs `okl on-edit run` for the file: the approved
checks of the lessons governing it, each with its own timeout, and a failure goes back to the
agent as `additionalContext`. It never blocks and never stamps a lesson verified.

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
pipx bin dir on PATH — so the hooks resolve the `okl` binary in layers: the `OKL_BIN`
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
