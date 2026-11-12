---
name: reference-claude-code-output-limits
description: How much tool output an agent in Claude Code actually sees inline (Bash and MCP caps), and how long a hook may run (600 s command default, 30 s UserPromptSubmit), read from the binary
metadata:
  type: reference
---

Read from the installed binary, Claude Code 2.1.302 (`~/.local/share/claude/versions/2.1.302`; search it with a
python `bytes.find`, since a `grep -o` with a long context runs for minutes on the 268 MB file):
- Bash: setting `bashOutputMaxChars`, "default 30000; values clamp to 4000-128000". Past it, "Output past this is saved to a file and Claude receives a short preview plus the path". `BASH_MAX_OUTPUT_LENGTH` alone only sizes the read-back window.
- MCP tool results: `MAX_MCP_OUTPUT_TOKENS`, default 25000 tokens (a feature flag can override it).
- Hook timeouts (read 2026-11-12, #441): `var fu=600000,dXe=30000,...` beside the PreToolUse/PostToolUse set. Command hooks
  default to 600 s (`e.timeout?e.timeout*1000:fu`), and the PostToolUse runner `HHn(...,w=fu)` is called with `void 0`, so
  PostToolUse gets 600 s. UserPromptSubmit passes `timeoutMs:dXe`, 30 s. A hook entry's own `timeout` (seconds) overrides.
  Locate it with a python regex like `var fu=600000` or `hook_event_name:"PostToolUse"`. Minified names change per version.

Seen at review of 42f2168 (2026-11-10): `okl check --change` printed 81,973 bytes (307 lessons) in this repo, so in
Claude Code the agent gets a preview and a path, while §4at's pick put every line inline in the prompt.

**How to apply:** when an okl output is meant for the agent (briefing, review menu, recap), measure its bytes on this
repo's store and compare with these caps. Re-read the binary after a Claude Code upgrade. Related: [[review-findings-log]].
