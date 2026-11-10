# How okl is built

Four diagrams of the project itself. The [overview and anatomy](../README.md) sheets explain
what okl does for you; these show how it is put together, down to the files and functions.

| Diagram | Shows |
|---|---|
| [Where the code lives](#where-the-code-lives) | the repo's folders, what each file in `src/okl/` does, and what `okl init` copies into your repo |
| [What a command touches](#what-a-command-touches) | each command and hook, through the files and functions it runs, down to the store |
| [What runs when](#what-runs-when) | each hook, tool and gate, the moment it fires, and whether it can stop you |
| [A lesson's life](#a-lessons-life) | every state a lesson moves through, and the command that moves it |

All four are Excalidraw files under `docs/architecture/`, each with the `.svg` render beside it,
which is what this page shows: an image looks the same in any viewer and theme. To change one,
open its `.excalidraw` in Excalidraw (excalidraw.com, or the VS Code extension), edit it, and
export the `.svg` beside it.

They are checked, not just drawn. `ci/check-diagram-names.py` reads each source and its render
and fails CI on any command, flag, MCP tool, hook event, file, folder, function or briefing mark
they name that the code no longer has (`core.check()` must be defined in `core.py`), and on a
render whose names differ from its source. It proves the names exist, not that the picture is
right: a change of behaviour under an unchanged name is still review's to catch. okl's previous
hand-drawn architecture diagram was retired after it was found wrong in four places nothing
checked.

## Where the code lives

`src/okl/` laid out by layer, top to bottom: the command line, the adapters (MCP, HTTP, seed
packs, review), the client that picks the store, the core, the retrieval helpers, and the store.
The thick arrows are the path every command takes. Below them, `scaffold/` and where each part
lands in your repo; on the right, the rest of the repo, and which folders mirror which.

<img src="architecture/okl-code-map.svg" alt="Where the code lives. Inside src/okl, the package pip installs: cli/, the command line, one file per kind of command: parser.py (every command and its flags), lessons.py (check, record, update, retire, recap, search, show), verification.py (verify, reverify, drift, export), install.py (init, connect, scaffold), packs.py (seed), health.py (doctor, metric, coverage), servers.py (serve, mcp), review.py, intake.py (intake pr), warm.py and embed.py. Below it the adapters: mcp_server.py (the MCP tools, okl mcp), service.py (the HTTP service, whose routes call core: okl serve), seed.py (loads a seed pack's lessons) and review.py. client.py picks the store: the service over HTTP when OKL_SERVICE_URL or service_url in .okl/config.json is set, otherwise this process, on OKL_DATABASE_URL or .okl/okl.db. Then core.py (check, the briefing, plus record, update, retire, verify and search), drift.py (stale lessons and the okl-drift.json snapshot) and recap.py (what a session touched). The briefing uses decide.py, semantic.py, rerank.py and warm.py when they are on. store.py keeps the lessons, their links and every check run in SQLite or Postgres, with full-text search; hub.py is the model cache. A thick arrow runs cli to client to core to store. Outside the layers: coexist.py, ownership.py, codeowners.py, protection.py, hygiene.py, bootstrap.py, scaffold_cmd.py and intake.py. scaffold/ holds what okl init and okl scaffold copy into your repo: hooks/ to .claude/hooks/, git-hooks/pre-push to git's hooks folder, ci/okl-verify.yml to .github/workflows/, gates/, claude/ to .claude/, root/ to CLAUDE.md and AGENTS.md, profiles/ and plugin/. The rest of the repo: hooks/ and gates/, byte-identical mirrors of their scaffold copies; .github/workflows/ with ci.yml and okl-verify.yml; ci/, this repo's own checks; seed/, the starter packs; tests/; evals/ with REPORT.md and results/; docs/; examples/; .claude/ and .claude-plugin/; and at the root pyproject.toml and okl-drift.json." width="100%">

## What a command touches

One row per command or hook, left to right through `src/okl/cli/`, `client.py`, the core
modules and `store.py`, naming the function at each step, with what else it touches on the
right. Read a row to find where to start reading the code.

<img src="architecture/okl-command-paths.svg" alt="What a command touches. okl check --task, run by Claude Code's UserPromptSubmit hook: cli/lessons.py cmd_check() and _print_prompt_hook(), Client.check(), core.check() calling briefing_terms(), _live_hits() and _calibrated(), then store.search(); decide.py chooses who is briefed and semantic.py joins with --hybrid. okl check --path, run by Claude Code's PostToolUse hook: cmd_check() and _print_file_hook(), Client.check() and _check_paths(), core.check_paths() calling governing(), store.all_nodes(). okl record, update and retire: cmd_record(), cmd_update(), cmd_retire(), the Client methods of the same names, core.record(), core.update(), core.retire(), store.add_node(). okl verify: verification.py cmd_verify() and _run_check(), Client.verify(), core.verify(), store.add_node() and store.log_check(), then _refresh_snapshot() and drift.branch_snapshot() write okl-drift.json. okl drift --gate, the pre-push hook and CI: cmd_drift(), Client.all_nodes(), drift.scan_drift() and drift.off_branch(), against store.all_nodes() or in CI the committed okl-drift.json, with a git diff of each lesson's files against the commit its check passed on. okl recap, run by Claude Code's Stop hook: cmd_recap(), Client.all_nodes(), recap.recap() and recap.render(), store.all_nodes(), and git for what the session changed. okl mcp: servers.py cmd_mcp(), mcp_server.py's tools such as okl_check() and okl_record(), then the Client, core and store like the CLI. okl serve: cmd_serve(), service.py create_app() whose routes call core, then store.py; a Client with OKL_SERVICE_URL calls those routes over HTTP. okl init and okl seed: install.py cmd_init(), packs.py cmd_seed() and seed.seed_from_file(), Client.record(), core.record(), store.add_node(); init also copies src/okl/scaffold/ into your repo." width="100%">

## What runs when

Six moments, left to right: three Claude Code hooks and the MCP tools inside a session, then
the pre-push hook and CI when the work leaves your machine. Each card names the event, the
script, the command it runs and whether it can stop you. Everything reads the store except
CI, which reads the snapshot `okl verify` and `okl export --drift` write from it.

<img src="architecture/okl-runtime.svg" alt="What runs when. A timeline of six moments. You send a prompt: the Claude Code UserPromptSubmit hook runs userpromptsubmit-okl-check.sh, which runs okl check --task with --format hook and briefs the lessons that share the prompt's subject words; it fails closed, blocking the prompt with exit 2 if okl cannot run. The agent reads a file: the PostToolUse Read hook runs posttooluse-okl-read.sh, which runs okl check --path and briefs the lessons that govern that file; it never blocks. The agent calls a tool: any MCP agent reaches okl mcp through okl-mcp.sh and its tools okl_check, okl_search, okl_get, okl_record, okl_update and okl_retire; it never blocks. The session ends: the Stop hook runs stop-okl-encode.sh, which runs okl recap on the transcript and holds the first stop once if the tree changed, asking what was learned; unless okl init --no-review-after-writing turned it off, okl check --change --format hook first asks for the review after writing. You push: the git pre-push hook runs okl drift --gate; exit 1 holds the push, any other failure only warns, and --no-verify skips it. A pull request runs CI: okl-verify.yml runs okl drift --gate against the committed okl-drift.json snapshot, then the repo's gates; a failing check fails the build. Every moment but CI reads the store; okl verify and okl export --drift write the snapshot from it." width="100%">

## A lesson's life

Every state a lesson can be in, the command that moves it between them, and the mark a
briefing prints for each, so the agent knows how far to trust what it is told.

<img src="architecture/okl-lesson-states.svg" alt="A lesson's life. okl record makes a lesson UNCHECKED without --files (briefed as advice, drift has no verdict) or UNVERIFIED with --files (drift reports it never verified). okl seed lands a pack lesson the same way, or UNPROVEN when it carries a stamp with no observed run. From any of the three, okl verify with --run and --expect, when the check passes, makes it PROVEN: okl stamps the command, the commit and the time and keeps every run; okl update keeps the stamp unless --files changes. A failing check stamps nothing. When a file it governs changes after the check, it is STALE: the briefing marks it, the pre-push hook holds the push and CI fails the build. okl reverify passing, or the code going back to what passed, makes it PROVEN again; if the check fails, fix the code or change the lesson on purpose with okl update. From any state, okl retire makes it retracted by default (it was wrong, still briefed as AVOID), obsolete with --obsolete (no longer briefed) or superseded with --by (the briefing shows the replacement). Drift stops checking a retired lesson; a fixed defect is not retired, and okl update --status resolved keeps it briefed. Below, the marks as a briefing prints them: UNCHECKED, UNVERIFIED, STALE and AVOID (retracted)." width="100%">
