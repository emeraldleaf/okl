"""Defects the review for #446 found in the eval harness, each pinned by its behaviour."""
from __future__ import annotations

import ast
import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "evals"))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "evals" / f"{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_a_brace_in_the_judges_prose_does_not_void_its_verdict():
    """ab_harness read from the first brace to the last, so prose with a brace before the JSON
    turned a good verdict into a judge failure."""
    ab = _load("ab_harness")
    raw = 'The handler returns {status} on error. {"implemented": true, "defect_reproduced": false}'
    assert ab.parse_judge(raw) == {"implemented": True, "defect_reproduced": False}
    with pytest.raises(ValueError, match="missing boolean defect_reproduced"):
        ab.parse_judge('{"implemented": true, "defect_reproduced": "no"}')
    with pytest.raises(ValueError, match="no JSON"):
        ab.parse_judge("no verdict here")


def test_a_screen_answer_of_the_string_false_is_no_verdict(monkeypatch):
    """bool("false") is True: pick_fix read a string verdict as bearing on the change."""
    pf = _load("pick_fix")
    item = ("dev", 1, "n_x", ["a.py"], ["it does a thing"], "Lesson text")
    monkeypatch.setattr(pf, "ask", lambda *a, **k: '{"bears": "false", "reason": "no"}')
    assert pf.screen_one(item) is None
    monkeypatch.setattr(pf, "ask", lambda *a, **k: 'Thinking {x}. {"bears": false, "reason": "no"}')
    assert pf.screen_one(item)["bears"] is False


def test_an_echoed_id_matches_only_at_a_prefix_boundary():
    """A model can drop a pack prefix; it cannot turn "x_abc" into "abc"."""
    wl = _load("when_lines")
    ids = ["seed:pack:abc", "x_abc", "n_1"]
    assert wl.own_id("n_1", ids) == "n_1"
    assert wl.own_id("pack:abc", ids) == "seed:pack:abc"
    assert wl.own_id("abc", ["x_abc"]) is None
    assert wl.own_id("abc", ["seed:a:abc", "seed:b:abc"]) is None   # ambiguous stays unanswered


def test_a_model_call_with_no_cwd_runs_in_an_empty_room(monkeypatch):
    """pick_fix and plan_reach ran from wherever the script started, the checkout (§4ba–§4bc)."""
    import sandbox as sb
    seen = []

    def fake(cmd, **kw):
        seen.append(kw)
        return subprocess.CompletedProcess(cmd, 0, stdout='{"result": "x", "modelUsage": {"claude-sonnet-5-5": {}}}', stderr="")
    monkeypatch.setenv("CLAUDE_EFFORT", "xhigh")   # set, so its absence below means something
    for name in ("pick_fix", "plan_reach"):
        mod = _load(name)
        monkeypatch.setattr(mod.subprocess, "run", fake)
        mod.ask(["claude", "-p"], "q", "sonnet") if name == "pick_fix" else mod.ask(["claude", "-p"], "q")
    assert len(seen) == 2
    for kw in seen:
        assert not sb.inside_repo(Path(kw["cwd"])) and "CLAUDE_EFFORT" not in kw["env"]


def _model_calls(tree: ast.AST) -> list[ast.Call]:
    """subprocess.run/Popen calls that feed a prompt on stdin, other than to a named tool like tar."""
    out = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr in ("run", "Popen") and getattr(node.func.value, "id", "") == "subprocess"):
            continue
        if not any(k.arg == "input" for k in node.keywords) or not node.args:
            continue
        first = node.args[0]
        if isinstance(first, ast.List) and first.elts and isinstance(first.elts[0], ast.Constant) \
                and first.elts[0].value != "claude":
            continue
        out.append(node)
    return out


def test_every_model_call_in_the_evals_names_its_room_and_its_environment():
    """A call that names neither runs where the script started and with everything the launching
    session set (#446). evals/sandbox.ask checks the room is outside the checkout at run time."""
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "evals/*.py"], capture_output=True, text=True,
                           check=True).stdout.split()
    assert len(files) > 50
    missing = []
    for f in files:
        tree = ast.parse((ROOT / f).read_text())
        parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        for call in _model_calls(tree):
            kw = {k.arg: k.value for k in call.keywords}
            if not {"cwd", "env"} <= set(kw):
                missing.append(f"{f}:{call.lineno} lacks {sorted({'cwd', 'env'} - set(kw))}")
                continue
            # Present is not enough (review on #451): the environment must come from clean_env, followed
            # through local names, and the working directory must not be the checkout.
            if not _clean(kw["env"], call, parents, tree):
                missing.append(f"{f}:{call.lineno} env does not come from sandbox.clean_env")
            if any((isinstance(n, ast.Name) and n.id == "REPO") or (isinstance(n, ast.Attribute) and n.attr == "REPO")
                   for n in ast.walk(kw["cwd"])):
                missing.append(f"{f}:{call.lineno} runs in the checkout")
    assert missing == [], missing


# Names an env may come from because each is built by clean_env, which its own test holds:
# review_repo.ENV and explain_search.ENV (module constants), and Replayer.env.
CLEAN_SOURCES = {"clean_env", "env_for", "generator_env"}
CLEAN_NAMES = {"ENV", "rp.ENV", "self.env", "r.env"}


def _unpacked(name: str, scope: ast.AST, tree: ast.AST) -> list[ast.AST]:
    """For `a, name = f(...)` with `f` defined in the module: the element of each tuple `f` returns that
    lands in `name` (e2e_read_briefing's `repo, env = build(room, arm)`)."""
    defs = {d.name: d for d in ast.walk(tree) if isinstance(d, ast.FunctionDef)}
    out: list[ast.AST] = []
    for n in ast.walk(scope):
        if not (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and _dotted(n.value.func) in defs):
            continue
        for t in n.targets:
            if isinstance(t, ast.Tuple):
                at = [i for i, e in enumerate(t.elts) if isinstance(e, ast.Name) and e.id == name]
                rets = [r.value for r in ast.walk(defs[_dotted(n.value.func)]) if isinstance(r, ast.Return)
                        and isinstance(r.value, ast.Tuple)]
                out += [(r, defs[_dotted(n.value.func)]) for r in rets for i in at if i < len(r.elts)]
    # Resolve each returned element inside the function that returns it.
    return [_Resolved(r.elts[i], fn) for (r, fn) in out for i in [_index_of(r, name, scope)]]


class _Resolved(ast.AST):
    """A returned expression with the function it belongs to, for _clean to resolve names in."""
    def __init__(self, expr: ast.AST, fn: ast.FunctionDef) -> None:
        super().__init__()
        self.expr, self.fn = expr, fn


def _index_of(ret: ast.Tuple, name: str, scope: ast.AST) -> int:
    for n in ast.walk(scope):
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Tuple):
                    for i, e in enumerate(t.elts):
                        if isinstance(e, ast.Name) and e.id == name:
                            return i
    return 0


def _dotted(n: ast.AST) -> str:
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return f"{_dotted(n.value)}.{n.attr}"
    return ""


def _clean(expr: ast.AST, at: ast.AST, parents: dict, tree: ast.AST, depth: int = 0) -> bool:  # noqa: PLR0911 - one return per kind of expression
    """Whether `expr` is an environment built by clean_env: a call to it (or to a helper built on it),
    a dict that spreads one and nothing from os.environ, a name assigned one in the enclosing function,
    a parameter (its callers are held where they build it), or a known module constant."""
    if depth > 5:
        return False
    if isinstance(expr, _Resolved):
        inner = expr.expr
        # A name in a returned tuple resolves in the function that returns it.
        parents_fn = {c: n for n in ast.walk(expr.fn) for c in ast.iter_child_nodes(n)}
        anchor = next((n for n in ast.walk(expr.fn) if n is inner), expr.fn)
        return _clean(inner, anchor, {**parents, **parents_fn}, tree, depth + 1)
    if any(isinstance(n, ast.Attribute) and n.attr == "environ" for n in ast.walk(expr)):
        return False
    if isinstance(expr, ast.Call):
        return _dotted(expr.func).rsplit(".", 1)[-1] in CLEAN_SOURCES
    if isinstance(expr, ast.IfExp):
        return all(_clean(x, at, parents, tree, depth + 1) for x in (expr.body, expr.orelse))
    if isinstance(expr, ast.Dict):
        spread = [v for k, v in zip(expr.keys, expr.values, strict=True) if k is None]
        return bool(spread) and all(_clean(v, at, parents, tree, depth + 1) for v in spread)
    if _dotted(expr) in CLEAN_NAMES:
        return True
    if isinstance(expr, ast.Name):
        fn = at
        while fn is not None and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            fn = parents.get(fn)
        scope = fn if fn is not None else tree
        if fn is not None and expr.id in {a.arg for a in fn.args.args + fn.args.kwonlyargs}:
            return True
        values = [n.value for n in ast.walk(scope) if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == expr.id for t in n.targets)]
        values += [n.items[0].context_expr for n in ast.walk(scope) if isinstance(n, ast.With) and n.items
                   and isinstance(n.items[0].optional_vars, ast.Name) and n.items[0].optional_vars.id == expr.id]
        values += _unpacked(expr.id, scope, tree)
        return bool(values) and all(_clean(v, at, parents, tree, depth + 1) for v in values)
    return False


def _repo(tmp_path: Path) -> Path:
    room = tmp_path / "room"
    room.mkdir()
    ident = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(room)], check=True)
    (room / "a.py").write_text("x = 1\n")
    subprocess.run(["git", "-C", str(room), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(room), *ident, "commit", "-qm", "base", "--no-verify"], check=True)
    return room


def test_a_patch_carries_the_files_the_agent_created(tmp_path):
    """outcome_replay saved `git diff`, tracked files only: a new file was not in the patch."""
    o = _load("outcome_replay")
    room = _repo(tmp_path)
    (room / "a.py").write_text("x = 2\n")
    (room / "new_test.py").write_text("def test_x():\n    pass\n")
    patch = o.patch_of(room)
    assert "+++ b/a.py" in patch and "+++ b/new_test.py" in patch
    staged = subprocess.run(["git", "-C", str(room), "diff", "--cached", "--name-only"], capture_output=True, text=True).stdout
    assert staged == ""   # left unstaged, so a grader reading the index sees the tree as the agent left it


def test_the_judge_is_told_when_a_diff_is_cut():
    """§4bf judged a control on the first 12,000 of 172,615 characters, with no word that it was cut."""
    dm = _load("drift_mutate")
    assert dm.for_judge("short diff") == "short diff"
    long = "+x\n" * 5000
    seen = dm.for_judge(long)
    assert seen.startswith(long[:dm.JUDGE_CHARS]) and seen.endswith(
        f"[the diff is cut here: it has {len(long)} characters, and you see the first {dm.JUDGE_CHARS}]")


def test_a_breaker_never_works_on_a_tree_that_is_not_clean_at_base(tmp_path):
    """git() never raises, so a failed reset let the next break stack on the last one."""
    dm = _load("drift_mutate")
    room = _repo(tmp_path)
    base = subprocess.run(["git", "-C", str(room), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    dm.at_base(room, base)
    (room / "a.py").write_text("x = 3\n")
    with pytest.raises(RuntimeError, match="not clean at BASE"):
        dm.at_base(room, base)
    subprocess.run(["git", "-C", str(room), "checkout", "-q", "--", "a.py"], check=True)
    with pytest.raises(RuntimeError, match="not clean at BASE"):
        dm.at_base(room, "0" * 40)


def test_the_run_guard_watches_what_a_replay_reads_mid_run():
    """outcome_regrade copies the graders into each room per session; an edit to them mid-run changed
    the instrument behind half the sessions without the guard noticing (#446)."""
    import run_guard
    assert {"tests/replay_graders_4aw.py", "evals/replay-*.json"} <= set(run_guard.READS)
    assert (ROOT / "tests" / "replay_graders_4aw.py").exists() and list((ROOT / "evals").glob("replay-*.json"))


def test_the_4af_note_quotes_its_receipt():
    """§4af's note: drift caught 7 of the 11 breaking patches the judge gave no verdict, against
    14 of the 36 it judged broken, so leaving them out lowered the rate."""
    import json
    rec = json.loads((ROOT / "evals" / "results" / "drift-mutate-20261031-1522.json").read_text())
    breaking = [p for p in rec["patches"] if p["kind"] == "breaking"]

    def caught(p: dict) -> bool:
        return bool(p.get("red")) and p.get("check") == "fail"
    none = [p for p in breaking if p.get("judge") is None and p.get("patch")]
    broken = [p for p in breaking if p.get("judge") == "broken"]
    assert (sum(map(caught, none)), len(none), sum(map(caught, broken)), len(broken)) == (7, 11, 14, 36)
    report = (ROOT / "evals" / "REPORT.md").read_text()
    note = report.split("## 4af.", 1)[1].split("\n## 4ag.", 1)[0]
    flat = " ".join(note.split())
    assert "Drift caught 7 of the 11 breaking patches with no verdict, 3 of the 4 the re-judge called broken, against 14 of the 36 judged broken" in flat
    rejudged = [p for p in json.loads((ROOT / "evals" / "results" / "drift-mutate-20261031-1522-rejudge.json").read_text())["patches"]
                if p.get("rejudged") and p.get("judge") == "broken"]
    assert (sum(map(caught, rejudged)), len(rejudged)) == (3, 4)
    assert sum(p["lesson"].startswith("doc-") for p in none) == 7 and "(7 of the 11 here" in flat


def test_a_session_in_a_repo_tree_sees_no_git_link_and_it_comes_back(tmp_path):
    """A session in a git tree reads its status: §4bf's breakers saw commit subjects naming the experiment
    and the hidden check files listed as deleted. The link is kept outside the tree, under a name that
    says nothing, and restored even when the session fails."""
    import sandbox as sb
    room = _repo(tmp_path)
    with sb.no_git(room):
        assert not (room / ".git").exists() and not [p for p in room.iterdir() if "git" in p.name]
    assert (room / ".git").is_dir()
    with pytest.raises(RuntimeError), sb.no_git(room):
        raise RuntimeError("the session failed")
    assert (room / ".git").is_dir()


def _within(tree: ast.AST, call: ast.Call, ctx: str) -> bool:
    parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
    node = parents.get(call)
    while node is not None:
        if isinstance(node, ast.With) and any(_dotted(i.context_expr.func).endswith(ctx) for i in node.items
                                              if isinstance(i.context_expr, ast.Call)):
            return True
        node = parents.get(node)
    return False


def test_every_breaker_and_the_census_judge_work_with_the_git_link_hidden():
    """The wiring, not only the helper: removing `with sb.no_git(wt)` from a runner passed every test
    before (review on #451)."""
    for f, argv in (("evals/drift_mutate.py", "BREAKER"), ("evals/rule_mutate.py", "BREAKER"),
                    ("evals/lesson_census.py", "JUDGE")):
        tree = ast.parse((ROOT / f).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args
                 and _dotted(n.args[0]).rsplit(".", 1)[-1] == argv
                 and _dotted(n.func).rsplit(".", 1)[-1] in ("claude", "run")]   # not the receipt's " ".join
        assert calls, f
        for c in calls:
            assert _within(tree, c, "no_git"), f"{f}:{c.lineno} runs {argv} with the git link in place"


def test_the_ab_receipt_records_its_environment_and_the_settings_effort():
    """The A/B harness's calls without --restricted read the user's settings file; its receipt says what
    it set, and that the children ran in clean_env."""
    tree = ast.parse((ROOT / "evals" / "ab_harness.py").read_text())
    receipt = [d for d in ast.walk(tree) if isinstance(d, ast.Dict)
               and any(isinstance(k, ast.Constant) and k.value == "generator_cmd" for k in d.keys)]
    assert len(receipt) == 1
    keys = {k.value for k in receipt[0].keys if isinstance(k, ast.Constant)}
    assert {"model_env", "settings_effort"} <= keys


def test_a_receipt_is_marked_only_when_its_run_used_clean_env(monkeypatch):
    """A blanket default named a run whose child got os.environ (review on #451)."""
    import run_guard
    import sandbox as sb
    monkeypatch.setattr(sb, "USED", False)
    assert "model_env" not in run_guard.start().stamp({})
    sb.clean_env()
    assert run_guard.start().stamp({})["model_env"] == sb.MODEL_ENV


def test_the_tasks_store_snapshot_carries_the_log(monkeypatch, tmp_path):
    """realwork_tasks backed up the live store read-write; it now goes through copy_sqlite."""
    import sqlite3
    rt = _load("realwork_tasks")
    live = tmp_path / "repo" / ".okl" / "okl.db"
    live.parent.mkdir(parents=True)
    writer = sqlite3.connect(live)
    writer.execute("PRAGMA journal_mode=WAL")
    writer.execute("PRAGMA wal_autocheckpoint=0")
    writer.execute("CREATE TABLE t (x)")
    writer.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(20)])
    writer.commit()
    monkeypatch.setattr(rt, "REPO", tmp_path / "repo")
    monkeypatch.setattr(rt, "PRIVATE", tmp_path / "private")
    copy, _digest = rt.snapshot_store()
    with sqlite3.connect(copy) as c:
        assert c.execute("SELECT count(*) FROM t").fetchone() == (20,)
    writer.close()
