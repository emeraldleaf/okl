# E2E receipt — 2026-09-27 okl beside another memory plugin

Two headless sessions in a scratch repo wired with `okl init` (project hooks) and one
seeded pack, with claude-mem loaded for the session from a local checkout
(`claude --plugin-dir`, bun installed locally beside it; nothing installed globally and
nothing left in this machine's Claude settings). The scratch repo's settings also carried
the `enabledPlugins` entry a marketplace install would add, so `okl doctor` saw the same
state a real user's repo would. Budget: 2 model calls of ours (haiku smoke, sonnet task);
the plugin's own worker made 6 model calls of its own during the task session.

| what | evidence | outcome |
|---|---|---|
| both plugins' hooks run in one session | `transcript-smoke.jsonl`, `transcript-task.jsonl` | the plugin's two SessionStart hooks and okl's UserPromptSubmit hook fired; the plugin's worker started |
| does okl's blocked stop make the plugin's Stop summariser run twice? | `worker-log-excerpt.txt` | **no** — "Stop: Requesting summary" once; its Stop hook evidently honours `stop_hook_active` |
| does the plugin capture `okl record`? | `captured-tool-uses.txt` | **yes** — the `okl record …` command is one of the 3 tool uses it stored; its observer then chose to store no observation from this session |
| competing context injections | `transcript-task.jsonl` | not observable here: the plugin's injection was empty on a first session (nothing remembered yet); okl's briefing was 5,552 characters |
| `okl doctor` | `doctor.txt` | names the plugin, exit 1 |
| okl's own loop beside it | `session-task.txt`, store | briefing delivered, `okl record` landed, Stop question asked once and answered |

## What changed because of this

`okl doctor` had asserted that claude-mem's Stop hook "runs twice" beside okl. It does not;
the entry now says what was observed. The same claim for two plugins that were not tested
is now phrased as a possibility, not a fact, until they are.

## Cleanup

The plugin's worker was stopped, its data directory (created by this test) removed, and the
checkout deleted. Nothing of it remains on the machine.
