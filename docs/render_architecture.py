#!/usr/bin/env python3
"""Write the generated diagrams in docs/ARCHITECTURE.md from the code, never from memory.

Two of the four architecture diagrams are facts the code already holds, so they are read
from it: the package layers from the import contract in pyproject.toml plus every import
under src/okl, and where lessons are stored from the CLI's commands, the MCP tools, the
service's routes and the store's backends. Each is a Mermaid block between markers in
docs/ARCHITECTURE.md, which GitHub renders in place. The other two are drawn by hand in
Excalidraw (docs/architecture/*.excalidraw) and held by ci/check-diagram-names.py.

okl retired its last hand-drawn architecture diagram after it was found wrong in four places
(commit 93933d7): nothing watched it. tests/test_architecture.py runs this with --check, so a
change to the code that moves either diagram fails the suite until it is re-run.

Standard library only: it parses the source with ast and never imports okl, so it runs on
any checkout without the package or its extras installed.

Usage:
    python3 docs/render_architecture.py           # rewrite the generated blocks
    python3 docs/render_architecture.py --check   # exit 1 if they are out of date
"""
from __future__ import annotations

import argparse
import ast
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "okl"
DOC = ROOT / "docs" / "ARCHITECTURE.md"

# A Mermaid chart is drawn on the page's own background, transparent, so on a dark theme the
# default near-black arrows vanished (reported in a dark VS Code preview). Every box gets a
# light fill with dark text, and the arrows a mid teal that reads on black and on white, so
# the chart looks the same on either. okl's colours, from docs/overview/okl-anatomy.html.
THEME = ('%%{init: {"theme": "base", "themeVariables": {'
         '"primaryColor": "#e8f0f0", "primaryTextColor": "#1a4d4a", "primaryBorderColor": "#1a4d4a", '
         '"lineColor": "#3d9b96", "clusterBkg": "#f8f6f3", "clusterBorder": "#8a6a3f", '
         '"titleColor": "#1a4d4a", "edgeLabelBackground": "#ffffff", "textColor": "#1a4d4a"}}}%%')
# Mermaid's default arrow is a hairline; at 2px it holds up on a dark page as well as a light one.
ARROWS = "  linkStyle default stroke-width:2px"


# --- the package layers ------------------------------------------------------------------

def _modules() -> dict[str, list[Path]]:
    """okl's modules by name: each top-level .py file, and the cli package as one."""
    mods: dict[str, list[Path]] = {}
    for p in sorted(PKG.glob("*.py")):
        if p.stem not in ("__init__", "__main__"):
            mods[p.stem] = [p]
    mods["cli"] = sorted((PKG / "cli").glob("*.py"))
    return mods


def _imports(path: Path, names: set[str]) -> set[str]:
    """The okl modules one file imports, by module name. `from . import x`, `from .x import y`,
    `from .. import x` (inside cli) and `okl.x` all count; an import inside cli of its own
    siblings does not, as cli is drawn as one module."""
    depth = len(path.relative_to(PKG).parts) - 1        # 0 for okl/x.py, 1 for okl/cli/x.py
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.ImportFrom):
            found.update(_from_targets(node, depth))
        elif isinstance(node, ast.Import):
            found.update(a.name.split(".")[1] for a in node.names if a.name.startswith("okl."))
    return found & names


def _from_targets(node: ast.ImportFrom, depth: int) -> list[str]:
    """The okl modules one `from ... import` names, or none."""
    names = [a.name for a in node.names]
    if node.level:
        if node.level - 1 != depth:                     # within the cli package itself
            return []
        return [node.module.split(".")[0]] if node.module else names
    parts = (node.module or "").split(".")
    if parts[0] != "okl":
        return []
    return parts[1:2] or names


def _layers() -> list[list[str]]:
    """The layer contract, top first, each a list of sibling module names."""
    cfg = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    for contract in cfg["tool"]["importlinter"]["contracts"]:
        if contract.get("type") == "layers" and "okl.cli" in contract["layers"]:
            return [[m.strip().removeprefix("okl.") for m in layer.split("|")]
                    for layer in contract["layers"]]
    raise SystemExit("no layers contract naming okl.cli in pyproject.toml")


def layers_diagram() -> str:
    """The layers block: each layer of the import contract as a group, with the imports."""
    mods = _modules()
    names = set(mods)
    edges = {(m, t) for m, files in mods.items() for f in files for t in _imports(f, names) if t != m}
    layers = _layers()
    layered = {m for layer in layers for m in layer}
    missing = layered - names
    if missing:
        raise SystemExit(f"the layer contract names modules that do not exist: {sorted(missing)}")
    outside = sorted(names - layered)
    group = {m: f"layer{i}" for i, layer in enumerate(layers) for m in layer}
    group.update(dict.fromkeys(outside, "outside"))

    # Left to right, so each layer is a column of its modules: top to bottom stacked them in
    # boxes too narrow for their titles. Mermaid ignores a group's own direction once arrows
    # leave it, so the whole chart's direction is what lays them out.
    order = [f"layer{i}" for i in range(len(layers))] + ["outside"]
    between = {(group[m], group[t]) for (m, t) in edges if group[m] != group[t]}
    # The CLI imports from nearly every group, and seven arrows saying so buried the rest.
    # When it reaches every one, a sentence above the chart says so and it is left out; if it
    # ever stops reaching one, it is drawn again with its arrows.
    cli_reaches_all = {b for a, b in between if a == "layer0"} == set(order[1:])
    if cli_reaches_all:
        between = {e for e in between if e[0] != "layer0"}
    top = layers[0][0]
    lines = [THEME, "flowchart LR"]
    lines.append('  subgraph outside["outside the layer contract"]')
    lines.extend(f"    {m}" for m in outside)
    lines.append("  end")
    last = len(layers)
    for i, layer in enumerate(layers):
        if i == 0 and cli_reaches_all:
            continue                                    # said in words above the chart
        where = " (top)" if i == 0 else " (bottom)" if i == last - 1 else ""
        lines.append(f'  subgraph layer{i}["layer {i + 1}{where}"]')
        lines.extend(f"    {m}" for m in layer)
        lines.append("  end")
    # Between groups, one arrow per pair: something in one imports something in the other,
    # which is what the contract rules on. Forty module-to-module arrows, most of them into
    # the store, drew a tangle nobody could read. Inside a group, module to module.
    lines.extend(f"  {a} --> {b}" for a, b in sorted(between, key=lambda e: (order.index(e[0]), order.index(e[1]))))
    lines.extend(f"  {m} --> {t}" for (m, t) in sorted(edges) if group[m] == group[t])
    lines.append(ARROWS)
    lead = (f"Layer 1 (top), `{top}`, imports from every group below, so it is left out of the "
            "chart.\n\n" if cli_reaches_all else "")
    return f"{lead}```mermaid\n" + "\n".join(lines) + "\n```"


# --- where lessons are stored -------------------------------------------------------------

def _source(rel: str) -> str:
    return (PKG / rel).read_text(encoding="utf-8")


def _cli_commands() -> list[str]:
    tree = ast.parse(_source("cli/parser.py"))
    return [n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add_parser" and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "sub" and n.args and isinstance(n.args[0], ast.Constant)]


def _mcp_tools() -> list[str]:
    tree = ast.parse(_source("mcp_server.py"))
    return [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
            and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr == "tool" for d in n.decorator_list)]


def _routes() -> list[str]:
    tree = ast.parse(_source("service.py"))
    out = []
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef):
            for d in n.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and d.func.attr in ("get", "post", "put", "patch", "delete")
                        and d.args and isinstance(d.args[0], ast.Constant)):
                    path = re.sub(r"\{(\w+):\w+\}", r"{\1}", d.args[0].value)   # {id:path} -> {id}
                    out.append(f"{d.func.attr.upper()} {path}")
    return out


def _backends() -> list[str]:
    tree = ast.parse(_source("store.py"))
    return [n.name.strip("_").removesuffix("Backend") for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and n.name != "_Backend"
            and any(isinstance(b, ast.Name) and b.id == "_Backend" for b in n.bases)]


def _require(rel: str, *needles: str) -> None:
    """Fail when a fact the diagram states in words is no longer in the code."""
    text = _source(rel)
    gone = [s for s in needles if s not in text]
    if gone:
        raise SystemExit(f"{rel} no longer contains {gone}: the storage diagram states it")


def storage_diagram() -> str:
    """The storage block: the ways in, the client's choice, the service and the backends."""
    _require("client.py", 'os.environ.get("OKL_SERVICE_URL")', '"service_url"', "OKL_DATABASE_URL", "okl.db")
    _require("store.py", 'url.startswith("postgres")', "sqlite:///")
    backends = _backends()
    if sorted(backends) != ["Postgres", "SQLite"]:
        raise SystemExit(f"the store's backends are now {backends}: redraw the storage diagram")
    _require("service.py", 'os.environ.get("OKL_TOKEN")')
    cmds, tools, routes = _cli_commands(), _mcp_tools(), _routes()
    if "GET /health" not in routes:
        raise SystemExit("service.py has no GET /health: the storage diagram names it")

    def rows(items: list[str], per: int) -> str:
        return "<br/>".join(" · ".join(items[i:i + per]) for i in range(0, len(items), per))

    return "```mermaid\n" + "\n".join([
        THEME,
        "flowchart LR",
        f'  cli["okl CLI<br/>{len(cmds)} commands"]',
        f'  mcp["okl mcp, for any MCP agent<br/>{rows(tools, 2)}"]',
        '  client["okl.client.Client"]',
        f'  service["okl serve (okl.service)<br/>{len(routes)} HTTP routes<br/>OKL_TOKEN guards all but /health"]',
        '  store["okl.store.Store"]',
        '  sqlite[("SQLite<br/>.okl/okl.db by default")]',
        '  pg[("Postgres<br/>the postgres extra")]',
        "  cli --> client",
        "  mcp --> client",
        '  client -- "OKL_SERVICE_URL, or service_url in .okl/config.json" --> service',
        '  client -- "otherwise, in this process" --> store',
        "  service --> store",
        '  store -- "sqlite:/// URL, or none" --> sqlite',
        '  store -- "OKL_DATABASE_URL starting postgres" --> pg',
        ARROWS,
    ]) + "\n```"


# --- writing the doc ----------------------------------------------------------------------

BLOCKS = {"layers": layers_diagram, "storage": storage_diagram}


def render(text: str) -> str:
    """`text` with every generated block rewritten from the code."""
    for name, make in BLOCKS.items():
        pattern = re.compile(rf"(<!-- generated:{name} -->\n)(?:.*?\n)?(<!-- /generated:{name} -->)", re.S)
        if not pattern.search(text):
            raise SystemExit(f"{DOC.relative_to(ROOT)} has no generated:{name} markers")
        body = f"{make()}\n"
        text = pattern.sub(lambda m, b=body: m.group(1) + b + m.group(2), text)
    return text


def main() -> int:
    """Rewrite the generated blocks, or with --check exit 1 when they are stale."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if the generated blocks are stale")
    args = ap.parse_args()
    current = DOC.read_text(encoding="utf-8")
    fresh = render(current)
    if args.check:
        if fresh != current:
            print("docs/ARCHITECTURE.md is stale: the code moved and its generated diagrams did "
                  "not. Re-run: python3 docs/render_architecture.py", file=sys.stderr)
            return 1
        print("docs/ARCHITECTURE.md: generated diagrams are current")
        return 0
    if fresh != current:
        DOC.write_text(fresh, encoding="utf-8")
        print("rewrote the generated diagrams in docs/ARCHITECTURE.md")
    else:
        print("docs/ARCHITECTURE.md: already current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
