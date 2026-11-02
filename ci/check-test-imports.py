#!/usr/bin/env python3
"""Every package the tests import is one CI installs for them.

The check behind the `n_7e50e3588bcd` lesson: a test that imports an undeclared package passes
only where that package happens to be installed. What CI installs is read from its workflow's
`pip install -e .` and `uv sync` lines, and only what every one installs counts: the project's dependencies, any extras (in
brackets, or `--extra`/`--all-extras`), uv's default groups unless turned off, and each `--group`.
A module the tests import, or name to `pytest.importorskip`, must be the standard library,
okl's own, a module of this repository, or come from one of those distributions. Nothing else
counts: a package an extra declares that CI never installs is as undeclared as any other. The first version grepped the tests for one import, so a
break that took fastapi out of the dev group passed it, and the tests that import it skipped
themselves (REPORT §4af, #318).
"""
import ast
import re
import subprocess
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def norm(name: str) -> str:
    """A distribution name as PEP 503 compares it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def tracked(*paths: str) -> list[Path]:
    """The committed files under `paths` (CLAUDE.md: audits read the repo, not the working tree)."""
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", *paths], capture_output=True, text=True, check=True)
    return [REPO / f for f in out.stdout.split() if f.endswith(".py")]


project = tomllib.loads((REPO / "pyproject.toml").read_text())
EXTRAS = project["project"].get("optional-dependencies", {})
GROUPS = project.get("dependency-groups", {})


def installed_by(extras: list[str], groups: list[str]) -> set[str]:
    """The distributions one install line brings in: dependencies, extras, groups."""
    wanted = [*project["project"].get("dependencies", [])]
    for extra in extras:
        wanted += EXTRAS.get(extra, [])
    for group in groups:
        wanted += GROUPS[group]
    return {norm(re.match(r"[A-Za-z0-9._-]+", r).group(0)) for r in wanted if isinstance(r, str)}


def uv_sync(flags: str) -> set[str]:
    """What `uv sync <flags>` installs: uv's default groups (`dev` unless [tool.uv] names others)
    unless --no-dev or --no-default-groups, each --group, and --extra or --all-extras."""
    default = project.get("tool", {}).get("uv", {}).get("default-groups", ["dev"])
    groups = [] if re.search(r"--no-dev\b|--no-default-groups\b", flags) else (
        list(GROUPS) if default == "all" else list(default))
    extras = list(EXTRAS) if "--all-extras" in flags else re.findall(r"--extra[ =]([\w-]+)", flags)
    return installed_by(extras, groups + re.findall(r"--group[ =]([\w-]+)", flags))


installs: list[set[str]] = []
for line in (REPO / ".github/workflows/ci.yml").read_text().splitlines():
    if line.lstrip().startswith("#"):
        continue                       # a comment naming a command installs nothing
    if m := re.search(r"pip install -e \.(?:\[([\w,-]+)\])?((?: --group [\w-]+)*)", line):
        installs.append(installed_by(list(filter(None, (m.group(1) or "").split(","))),
                                     re.findall(r"--group ([\w-]+)", m.group(2))))
    elif m := re.search(r"\buv sync\b(.*)", line):
        installs.append(uv_sync(m.group(1)))
if not installs:
    sys.exit("UNDECLARED TEST IMPORT: ci.yml has no `pip install -e .` or `uv sync` line to read")

# Each job that installs runs the tests, so a test may use only what every one of them installs.
declared = set.intersection(*installs)
local = {"okl"} | {p.stem for p in tracked("tests/", "evals/", "ci/")}
dists = packages_distributions()

imported: dict[str, str] = {}
for path in tracked("tests/"):
    for node in ast.walk(ast.parse(path.read_text(), str(path))):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names = [node.module]
        elif (isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "importorskip"
              and node.args and isinstance(node.args[0], ast.Constant)):
            names = [node.args[0].value]
        for name in names:
            imported.setdefault(name.split(".")[0], f"{path.relative_to(REPO)}:{node.lineno}")

undeclared = []
for module, where in sorted(imported.items()):
    if module in sys.stdlib_module_names or module in local:
        continue
    # A module this environment cannot place is named for itself: it is declared under that
    # name or it is not declared at all.
    if not any(norm(d) in declared for d in dists.get(module, [module])):
        undeclared.append(f"{module} ({where})")

if undeclared:
    sys.exit("UNDECLARED TEST IMPORT: " + ", ".join(undeclared))
print("NO UNDECLARED IMPORT", len(imported), "modules")  # noqa: T201 - a check script reports on stdout
