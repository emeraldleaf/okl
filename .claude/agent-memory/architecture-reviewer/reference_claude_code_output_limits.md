---
name: reference-claude-code-output-limits
description: How much tool output an agent in Claude Code actually sees inline (Bash and MCP caps), for judging any okl command whose output is meant for the agent's context
metadata:
  type: reference
---

Read from the installed binary, Claude Code 2.1.302 (`~/.local/share/claude/versions/2.1.302`; search it with a
python `bytes.find`, since a `grep -o` with a long context runs for minutes on the 268 MB file):
- Bash: setting `bashOutputMaxChars`, "default 30000; values clamp to 4000-128000". Past it, "Output past this is saved to a file and Claude receives a short preview plus the path". `BASH_MAX_OUTPUT_LENGTH` alone only sizes the read-back window.
- MCP tool results: `MAX_MCP_OUTPUT_TOKENS`, default 25000 tokens (a feature flag can override it).

Seen at review of 42f2168 (2026-11-10): `okl check --change` printed 81,973 bytes (307 lessons) in this repo, so in
Claude Code the agent gets a preview and a path, while §4at's pick put every line inline in the prompt.

**How to apply:** when an okl output is meant for the agent (briefing, review menu, recap), measure its bytes on this
repo's store and compare with these caps. Re-read the binary after a Claude Code upgrade. Related: [[review-findings-log]].
