#!/usr/bin/env python3
"""Write the generated architecture diagrams from the code, never from memory.

Two of the four architecture diagrams are facts the code already holds, so they are read
from it: the package layers from the import contract in pyproject.toml plus every import
under src/okl, and where lessons are stored from the CLI's commands, the MCP tools, the
service's routes and the store's backends. Each is written as Mermaid source
(docs/architecture/okl-layers.mmd, okl-storage.mmd) and rendered to an SVG beside it, which
docs/ARCHITECTURE.md embeds with alt text generated from the same facts. The other two are
drawn by hand in Excalidraw (docs/architecture/*.excalidraw), held by ci/check-diagram-names.py.

Why an image and not a Mermaid block in the doc: a viewer draws a Mermaid block itself, on
its own background and in its own theme. In a dark VS Code preview the arrows vanished, and
after the colours were fixed the block still showed as solid black there, while the drawn
diagrams, images with a white background, looked right. An image looks the same everywhere.

okl retired its last hand-drawn architecture diagram after it was found wrong in four places
(commit 93933d7): nothing watched it. tests/test_architecture.py runs this with --check, so a
change to the code that moves either diagram fails the suite until it is re-run. Each SVG
carries the sha256 of the source it was rendered from, so --check catches a stale image too,
without a browser.

Writing the sources, the doc and --check use the standard library only: they parse the
source with ast and never import okl. --svg renders with Playwright's Chromium and Mermaid
from a pinned CDN URL, so it needs both and the network; the Excalidraw skill's environment
has them (see docs/DEVELOPING.md).

Usage:
    python3 docs/render_architecture.py           # rewrite the sources and the doc's blocks
    python3 docs/render_architecture.py --svg     # ...and render each source to its SVG
    python3 docs/render_architecture.py --check   # exit 1 if any of them is out of date
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import html
import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "okl"
DOC = ROOT / "docs" / "ARCHITECTURE.md"
OUT = ROOT / "docs" / "architecture"
MERMAID_JS = "https://cdn.jsdelivr.net/npm/mermaid@11.12.2/dist/mermaid.min.js"
STAMP = re.compile(r"<!-- okl:source-sha256 ([0-9a-f]{64}) -->")

# okl's colours, from docs/overview/okl-anatomy.html, as the drawn diagrams use them: light
# boxes with dark teal text, and dark teal arrows, on the white background every render gets.
THEME = ('%%{init: {"theme": "base", "themeVariables": {'
         '"primaryColor": "#e8f0f0", "primaryTextColor": "#1a4d4a", "primaryBorderColor": "#1a4d4a", '
         '"lineColor": "#1a4d4a", "clusterBkg": "#f8f6f3", "clusterBorder": "#8a6a3f", '
         '"titleColor": "#1a4d4a", "edgeLabelBackground": "#ffffff", "textColor": "#1a4d4a"}}}%%')
# Mermaid's default arrow is a hairline, faint once the image is scaled to the page.
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


def layers_diagram() -> tuple[str, str, str]:
    """The layers chart, as (a sentence for above it, its Mermaid source, its alt text): each
    layer of the import contract as a group, with the imports between them."""
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
            "chart." if cli_reaches_all else "")
    title = {f"layer{i}": f"layer {i + 1}" for i in range(len(layers))} | {"outside": "outside the contract"}
    shown = [g for g in order if not (g == "layer0" and cli_reaches_all)]
    members = {g: sorted(m for m in names if group[m] == g) for g in order}
    alt = ("The code's layers, left to right. "
           + "; ".join(f"{title[g]}: {', '.join(members[g])}" for g in shown) + ". "
           + " ".join(f"{title[a].capitalize()} imports from "
                      f"{', '.join(title[b] for b in order if (a, b) in between)}."
                      for a in shown if any((a, b) in between for b in order))
           + "".join(f" {m} imports {t}." for (m, t) in sorted(edges) if group[m] == group[t]))
    return lead, "\n".join(lines), alt


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


def storage_diagram() -> tuple[str, str, str]:
    """The storage chart, as (lead, Mermaid source, alt text): the ways in, the client's
    choice, the service and the backends."""
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

    source = "\n".join([
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
    ])
    alt = (f"Where lessons are stored. The okl CLI ({len(cmds)} commands) and okl mcp, for any "
           f"MCP agent (tools {', '.join(tools)}), both go through okl.client.Client. With "
           "OKL_SERVICE_URL, or service_url in .okl/config.json, the client calls okl serve "
           f"(okl.service: {len(routes)} HTTP routes, OKL_TOKEN guarding all but /health), which "
           "uses okl.store.Store; otherwise the client uses the store in its own process. The "
           "store keeps lessons in SQLite (.okl/okl.db by default, or a sqlite:/// URL) or in "
           "Postgres when OKL_DATABASE_URL starts with postgres (the postgres extra).")
    return "", source, alt


# --- writing the sources, the doc and the renders ---------------------------------------

CHARTS = {"layers": ("okl-layers", layers_diagram), "storage": ("okl-storage", storage_diagram)}


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _block(stem: str, lead: str, alt: str) -> str:
    img = (f'<img src="architecture/{stem}.svg" alt="{html.escape(alt, quote=True)}" '
           'width="100%">')
    return ((f"{lead}\n\n" if lead else "") + img
            + f"\n\nIts source, generated with it: [`{stem}.mmd`](architecture/{stem}.mmd).")


def fresh() -> tuple[str, dict[str, str]]:
    """The doc as it should read, and each chart's Mermaid source by file stem."""
    text = DOC.read_text(encoding="utf-8")
    sources: dict[str, str] = {}
    for name, (stem, make) in CHARTS.items():
        lead, source, alt = make()
        sources[stem] = source + "\n"
        pattern = re.compile(rf"(<!-- generated:{name} -->\n)(?:.*?\n)?(<!-- /generated:{name} -->)", re.S)
        if not pattern.search(text):
            raise SystemExit(f"{DOC.relative_to(ROOT)} has no generated:{name} markers")
        body = _block(stem, lead, alt) + "\n"
        text = pattern.sub(lambda m, b=body: m.group(1) + b + m.group(2), text)
    return text, sources


def stale_renders(sources: dict[str, str]) -> list[str]:
    """The SVGs missing, or rendered from a source other than the one given."""
    out = []
    for stem, source in sources.items():
        svg = OUT / f"{stem}.svg"
        stamp = STAMP.search(svg.read_text(encoding="utf-8")) if svg.exists() else None
        if not stamp or stamp.group(1) != _sha(source):
            out.append(f"docs/architecture/{stem}.svg")
    return out


def render_svg(source: str) -> str:
    """`source` drawn by Mermaid in headless Chromium, as a standalone SVG: labels as SVG text
    (an <img> does not draw HTML labels everywhere), a white background, an explicit size,
    and the sha256 of `source`, which --check compares."""
    from playwright.sync_api import sync_playwright  # only --svg needs it
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(f'<html><body><script src="{MERMAID_JS}"></script></body></html>',
                         wait_until="load")
        # Mermaid sizes no background behind an SVG-text label, so an arrow's label sat on its
        # line: each gets a white box measured from its text, opaque against Mermaid's own
        # half-transparent `.edgeLabel rect` rule. XMLSerializer keeps the result well-formed.
        svg = page.evaluate("""async (src) => {
            mermaid.initialize({startOnLoad: false, htmlLabels: false,
                                flowchart: {htmlLabels: false}});
            const {svg} = await mermaid.render('chart', src);
            const host = document.createElement('div');
            host.innerHTML = svg;
            document.body.appendChild(host);
            const el = host.querySelector('svg');
            for (const label of el.querySelectorAll('g.edgeLabel g.label')) {
                const text = label.querySelector('text');
                if (!text || !text.textContent.trim()) continue;
                const b = text.getBBox();
                const box = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
                box.setAttribute('x', b.x - 4); box.setAttribute('y', b.y - 2);
                box.setAttribute('width', b.width + 8); box.setAttribute('height', b.height + 4);
                box.setAttribute('style', 'fill: #ffffff; opacity: 1');
                text.parentNode.insertBefore(box, text);
            }
            return new XMLSerializer().serializeToString(el); }""", source)
        browser.close()
    box = re.search(r'viewBox="([-\d.]+) ([-\d.]+) ([\d.]+) ([\d.]+)"', svg)
    if not box:
        raise SystemExit("Mermaid returned an SVG with no viewBox")
    x, y, w, h = box.groups()
    head = re.match(r"<svg\b[^>]*>", svg)
    if not head:
        raise SystemExit("Mermaid returned no <svg> element")
    tag = re.sub(r'\s(width|height)="[^"]*"', "", head.group(0))
    tag = re.sub(r'\sstyle="[^"]*"', "", tag).replace("<svg", f'<svg width="{w}" height="{h}"', 1)
    return (tag + f"<!-- okl:source-sha256 {_sha(source)} -->"
            + f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#ffffff"/>'
            + svg[head.end():] + "\n")


def main() -> int:
    """Rewrite the sources and the doc (and with --svg the renders), or with --check exit 1
    when any of them is stale."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if anything generated is stale")
    ap.add_argument("--svg", action="store_true", help="also render each source to its SVG")
    args = ap.parse_args()
    doc, sources = fresh()
    if args.check:
        stale = [] if doc == DOC.read_text(encoding="utf-8") else ["docs/ARCHITECTURE.md"]
        stale += [f"docs/architecture/{stem}.mmd" for stem, src in sources.items()
                  if not (OUT / f"{stem}.mmd").exists()
                  or (OUT / f"{stem}.mmd").read_text(encoding="utf-8") != src]
        renders = stale_renders(sources)
        if stale or renders:
            print("stale, because the code moved and the generated diagrams did not: "
                  + ", ".join(stale + renders) + ". Re-run: python3 docs/render_architecture.py"
                  + (" --svg (it renders with Playwright; see docs/DEVELOPING.md)" if renders else ""),
                  file=sys.stderr)
            return 1
        print("generated architecture diagrams are current: the doc, the sources and the renders")
        return 0
    DOC.write_text(doc, encoding="utf-8")
    for stem, src in sources.items():
        (OUT / f"{stem}.mmd").write_text(src, encoding="utf-8")
    if args.svg:
        for stem, src in sources.items():
            (OUT / f"{stem}.svg").write_text(render_svg(src), encoding="utf-8")
            print(f"rendered docs/architecture/{stem}.svg")
    left = stale_renders(sources)
    print("wrote docs/ARCHITECTURE.md and the Mermaid sources"
          + (f"; still to render: {', '.join(left)} (run with --svg)" if left else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
