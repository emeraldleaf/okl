"""Detect other agent-memory tools installed beside okl, and say how they collide (#40).

Each of these tools is reasonable on its own. Installed next to okl they collide at the
hooks, and nobody is told: okl's Stop hook blocks the first stop to ask what was learned,
so every other Stop hook runs twice; tools that capture every tool call also capture
`okl record`, so one lesson lands in two stores that can disagree; and each injects its own
context beside okl's briefing with nothing reconciling them. Found by reading each tool's
source (2026-09-25); the sources are cited on issue #40.

Warn only. This module never edits another tool's configuration: what to give up is the
operator's call, and a tool that silently rewrites its neighbours is the problem it reports.

Detection reads settings files, never runs anything. A plugin is matched on its exact
plugin name (the part before `@` in `enabledPlugins`), so `ecc` cannot match `necc`; a
hand-registered hook is matched on its command, which is what actually runs.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Tool:
    name: str
    plugins: tuple[str, ...]        # exact plugin names, as in "<name>@<marketplace>"
    commands: tuple[str, ...]       # substrings of a hook command that identify it
    collides: tuple[str, ...]
    advice: str


_TWICE = ("its Stop hook runs twice per turn: okl's Stop hook blocks the first stop to ask "
          "what was learned, and the agent's reply ends in a second stop")
_BOTH_STORES = ("it records every tool call, including `okl record` and `okl verify`, so the "
                "same lesson lands in its store too, where it can drift from okl's")

KNOWN: tuple[Tool, ...] = (
    Tool("claude-mem", ("claude-mem",), ("claude-mem",),
         (_TWICE + " (a second session summary)", _BOTH_STORES,
          "it injects its own context at session start and when files are read, beside "
          "okl's per-prompt briefing"),
         "treat okl as the source of truth for rules and claude-mem as the session log; "
         "if briefings contradict, the verified okl record wins"),
    Tool("agentmemory", ("agentmemory",), ("agentmemory",),
         (_TWICE + " (a second session-end summary)", _BOTH_STORES,
          "with AGENTMEMORY_INJECT_CONTEXT=true it injects at session start and before tool "
          "use, adding to okl's briefing's token cost"),
         "keep its context injection off (its default) unless you need it; record rules in "
         "okl, where they are verified"),
    Tool("ECC", ("ecc", "everything-claude-code"), (),
         ("it registers several Stop hooks, one a format/typecheck with a 300-second timeout; "
          "each runs again on okl's second stop, delaying the what-did-we-learn turn",
          "it injects learned 'instincts' at session start; nothing reconciles them with "
          "okl's verified rules"),
         "disable the Stop hooks you do not need (ECC_DISABLED_HOOKS); where an instinct and "
         "an okl rule disagree, the rule has evidence behind it"),
    Tool("beads", ("beads",), ("bd prime",),
         ("it injects `bd prime` context at session start beside okl's briefing; small, but "
          "its instructions (e.g. 'do not create MEMORY.md') compete with okl's",
          "it uses 'gate' for a wait condition; in okl a Gate is a mechanical check"),
         "mostly complementary: beads tracks work, okl tracks lessons. Record lessons in "
         "okl, tasks in beads"),
)


@dataclass(frozen=True)
class Finding:
    tool: Tool
    where: str      # the settings file and how it was recognised


def settings_files(project_root: Path, home: Path) -> list[Path]:
    """Every settings file Claude Code merges for this project, LEAST specific first, so
    a later file overrides an earlier one. User settings live in CLAUDE_CONFIG_DIR when it
    is set; reading ~/.claude regardless gave a false all-clear to anyone who moved them."""
    user = Path(os.environ["CLAUDE_CONFIG_DIR"]) if os.environ.get("CLAUDE_CONFIG_DIR") \
        else home / ".claude"
    return [user / "settings.json",
            project_root / ".claude" / "settings.json",
            project_root / ".claude" / "settings.local.json"]


def _load(path: Path) -> dict:
    try:
        # UTF-8 explicitly: under a non-UTF-8 default encoding a valid settings file with
        # non-ASCII text failed to decode, was skipped, and its tools went unreported.
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}           # absent or unreadable: nothing to report from it
    return data if isinstance(data, dict) else {}


def _hook_commands(settings: dict) -> list[tuple[str, str]]:
    """(event, command) for every registered command hook. Malformed parts are skipped,
    never fatal: one bad value must not hide what the rest of the file says."""
    out: list[tuple[str, str]] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            entries = group.get("hooks") if isinstance(group, dict) else None
            if isinstance(entries, list):
                out.extend((event, h["command"]) for h in entries
                           if isinstance(h, dict) and isinstance(h.get("command"), str))
    return out


def detect(project_root: Path, home: Path) -> list[Finding]:
    # Plugins: resolve each key's EFFECTIVE value first, as Claude Code does -- a project
    # that switches off a plugin the user enabled has it off, and must not be told otherwise.
    plugin_state: dict[str, tuple[bool, Path]] = {}
    hook_sources: list[tuple[Path, str, str]] = []
    for path in settings_files(project_root, home):
        settings = _load(path)
        plugins = settings.get("enabledPlugins")
        if isinstance(plugins, dict):
            for key, on in plugins.items():
                plugin_state[key.split("@", 1)[0]] = (on is True, path)
        # Hooks are not overridden: every registered hook runs, so every file counts.
        hook_sources += [(path, ev, c) for ev, c in _hook_commands(settings)]

    found: list[Finding] = []
    for tool in KNOWN:
        plugin = next((p for p in tool.plugins if plugin_state.get(p, (False,))[0]), None)
        if plugin:
            found.append(Finding(tool, f"{plugin_state[plugin][1]} (plugin `{plugin}` enabled)"))
            continue
        hit = next(((p, ev, c) for p, ev, c in hook_sources
                    if any(sig in c for sig in tool.commands)), None)
        if hit:
            found.append(Finding(tool, f"{hit[0]} ({hit[1]} hook `{hit[2]}`)"))
    return found


def render(findings: list[Finding]) -> str:
    if not findings:
        return ("okl doctor: no known agent-memory tool found beside okl "
                f"(checked for {', '.join(t.name for t in KNOWN)}).")
    lines = [f"okl doctor: {len(findings)} agent-memory tool(s) installed beside okl. "
             "Nothing was changed; how they collide:"]
    for f in findings:
        lines += ["", f"  ! {f.tool.name} — found in {f.where}"]
        lines += [f"      - {c}" for c in f.tool.collides]
        lines.append(f"      → {f.tool.advice}")
    return "\n".join(lines)
