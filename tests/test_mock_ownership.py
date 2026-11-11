"""Tests replace only okl's own code: a fake of a library okl does not own is a guess about it.

Lesson seed:python-canon:py_dont_mock_what_you_dont_own (three past breaks, #415). A test put a
stand-in for fastembed's cross-encoder into sys.modules (#274) and another replaced
huggingface_hub.constants with a namespace (#290); both keep passing if the library changes.
This reads every patch the tests make (monkeypatch's setattr, delattr and setitem on sys.modules,
mock.patch, patch.object), resolves its target through the file's own imports, and fails on a new
one that replaces code okl does not own. The ones that were here first are listed with why, and the
list only shrinks.

Not counted: okl's own modules and the repository's scripts; the environment (sys.argv, sys.path,
os.environ, Path.home); and None in sys.modules, which stands for a package that is not installed
rather than a guess at how it behaves. A target held in a variable is not resolved.
"""
import ast
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OWN = {p.stem for d in ("evals", "ci", "tests", "docs", "hooks") for p in (REPO / d).glob("*.py")} | {"okl"}
ENVIRONMENT = {"sys.argv", "sys.path", "os.environ", "pathlib.Path.home"}
ALLOWED = {   # here before the check; each says why, and a fix removes its line
    ("test_check_paths.py", "tempfile.gettempdir"): "points the temp directory at tmp_path (environment)",
    ("test_okl.py", "hmac.compare_digest"): "a spy that calls the real function, to show the token is compared in constant time",
    ("test_okl.py", "pathlib.Path.iterdir"): "a spy on the real method, counting directory reads",
    ("test_okl.py", "psycopg"): "a stand-in for psycopg's Error class; to replace with an adapter okl owns",
    ("test_owner_paths.py", "subprocess.run"): "simulates git missing; to replace with an adapter okl owns",
    ("test_rerank.py", "fastembed"): "the lesson's own break (#274); to replace with an adapter okl owns",
    ("test_rerank.py", "fastembed.rerank"): "the lesson's own break (#274); to replace with an adapter okl owns",
    ("test_rerank.py", "fastembed.rerank.cross_encoder"): "the lesson's own break (#274); to replace with an adapter okl owns",
    ("test_rerank.py", "huggingface_hub.constants"): "the lesson's own break (#290); to replace with an adapter okl owns",
    ("test_scaffold.py", "importlib.metadata.distribution"): "a stand-in for the installed distribution's metadata",
    ("test_scaffold.py", "pathlib.Path.read_text"): "simulates an unreadable file",
    ("test_stem.py", "sqlite3.connect"): "wraps the real connect with a short lock timeout",
}


def _imports(tree: ast.AST) -> dict[str, str]:
    """Each name a file imports, mapped to the dotted module or object it stands for."""
    names: dict[str, str] = {}
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                names[a.asname or a.name.split(".")[0]] = a.name if a.asname else a.name.split(".")[0]
        elif isinstance(n, ast.ImportFrom) and n.module:
            for a in n.names:
                names[a.asname or a.name] = f"{n.module}.{a.name}"
    return names


def _dotted(node: ast.AST, names: dict[str, str]) -> str | None:
    """A patch target as a dotted path, or None when it is a local object or a variable."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name) and node.id in names:
        return ".".join([names[node.id], *reversed(parts)])
    return None


def _receivers(tree: ast.AST) -> set[str]:
    """monkeypatch, and every name bound by `with monkeypatch.context() as m`."""
    out = {"monkeypatch"}
    for n in ast.walk(tree):
        if isinstance(n, ast.With):
            for item in n.items:
                ctx = item.context_expr
                if (isinstance(ctx, ast.Call) and isinstance(ctx.func, ast.Attribute) and ctx.func.attr == "context"
                        and isinstance(item.optional_vars, ast.Name)):
                    out.add(item.optional_vars.id)
    return out


def _target(call: ast.Call, names: dict[str, str], receivers: set[str]) -> str | None:
    """What a patch call replaces, as a dotted path, or None when the call is not a patch."""
    fn, args = call.func, call.args
    if not args:
        return None
    on = fn.value if isinstance(fn, ast.Attribute) else None
    attr = fn.attr if isinstance(fn, ast.Attribute) else fn.id if isinstance(fn, ast.Name) else ""
    by_monkeypatch = isinstance(on, ast.Name) and on.id in receivers
    if by_monkeypatch and attr == "setitem":
        return _module_put(args, names)
    if (by_monkeypatch and attr in ("setattr", "delattr")) or attr == "patch" or (
            attr == "object" and isinstance(on, ast.Name | ast.Attribute) and _last(on) == "patch"):
        base = _dotted(args[0], names)
        if base and len(args) > 1 and isinstance(args[1], ast.Constant) and isinstance(args[1].value, str) \
                and not isinstance(args[0], ast.Constant):
            return f"{base}.{args[1].value}"
        return base
    return None


def _module_put(args: list[ast.expr], names: dict[str, str]) -> str | None:
    """The module a setitem on sys.modules replaces, unless it puts None (a package not installed)."""
    if _dotted(args[0], names) != "sys.modules" or len(args) < 3:
        return None
    absent = isinstance(args[2], ast.Constant) and args[2].value is None
    return None if absent else _dotted(args[1], names)


def _last(node: ast.AST) -> str:
    return node.attr if isinstance(node, ast.Attribute) else node.id if isinstance(node, ast.Name) else ""


def not_owned(source: str) -> set[str]:
    """Every target a test file's patches replace that okl does not own."""
    tree = ast.parse(source)
    names, receivers = _imports(tree), _receivers(tree)
    found = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Call) and (t := _target(n, names, receivers)) \
                and t.split(".")[0] not in OWN and t not in ENVIRONMENT:
            found.add(t)
    return found


def found_now() -> set[tuple[str, str]]:
    """Each (test file, target) the suite's patches replace that okl does not own."""
    return {(f.name, t) for f in sorted((REPO / "tests").glob("*.py")) for t in not_owned(f.read_text())}


def test_no_new_test_patches_code_okl_does_not_own():
    """Fake an adapter okl owns, and test the adapter against the real library."""
    new = sorted(found_now() - set(ALLOWED))
    assert new == [], ("these tests replace code okl does not own: put the call behind a small adapter "
                       f"okl owns, test that against the real library, and fake the adapter: {new}")


def test_the_list_only_shrinks():
    """A listed patch that was removed comes off the list."""
    gone = sorted(set(ALLOWED) - found_now())
    assert gone == [], f"no longer in the tests, so take them off ALLOWED: {gone}"


def test_the_reader_finds_each_shape_of_patch():
    """setattr on an imported module, a dotted string, sys.modules, mock.patch and patch.object
    are read; okl's own code, the environment, a package set to None and a local object are not."""
    source = '''
import subprocess, sys, types
from pathlib import Path
from unittest import mock
from okl import core
import requests

def test_x(monkeypatch, tmp_path):
    monkeypatch.setattr(subprocess, "run", lambda *a: None)
    monkeypatch.setattr("shutil.which", lambda _: None)
    monkeypatch.setitem(sys.modules, "fastembed", types.ModuleType("fastembed"))
    with monkeypatch.context() as m:
        m.setitem(sys.modules, "psycopg", types.SimpleNamespace())
    mock.patch("yaml.safe_load")
    mock.patch.object(requests.Session, "get")
    monkeypatch.setattr(core, "check", lambda **k: {})
    monkeypatch.setattr(sys, "argv", ["x"])
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    monkeypatch.setitem(sys.modules, "uvicorn", None)
    client = object()
    monkeypatch.setattr(client, "url", "x")
'''
    assert not_owned(source) == {"subprocess.run", "shutil.which", "fastembed", "psycopg", "yaml.safe_load",
                                 "requests.Session.get"}
