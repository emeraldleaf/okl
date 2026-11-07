#!/usr/bin/env python3
"""Every name a drawn diagram shows must still exist in the code.

okl retired its last hand-drawn architecture diagram (commit 93933d7) after a review found it
wrong in four places: it described behaviour the code had moved past, and nothing compared
the picture with the code. The diagrams under docs/architecture/ are drawn too, so this reads
the text of each source and of its exported render, and fails on any name the code no longer
has:

  okl <command>    a subcommand of the CLI parser
  --<flag>         a flag some CLI parser defines (or one of EXTERNAL_FLAGS)
  okl_<tool>       an MCP tool okl_mcp serves
  <Event>          a word shaped like a Claude Code hook event (UserPrompt*, Pre*/Post* in
                   PascalCase, Session*, Subagent*, Notification, Stop), registered in
                   hooks/hooks.json, so a misspelt one fails too
  <path>.sh/.yml   a tracked file: the path the diagram names, or its basename
  <MARK>           an all-caps briefing mark, present in core.py or drift.py

It also fails when a render names something its source does not, or the reverse: the .svg is
what people read, and an edited source whose render was never re-exported shows the old names.

It proves the names exist, not that the picture is right: a renamed command fails here, a
changed behaviour under an unchanged name does not. That second kind is what review is for.

Reads the repo, not the working tree (CLAUDE.md): with no arguments it checks the diagrams
and the code as committed at HEAD. Paths given on the command line are read from disk, with
the code read from disk too, which is how the tests exercise it.

Exit 0 when every name resolves, 1 when any does not, 2 when it cannot run.
"""
from __future__ import annotations

import ast
import html
import json
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

# Words that follow "okl " in prose ("okl runs it") rather than naming a command. Adding one
# is a deliberate act: a word here is never checked.
PROSE = frozenset({"runs", "stamps", "cannot", "can", "keeps", "is"})
# Flags that belong to another tool the diagrams show (git's, here), not to okl's parser.
EXTERNAL_FLAGS = frozenset({"--no-verify"})
# What each kind of name looks like in a diagram's text. Events match any word shaped like a
# Claude Code hook event rather than a fixed list, so "UserPromptSubmitted" is caught as well
# as a removed hook (CodeRabbit on #383).
PATTERNS = {
    "command": r"\bokl ([a-z][a-z-]*)",
    "flag": r"(?<![\w-])(--[a-z][a-z-]*)",
    "tool": r"\b(okl_[a-z_]+)\b",
    "event": r"\b(UserPrompt[A-Za-z]*|Pre[A-Z][A-Za-z]+|Post[A-Z][A-Za-z]+|Session[A-Z][A-Za-z]*"
             r"|Subagent[A-Z][A-Za-z]*|Notification|Stop)\b",
    "path": r"([\w./-]*[\w-]\.(?:sh|yml))\b",
    "mark": r"\b([A-Z]{5,})\b",
}


def _git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          encoding="utf-8", check=True).stdout


class Repo:
    """The code to check against: as committed at HEAD, or as on disk."""

    def __init__(self, committed: bool) -> None:
        self.committed = committed

    def read(self, rel: str) -> str:
        """One file's text."""
        if self.committed:
            return _git("show", f"HEAD:{rel}")
        return (ROOT / rel).read_text(encoding="utf-8")

    def files(self) -> list[str]:
        """Every tracked path."""
        if self.committed:
            return _git("ls-tree", "-r", "--name-only", "HEAD").split()
        return _git("ls-files").split()


def _calls(tree: ast.AST, keep: Callable[[ast.Call], bool]) -> list[ast.Call]:
    return [n for n in ast.walk(tree) if isinstance(n, ast.Call) and keep(n)]


def known_names(repo: Repo) -> dict[str, Any]:
    """What the code has, by kind."""
    parser = ast.parse(repo.read("src/okl/cli/parser.py"))
    commands = {c.args[0].value for c in _calls(parser, lambda c: (
        isinstance(c.func, ast.Attribute) and c.func.attr == "add_parser"
        and isinstance(c.func.value, ast.Name) and c.func.value.id == "sub"
        and bool(c.args) and isinstance(c.args[0], ast.Constant)))}
    flags = set(EXTERNAL_FLAGS)
    for rel in (f for f in repo.files() if f.startswith("src/okl/cli/") and f.endswith(".py")):
        for node in ast.walk(ast.parse(repo.read(rel))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and re.fullmatch(r"--[a-z][a-z-]*", node.value):
                flags.add(node.value)
    mcp = ast.parse(repo.read("src/okl/mcp_server.py"))
    tools = {n.name for n in ast.walk(mcp) if isinstance(n, ast.FunctionDef)
             and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                     and d.func.attr == "tool" for d in n.decorator_list)}
    events = set(json.loads(repo.read("hooks/hooks.json"))["hooks"])
    marks_text = repo.read("src/okl/core.py") + repo.read("src/okl/drift.py")
    return {"commands": commands, "flags": flags, "tools": tools, "events": events,
            "files": set(repo.files()), "marks_text": marks_text}


def diagram_text(raw: str) -> str:
    """The text of every live text element in an .excalidraw file."""
    data = json.loads(raw)
    return "\n".join(e.get("text", "") for e in data.get("elements", [])
                     if e.get("type") == "text" and not e.get("isDeleted"))


def render_text(raw: str) -> str:
    """The text of an exported .svg: Excalidraw writes each line as an escaped <text>."""
    return "\n".join(html.unescape(t) for t in re.findall(r"<text\b[^>]*>(.*?)</text>", raw, re.S))


def names(text: str) -> dict[str, set[str]]:
    """Every name `text` shows, by kind."""
    found = {kind: set(re.findall(pattern, text)) for kind, pattern in PATTERNS.items()}
    found["command"] -= PROSE
    return found


def _tracked(path: str, files: set[str]) -> bool:
    name = path.removeprefix("./")
    return any(f == name or f.endswith("/" + name) for f in files)


def unknown(text: str, known: dict[str, Any]) -> list[str]:
    """Each name in `text` the code does not have, described."""
    ok: dict[str, Callable[[str], bool]] = {
        "command": lambda c: c in known["commands"],
        "flag": lambda f: f in known["flags"],
        "tool": lambda t: t in known["tools"],
        "event": lambda e: e in known["events"],
        "path": lambda p: _tracked(p, known["files"]),
        "mark": lambda m: m in known["marks_text"],
    }
    say = {"command": "okl {}: no such command in src/okl/cli/parser.py",
           "flag": "{}: no CLI parser defines it",
           "tool": "{}: no such MCP tool in src/okl/mcp_server.py",
           "event": "{}: not a hook hooks/hooks.json registers",
           "path": "{}: no tracked file by that path or name",
           "mark": "{}: no such briefing mark in core.py or drift.py"}
    found = names(text)
    return [say[k].format(n) for k in PATTERNS for n in sorted(found[k]) if not ok[k](n)]


def mismatch(source: str, render: str) -> list[str]:
    """How a render's names differ from its source's, or nothing when they agree."""
    a, b = names(source), names(render)
    only_source = sorted(n for k in PATTERNS for n in a[k] - b[k])
    only_render = sorted(n for k in PATTERNS for n in b[k] - a[k])
    if not (only_source or only_render):
        return []
    parts = [f"only the .excalidraw names {', '.join(only_source)}" if only_source else "",
             f"only the .svg names {', '.join(only_render)}" if only_render else ""]
    return ["the render does not match its source (" + "; ".join(p for p in parts if p)
            + "): re-export the .svg"]


def _say(msg: str, *, err: bool = False) -> None:
    print(msg, file=sys.stderr if err else sys.stdout)


def main(argv: list[str]) -> int:
    """Check the committed diagrams, or the paths given; 0 clean, 1 unknown names, 2 cannot run."""
    committed = not argv
    repo = Repo(committed)
    try:
        if committed:
            files = set(repo.files())
            paths = [p for p in files if p.startswith("docs/") and p.endswith(".excalidraw")]
            sources = {p: repo.read(p) for p in paths}
            renders = {p: repo.read(svg) for p in paths
                       if (svg := p.removesuffix(".excalidraw") + ".svg") in files}
        else:
            sources = {p: Path(p).read_text(encoding="utf-8") for p in argv}
            renders = {p: svg.read_text(encoding="utf-8") for p in argv
                       if (svg := Path(p).with_suffix(".svg")).exists()}
        known = known_names(repo)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as e:
        _say(f"check-diagram-names: could not run: {e}", err=True)
        return 2
    if not sources:
        _say("no .excalidraw diagrams under docs/: nothing to check")
        return 0
    failed = False
    for path, raw in sorted(sources.items()):
        text = diagram_text(raw)
        problems = unknown(text, known)
        if path in renders:     # a missing render is check-diagram-pairs.sh's to report
            drawn = render_text(renders[path])
            problems += [p for p in unknown(drawn, known) if p not in problems]
            problems += mismatch(text, drawn)
        _say(f"-- {path}")
        if problems:
            failed = True
            _say("\n".join(f"   FAIL: {p}" for p in problems))
        else:
            _say("   ok: every command, flag, tool, hook, script and mark it names exists, "
                 "in the source and its render")
    if failed:
        _say("\nA drawn diagram names something the code no longer has. Fix the diagram "
             "(edit the .excalidraw, re-export the .svg), or, if a name here is prose, see "
             "PROSE and EXTERNAL_FLAGS in ci/check-diagram-names.py.", err=True)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
