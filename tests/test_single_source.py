"""A fact okl defines once is imported, never written out again.

Lesson seed:geospatial-enforcement-defects:r_single_source_sets (seven past breaks, #415): two
definitions of one fact are two facts free to diverge. The parser and the service each wrote out
the decision settings, core repeated the statuses only `okl retire` sets, and review.py defined
the record types that are never advice a second time beside drift.py's. Every string collection
defined at module level in src/okl (a set, frozenset, tuple or list of two or more strings) is
canonical; this fails when the same values are written out anywhere else in the repository's
Python, a second definition included. A literal inside an assert pins a constant on purpose and
is not counted. The ones that were here first are listed with why, and the list only shrinks.
"""
import ast
import subprocess
import typing
from pathlib import Path

from okl import decide, service

REPO = Path(__file__).resolve().parent.parent
ALLOWED = {   # (file, canonical): why it is written out; a fix removes its line
    ("src/okl/service.py", "src/okl/decide.py::SETTINGS"):
        "pydantic needs a Literal mypy can read; test_the_service_reads_the_decide_settings holds the two equal",
    ("evals/bench/assemble_queries.py", "src/okl/core.py::TRIGGER_TYPES"): "here before the check",
    ("evals/reach_detail.py", "src/okl/core.py::TRIGGER_TYPES"): "here before the check",
    ("evals/bench/v2.py", "src/okl/decide.py::HARNESS_PREFIXES"): "here before the check",
    ("evals/compare_seed_briefings.py", "src/okl/cli/lessons.py::_BRIEFED_BUCKETS"): "here before the check",
    ("evals/grid_setup.py", "src/okl/cli/lessons.py::_BRIEFED_BUCKETS"): "here before the check",
    ("evals/hybrid_grid.py", "src/okl/cli/lessons.py::_BRIEFED_BUCKETS"): "here before the check (the lesson's break on #267)",
    ("evals/probe_rephrase.py", "src/okl/cli/lessons.py::_BRIEFED_BUCKETS"): "here before the check",
    ("evals/embedder_select.py", "src/okl/store.py::RETIRED_STATUSES"): "here before the check",
    ("evals/realwork_tasks.py", "src/okl/store.py::RETIRED_STATUSES"): "here before the check",
    ("evals/lesson_census.py", "src/okl/review.py::JUDGE"): "§4ai's judge, kept as that census ran it",
    ("evals/lesson_census.py", "src/okl/review.py::VERDICTS"): "here before the check",
    ("evals/lesson_census.py", "src/okl/review.py::QUESTIONED"): "here before the check",
    ("tests/test_docs.py", "src/okl/review.py::QUESTIONED"): "here before the check",
    ("tests/test_retire.py", "src/okl/store.py::RETIRED_STATUSES"): "each status written out, so a test names the one that fails",
    ("tests/test_scaffold.py", "src/okl/coexist.py::OKL_HOOK_SCRIPTS"): "here before the check",
}


def strings(node: ast.AST) -> frozenset[str] | None:
    """The values of a literal collection of two or more distinct strings, or None."""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in (
            "frozenset", "set", "tuple", "list") and len(node.args) == 1:
        node = node.args[0]
    if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) and node.value.id == "Literal":
        node = node.slice
    if isinstance(node, ast.Set | ast.Tuple | ast.List) and len(node.elts) >= 2 and all(
            isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.elts):
        values = frozenset(e.value for e in node.elts)
        return values if len(values) >= 2 else None
    return None


def _definitions(path: str, tree: ast.Module) -> list[tuple[frozenset[str], str, ast.AST]]:
    out = []
    for n in tree.body:
        target = n.targets[0] if isinstance(n, ast.Assign) else n.target if isinstance(n, ast.AnnAssign) else None
        if isinstance(target, ast.Name) and getattr(n, "value", None) is not None and (v := strings(n.value)):
            out.append((v, f"{path}::{target.id}", n.value))
    return out


def restatements(sources: dict[str, str]) -> set[tuple[str, str]]:
    """Each (file, canonical) where a file writes out the values a src/okl definition holds."""
    trees = {p: ast.parse(text) for p, text in sources.items()}
    canon: dict[frozenset[str], str] = {}
    judged: set[int] = set()   # the nodes inside every src/okl definition, each judged below
    found = set()
    for path in sorted(p for p in trees if p.startswith("src/okl/")):
        for values, name, node in _definitions(path, trees[path]):
            judged |= {id(x) for x in ast.walk(node)}
            if values in canon:
                found.add((path, canon[values]))   # a second definition of one fact
            else:
                canon[values] = name
    for path, tree in trees.items():
        pinned = {id(x) for n in ast.walk(tree) if isinstance(n, ast.Assert) for x in ast.walk(n)}
        for n in ast.walk(tree):
            if id(n) not in judged and id(n) not in pinned and (v := strings(n)) and v in canon:
                found.add((path, canon[v]))
    return found


def tracked() -> dict[str, str]:
    """Every Python file the repository tracks, as committed paths with their text."""
    names = subprocess.run(["git", "-C", str(REPO), "ls-files", "--", "*.py"], capture_output=True,
                           text=True, check=True).stdout.split()
    return {n: (REPO / n).read_text(encoding="utf-8") for n in names if (REPO / n).exists()}


def test_no_fact_defined_in_src_okl_is_written_out_again():
    """Import the definition, or derive from it."""
    new = sorted(restatements(tracked()) - set(ALLOWED))
    assert new == [], f"these write out values a src/okl constant holds: import it instead: {new}"


def test_the_list_only_shrinks():
    """A listed restatement that was removed comes off the list."""
    gone = sorted(set(ALLOWED) - restatements(tracked()))
    assert gone == [], f"no longer written out, so take them off ALLOWED: {gone}"


def test_the_service_reads_the_decide_settings():
    """The one restatement in src/okl that stays: pydantic's Literal, held equal here."""
    assert typing.get_args(service.CheckReq.model_fields["decision"].annotation) == decide.SETTINGS


def test_the_reader_finds_a_restatement_a_second_definition_and_skips_a_pin():
    """A copy elsewhere, a second definition in src/okl and a Literal are found; an assert is not."""
    sources = {
        "src/okl/a.py": 'KINDS = frozenset({"Rule", "Defect"})\nMODES = ("on", "off")\n',
        "src/okl/b.py": 'SAME = ("Defect", "Rule")\n',
        "evals/x.py": 'for k in ("Rule", "Defect"):\n    pass\nassert MODES == ("off", "on")\n',
        "src/okl/c.py": 'from typing import Literal\nmode: Literal["on", "off"] = "on"\n',
    }
    assert restatements(sources) == {("src/okl/b.py", "src/okl/a.py::KINDS"), ("evals/x.py", "src/okl/a.py::KINDS"),
                                     ("src/okl/c.py", "src/okl/a.py::MODES")}
