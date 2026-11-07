# How okl is built

Four diagrams of the project itself. The [overview and anatomy](../README.md) sheets explain
what okl does for you; these show how it is put together.

| Diagram | Shows | Kept current by |
|---|---|---|
| [What runs when](#what-runs-when) | each hook, tool and gate, the moment it fires and the command it runs | drawn; `ci/check-diagram-names.py` fails on a name the code no longer has |
| [A lesson's life](#a-lessons-life) | every state a lesson moves through, and the command that moves it | drawn; the same check |
| [Where lessons are stored](#where-lessons-are-stored) | the ways in, the client's choice of store, the backends | generated from the code |
| [The code's layers](#the-codes-layers) | the modules, the one-way import contract, and every import | generated from the code |

The generated ones are written by [`render_architecture.py`](render_architecture.py) from the
source and `pyproject.toml`, as Mermaid source (`docs/architecture/*.mmd`) rendered to the SVG
beside it, so they look the same in any viewer and theme. `tests/test_architecture.py` fails
the suite when the code moves and they do not, a render included: run
`python3 docs/render_architecture.py --svg` to bring them back (rendering needs Playwright; see
[DEVELOPING.md](DEVELOPING.md)). The
drawn ones are Excalidraw files under `docs/architecture/`. Open the `.excalidraw` in
Excalidraw (excalidraw.com, or the VS Code extension), edit it, and export the `.svg` beside
it. `ci/check-diagram-names.py` reads each source and its render, and fails CI on any
command, flag, MCP tool, script or briefing mark they name that the code no longer has, on any
word shaped like a hook event that `hooks/hooks.json` does not register, and on a render whose
names differ from its source. It proves the names exist, not that the picture is right: a
change of behaviour under an unchanged name is still review's to catch. okl's previous
hand-drawn architecture diagram was retired after it was found wrong in four places that
nothing checked; these two are checked.

## What runs when

Six moments, left to right: three Claude Code hooks and the MCP tools inside a session, then
the pre-push hook and CI when the work leaves your machine. Each card names the event, the
script, the command it runs and whether it can stop you. Everything reads the store except
CI, which reads the snapshot `okl verify` and `okl export --drift` write from it.

<img src="architecture/okl-runtime.svg" alt="What runs when. A timeline of six moments. You send a prompt: the Claude Code UserPromptSubmit hook runs userpromptsubmit-okl-check.sh, which runs okl check --task with --format hook and briefs the lessons that share the prompt's subject words; it fails closed, blocking the prompt with exit 2 if okl cannot run. The agent reads a file: the PostToolUse Read hook runs posttooluse-okl-read.sh, which runs okl check --path and briefs the lessons that govern that file; it never blocks. The agent calls a tool: any MCP agent reaches okl mcp through okl-mcp.sh and its tools okl_check, okl_search, okl_get, okl_record, okl_update and okl_retire; it never blocks. The session ends: the Stop hook runs stop-okl-encode.sh, which runs okl recap on the transcript and holds the first stop once if the tree changed, asking what was learned. You push: the git pre-push hook runs okl drift --gate; exit 1 holds the push, any other failure only warns, and --no-verify skips it. A pull request runs CI: okl-verify.yml runs okl drift --gate against the committed okl-drift.json snapshot, then the repo's gates; a failing check fails the build. Every moment but CI reads the store; okl verify and okl export --drift write the snapshot from it." width="100%">

## A lesson's life

Every state a lesson can be in, the command that moves it between them, and the mark a
briefing prints for each, so the agent knows how far to trust what it is told.

<img src="architecture/okl-lesson-states.svg" alt="A lesson's life. okl record makes a lesson UNCHECKED without --files (briefed as advice, drift has no verdict) or UNVERIFIED with --files (drift reports it never verified). okl seed lands a pack lesson the same way, or UNPROVEN when it carries a stamp with no observed run. From any of the three, okl verify with --run and --expect, when the check passes, makes it PROVEN: okl stamps the command, the commit and the time and keeps every run; okl update keeps the stamp unless --files changes. A failing check stamps nothing. When a file it governs changes after the check, it is STALE: the briefing marks it, the pre-push hook holds the push and CI fails the build. okl reverify passing, or the code going back to what passed, makes it PROVEN again; if the check fails, fix the code or change the lesson on purpose with okl update. From any state, okl retire makes it retracted by default (it was wrong, still briefed as AVOID), obsolete with --obsolete (no longer briefed) or superseded with --by (the briefing shows the replacement). Drift stops checking a retired lesson; a fixed defect is not retired, and okl update --status resolved keeps it briefed. Below, the marks as a briefing prints them: UNCHECKED, UNVERIFIED, STALE and AVOID (retracted)." width="100%">

## Where lessons are stored

<!-- generated:storage -->
<img src="architecture/okl-storage.svg" alt="Where lessons are stored. The okl CLI (27 commands) and okl mcp, for any MCP agent (tools okl_check, okl_record, okl_search, okl_update, okl_retire, okl_get), both go through okl.client.Client. With OKL_SERVICE_URL, or service_url in .okl/config.json, the client calls okl serve (okl.service: 14 HTTP routes, OKL_TOKEN guarding all but /health), which uses okl.store.Store; otherwise the client uses the store in its own process. The store keeps lessons in SQLite (.okl/okl.db by default, or a sqlite:/// URL) or in Postgres when OKL_DATABASE_URL starts with postgres (the postgres extra)." width="100%">

Its source, generated with it: [`okl-storage.mmd`](architecture/okl-storage.mmd).
<!-- /generated:storage -->

## The code's layers

Higher layers import lower ones, never the reverse, and modules in the same layer must not
import each other. `lint-imports` enforces it in CI. An arrow between two groups means some
module in one imports some module in the other; inside a group, an arrow is one import.

<!-- generated:layers -->
Layer 1 (top), `cli`, imports from every group below, so it is left out of the chart.

<img src="architecture/okl-layers.svg" alt="The code&#x27;s layers, left to right. layer 2: mcp_server, review, seed, service; layer 3: client; layer 4: recap; layer 5: core, drift; layer 6: decide, rerank, semantic, warm; layer 7: hub, store; outside the contract: bootstrap, codeowners, coexist, hygiene, ownership, protection, scaffold_cmd. Layer 2 imports from layer 3, layer 5, layer 6, layer 7, outside the contract. Layer 3 imports from layer 5, layer 6, layer 7. Layer 4 imports from layer 5, layer 7. Layer 5 imports from layer 6, layer 7, outside the contract. Layer 6 imports from layer 7. protection imports codeowners." width="100%">

Its source, generated with it: [`okl-layers.mmd`](architecture/okl-layers.mmd).
<!-- /generated:layers -->
