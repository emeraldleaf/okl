#!/usr/bin/env python3
"""Every package the tests import is one CI installs for them.

The check behind the `n_7e50e3588bcd` lesson: a test that imports an undeclared package passes
only where that package happens to be installed. CI installs the project and its `dev` group
(`pip install -e . --group dev`), so a module the tests import, or name to
`pytest.importorskip`, must be the standard library, okl's own, a module of this repository, or
come from a distribution named in `[project].dependencies` or the `dev` group. The extras do not
count: CI does not install them. The first version grepped the tests for one import, so a
break that took fastapi out of the dev group passed it, and the tests that import it skipped
themselves (REPORT §4af, #318).
"""
import ast
import re
import sys
import tomllib
from importlib.metadata import packages_distributions
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def norm(name: str) -> str:
    """A distribution name as PEP 503 compares it."""
    return re.sub(r"[-_.]+", "-", name).lower()


project = tomllib.loads((REPO / "pyproject.toml").read_text())
declared = {norm(re.match(r"[A-Za-z0-9._-]+", r).group(0))
            for r in [*project["project"].get("dependencies", []), *project["dependency-groups"]["dev"]]
            if isinstance(r, str)}
local = {"okl"} | {p.stem for d in ("tests", "evals", "ci") for p in (REPO / d).glob("*.py")}
dists = packages_distributions()

imported: dict[str, str] = {}
for path in sorted((REPO / "tests").rglob("*.py")):
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
