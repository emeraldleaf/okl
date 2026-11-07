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
source and `pyproject.toml`, and `tests/test_architecture.py` fails the suite when the code
moves and they do not: run `python3 docs/render_architecture.py` to bring them back. The
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
```mermaid
flowchart LR
  cli["okl CLI<br/>27 commands"]
  mcp["okl mcp, for any MCP agent<br/>okl_check · okl_record<br/>okl_search · okl_update<br/>okl_retire · okl_get"]
  client["okl.client.Client"]
  service["okl serve (okl.service)<br/>14 HTTP routes<br/>OKL_TOKEN guards all but /health"]
  store["okl.store.Store"]
  sqlite[("SQLite<br/>.okl/okl.db by default")]
  pg[("Postgres<br/>the postgres extra")]
  cli --> client
  mcp --> client
  client -- "OKL_SERVICE_URL, or service_url in .okl/config.json" --> service
  client -- "otherwise, in this process" --> store
  service --> store
  store -- "sqlite:/// URL, or none" --> sqlite
  store -- "OKL_DATABASE_URL starting postgres" --> pg
```
<!-- /generated:storage -->

## The code's layers

Higher layers import lower ones, never the reverse, and `|` separates siblings that must not
import each other. `lint-imports` enforces it in CI. An arrow is an import; the CLI's many
imports are drawn as one arrow to each group it reaches.

<!-- generated:layers -->
Layer 1 (top), `cli`, imports from every group below, so it is left out of the chart.

```mermaid
flowchart LR
  subgraph outside["outside the layer contract"]
    bootstrap
    codeowners
    coexist
    hygiene
    ownership
    protection
    scaffold_cmd
  end
  subgraph layer1["layer 2"]
    service
    mcp_server
    seed
    review
  end
  subgraph layer2["layer 3"]
    client
  end
  subgraph layer3["layer 4"]
    recap
  end
  subgraph layer4["layer 5"]
    core
    drift
  end
  subgraph layer5["layer 6"]
    semantic
    rerank
    decide
    warm
  end
  subgraph layer6["layer 7 (bottom)"]
    store
    hub
  end
  layer1 --> layer2
  layer1 --> layer4
  layer1 --> layer5
  layer1 --> layer6
  layer1 --> outside
  layer2 --> layer4
  layer2 --> layer5
  layer2 --> layer6
  layer3 --> layer4
  layer3 --> layer6
  layer4 --> layer5
  layer4 --> layer6
  layer4 --> outside
  layer5 --> layer6
  protection --> codeowners
```
<!-- /generated:layers -->
