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
    """Every settings file Claude Code merges for this project, most specific first."""
    return [project_root / ".claude" / "settings.local.json",
            project_root / ".claude" / "settings.json",
            home / ".claude" / "settings.json"]


def _load(path: Path) -> dict:
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}           # absent or unreadable: nothing to report from it
    return data if isinstance(data, dict) else {}


def _enabled_plugins(settings: dict) -> set[str]:
    plugins = settings.get("enabledPlugins")
    if not isinstance(plugins, dict):
        return set()
    return {key.split("@", 1)[0] for key, on in plugins.items() if on is True}


def _hook_commands(settings: dict) -> list[tuple[str, str]]:
    """(event, command) for every registered command hook."""
    out: list[tuple[str, str]] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return out
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            entries = (group.get("hooks") or []) if isinstance(group, dict) else []
            out.extend((event, h["command"]) for h in entries
                       if isinstance(h, dict) and isinstance(h.get("command"), str))
    return out


def detect(project_root: Path, home: Path) -> list[Finding]:
    found: dict[str, Finding] = {}
    for path in settings_files(project_root, home):
        settings = _load(path)
        enabled = _enabled_plugins(settings)
        commands = _hook_commands(settings)
        for tool in KNOWN:
            if tool.name in found:
                continue
            plugin = next((p for p in tool.plugins if p in enabled), None)
            if plugin:
                found[tool.name] = Finding(tool, f"{path} (plugin `{plugin}` enabled)")
                continue
            hit = next(((ev, c) for ev, c in commands
                        if any(sig in c for sig in tool.commands)), None)
            if hit:
                found[tool.name] = Finding(tool, f"{path} ({hit[0]} hook `{hit[1]}`)")
    return [found[t.name] for t in KNOWN if t.name in found]


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
