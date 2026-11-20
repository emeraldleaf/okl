"""Defects the review for #446 found in the eval harness, each pinned by its behaviour."""
from __future__ import annotations

import ast
import contextlib
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
CLEAN_SOURCES = {"clean_env", "env_for", "generator_env", "call_env"}
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
    assert {"tests/replay_graders_*.py", "evals/replay-*.json"} <= set(run_guard.READS)
    assert list((ROOT / "tests").glob("replay_graders_*.py")) and list((ROOT / "evals").glob("replay-*.json"))


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
    for f, argv in (("evals/drift_mutate.py", "BREAKER"), ("evals/rule_mutate.py", "BREAKER")):
        tree = ast.parse((ROOT / f).read_text())
        calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args
                 and _dotted(n.args[0]).rsplit(".", 1)[-1] == argv
                 and _dotted(n.func).rsplit(".", 1)[-1] in ("claude", "run")]   # not the receipt's " ".join
        assert calls, f
        for c in calls:
            assert _within(tree, c, "no_git"), f"{f}:{c.lineno} runs {argv} with the git link in place"
    # The census judges share one tree across workers, so its link is hidden once around the pool, never
    # per judge: a second rename of a link already moved raised (review on #451).
    tree = ast.parse((ROOT / "evals" / "lesson_census.py").read_text())
    pools = [w for w in ast.walk(tree) if isinstance(w, ast.With)
             and {_dotted(i.context_expr.func).rsplit(".", 1)[-1] for i in w.items if isinstance(i.context_expr, ast.Call)}
             >= {"no_git", "ThreadPoolExecutor"}]
    assert len(pools) == 1
    judges = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and n.args and _dotted(n.args[0]) == "JUDGE"
              and _dotted(n.func).endswith("run")]
    assert judges and not any(_within(tree, c, "no_git") for c in judges)


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
    import sandbox as sb
    opened, real = [], sb.connect

    def watch(target, uri=False):
        opened.append((str(target), uri))
        return real(target, uri=uri)
    monkeypatch.setattr(sb, "connect", watch)   # sandbox's own adapter, not sqlite3
    copy, _digest = rt.snapshot_store()
    # The live store is opened read-only, never as a plain path: a read-write backup also copies the rows,
    # so counting them alone passed the old code (review on #451).
    live_opens = [(t, uri) for t, uri in opened if "repo/.okl/okl.db" in t]
    assert live_opens and all(uri and t.endswith("?mode=ro") for t, uri in live_opens), live_opens
    with contextlib.closing(sqlite3.connect(copy)) as c:
        assert c.execute("SELECT count(*) FROM t").fetchone() == (20,)
    writer.close()


def test_a_census_resume_reuses_only_judgments_made_under_the_current_isolation(tmp_path):
    """A judgment saved before #446 saw the worktree's git status and the session's variables; a resume
    that reused it would pool two instruments (review on #451)."""
    import json as _json

    import sandbox as sb
    lc = _load("lesson_census")
    partial = tmp_path / "p.jsonl"
    partial.write_text("\n".join(_json.dumps(r) for r in (
        {"id": "old", "verdict": "stale"},
        {"id": "other", "verdict": "ok", "model_env": "something else"},
        {"id": "new", "verdict": "ok", "model_env": sb.MODEL_ENV})) + "\n")
    assert set(lc.resumed(partial)) == {"new"} and lc.resumed(tmp_path / "none.jsonl") == {}


def test_the_git_probes_ignore_a_launchers_git_dir(monkeypatch, tmp_path):
    """With an absolute GIT_DIR exported, both probes asked the same repository, so a folder outside it
    passed the check and a worktree was no longer told apart (review on #451)."""
    import sandbox as sb
    repo, wt, other = tmp_path / "repo", tmp_path / "elsewhere" / "wt", tmp_path / "other"
    ident = ["-c", "user.email=t@example.invalid", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    (repo / "a").write_text("x")
    subprocess.run(["git", "-C", str(repo), "add", "a"], check=True)
    subprocess.run(["git", "-C", str(repo), *ident, "commit", "-qm", "c", "--no-verify"], check=True)
    subprocess.run(["git", "-C", str(repo), "worktree", "add", "-q", "--detach", str(wt)], check=True)
    other.mkdir()
    monkeypatch.setattr(sb, "REPO", repo)
    monkeypatch.setenv("GIT_DIR", str(repo / ".git"))
    assert sb.inside_repo(wt) and not sb.inside_repo(other)


def test_a_store_copy_that_would_split_the_file_from_its_log_refuses(tmp_path):
    """A file copy then a log copy is not atomic; the default is to refuse (review on #451)."""
    import sandbox as sb
    with pytest.raises(RuntimeError, match="not copying the file and its log apart"):
        sb.copy_sqlite(tmp_path / "missing.db", tmp_path / "copy.db")


def test_a_garbled_path_is_read_as_its_own_tree_only_when_the_whole_prefix_matches(tmp_path):
    """A shared folder name (every room has a t0) must not pass a call to another run's tree as this one's
    (review on #451); the model's garbling, a dash for an underscore, still does."""
    import json as _json
    ht = _load("harness_transcripts")

    def session(cwd: str, target: str) -> Path:
        f = tmp_path / "s.jsonl"
        f.write_text(_json.dumps({"cwd": cwd, "message": {"role": "assistant", "content": [
            {"type": "tool_use", "id": "t1", "name": "Read", "input": {"file_path": target}}]}}) + "\n")
        return f
    own = ht.breaker(session("/tmp/okl-w-a_b/t0", "/tmp/okl-w-a-b/t0/ci/check-x.sh"), "/main", ("ci/check-x.sh",))
    other = ht.breaker(session("/tmp/okl-w-a_b/t0", "/tmp/okl-w-c_d/t0/ci/check-x.sh"), "/main", ("ci/check-x.sh",))
    assert (own["hidden_asked"], own["outside_worktree_calls"]) == (1, 0)
    assert (other["hidden_asked"], other["outside_worktree_calls"]) == (0, 1)


# --- receipts say what their runs ran (#479) -------------------------------------------------------

REPO = Path(__file__).resolve().parent.parent
# review_repo and every script that imports it. Importing one must not mark the process as having run
# its children in clean_env: an import-time build did, so receipts claimed it whatever their calls used.
REVIEW_REPO_IMPORTERS = ("review_repo", "audit_sample", "briefed_follow", "conditions_agree", "default_read",
                         "explain_search", "review_repo_detail", "review_graded", "review_graded_diagnose",
                         "lesson_finding")


def test_importing_the_eval_scripts_does_not_claim_a_clean_environment():
    """sandbox.USED stays False after importing review_repo and its importers, and turns True once a call's
    environment is built: the receipt's model_env then means a call used it."""
    code = ("import sys, importlib; sys.path[:0] = ['evals', 'src']\n"
            f"for m in {REVIEW_REPO_IMPORTERS!r}: importlib.import_module(m)\n"
            "import sandbox, review_repo\nbefore = sandbox.USED\nreview_repo.call_env()\n"
            "print(before, sandbox.USED)")
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=120)
    assert out.stdout.split() == ["False", "True"], out.stderr[-600:]


# Receipts written at or before this stamp are grandfathered: their rows predate the rule.
ROWS_COMMIT_FROM = "20261117-0500"
_STAMP = __import__("re").compile(r"-(\d{8}-\d{4})\.json$")


def _row_commit_problems(name: str, receipt: object) -> list[str]:
    """What a receipt with rows lacks to say what its rows ran: a commit on every row, and the set of them."""
    rows = receipt.get("rows") if isinstance(receipt, dict) else None
    if not isinstance(rows, list) or not rows:
        return []
    bare = [i for i, r in enumerate(rows) if not isinstance(r, dict) or not r.get("okl_commit")]
    if bare:
        return [f"{name}: rows {bare[:5]} carry no okl_commit (stamp each with run_guard.commit())"]
    if sorted({r["okl_commit"] for r in rows}) != sorted(receipt.get("run_commits") or []):
        return [f"{name}: run_commits does not list the commits its rows ran"]
    return []


def test_the_row_commit_check_finds_what_it_is_for():
    """The check flags a row with no commit and a run_commits that disagrees, and passes a receipt that has both."""
    good = {"rows": [{"okl_commit": "abc1234"}, {"okl_commit": "abc1234"}], "run_commits": ["abc1234"]}
    assert _row_commit_problems("r", good) == [] and _row_commit_problems("r", {"rows": []}) == []
    assert "carry no okl_commit" in _row_commit_problems("r", {"rows": [{"id": "t1"}], "run_commits": []})[0]
    assert "does not list" in _row_commit_problems("r", {**good, "run_commits": ["other"]})[0]


def test_every_new_receipt_with_rows_says_what_each_row_ran():
    """A receipt's okl_commit is the scoring process's; one scored after its run, in another process, cannot
    show what its sessions ran unless each row carries its own commit (#479, §4bj's first receipt)."""
    results = REPO / "evals" / "results"
    receipts = sorted(results.glob("*.json"))
    assert len(receipts) > 50
    problems = []
    for p in receipts:
        m = _STAMP.search(p.name)
        if m and m.group(1) > ROWS_COMMIT_FROM:
            problems += _row_commit_problems(p.name, __import__("json").loads(p.read_text()))
    assert problems == []



# --- an eval script does nothing on import (#486) ---------------------------------------------------

# Calls that open a store, read the command line, write a file or start a process: at the top level of a
# script they ran whenever anything imported it. make_heldout_tasks rewrote a committed file on import,
# the grids opened the working directory's store, and probe_rephrase parsed its importer's argv.
_SIDE_EFFECTS = {"Client", "Store", "_local_store", "load_config", "parse_args", "write_text", "write_bytes",
                 "mkdir", "unlink", "rmtree", "run", "Popen", "check_output", "print", "clean_env"}
# Import-time work that reads and writes nothing, kept on purpose: (script, name it assigns): why.
_IMPORT_TIME_ALLOWED = {("pick_fix.py", "COMMIT"): "reads HEAD once with git rev-parse to stamp its rows"}


def _import_time_work(tree: ast.Module, name: str = "") -> list[int]:
    """Lines of top-level statements that do work when the module is imported, outside its __main__ block.
    Typing-only blocks and loading a sibling module (`exec_module`, an import by another name) are not work."""
    bad = []
    for n in tree.body:
        if isinstance(n, ast.If) and ("__name__" in ast.unparse(n.test) or ast.unparse(n.test) == "TYPE_CHECKING"):
            continue
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and _dotted(n.value.func).endswith("exec_module"):
            continue
        targets = n.targets if isinstance(n, ast.Assign) else [n.target] if isinstance(n, ast.AnnAssign) else []
        if any((name, getattr(t, "id", "")) in _IMPORT_TIME_ALLOWED for t in targets):
            continue
        if isinstance(n, (ast.For, ast.While, ast.With, ast.Try, ast.If)) or isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) and "sys.path" not in ast.unparse(n.value.func) or isinstance(n, (ast.Assign, ast.AnnAssign)) and n.value is not None and any(
                isinstance(c, ast.Call) and _dotted(c.func).rsplit(".", 1)[-1] in _SIDE_EFFECTS
                for c in ast.walk(n.value)):
            bad.append(n.lineno)
    return bad


def test_no_eval_script_does_work_when_imported():
    """Every script's work is in main(), behind `if __name__ == "__main__"`; the top level only defines."""
    found = {p.name: lines for p in sorted((REPO / "evals").glob("*.py"))
             if (lines := _import_time_work(ast.parse(p.read_text()), p.name))}
    assert len(list((REPO / "evals").glob("*.py"))) > 50
    assert found == {}, found


def test_the_import_check_finds_what_it_is_for():
    """A top-level print, a store opened in an assignment, and a loop are found; definitions, constants, a
    sys.path line and a guarded main are not."""
    bad = ast.parse("import sys\nsys.path.insert(0, 'src')\nprint('x')\nstore = Client()._local_store()\n"
                    "for i in range(2):\n    pass\n")
    good = ast.parse("import sys\nREPO = 'okl'\nX = frozenset({1})\nif TYPE_CHECKING:\n    import y\n"
                     "def main():\n    print(1)\nif __name__ == '__main__':\n    sys.exit(main())\n")
    assert _import_time_work(bad) == [3, 4, 5] and _import_time_work(good) == []


def test_importing_every_eval_module_does_nothing():
    """Imported in a fresh interpreter, every eval module loads without running, printing or writing, and
    leaves the clean_env mark unset. A module whose optional dependency is not installed is skipped by name."""
    before = subprocess.run(["git", "status", "--porcelain", "--ignored"], cwd=REPO, capture_output=True,
                            text=True).stdout
    code = ("import sys, io, json, importlib, contextlib; sys.path[:0] = ['evals', 'src']; out = io.StringIO()\n"
            "bad, missing = {}, []\n"
            "for p in sorted(__import__('pathlib').Path('evals').glob('*.py')):\n"
            "    try:\n        with contextlib.redirect_stdout(out): importlib.import_module(p.stem)\n"
            "    except ModuleNotFoundError as e:\n        missing.append(e.name)\n"
            "    except BaseException as e:\n        bad[p.stem] = repr(e)[:120]\n"
            "import sandbox\nprint(json.dumps({'used': sandbox.USED, 'bad': bad, 'printed': out.getvalue()[:200]}))")
    # Under a store URL that cannot open: a module that opens a store at import fails here, whether or not
    # the checkout has an okl config (a local one let the grids open the live store silently; CI on #489).
    env = {**__import__("os").environ, "OKL_DATABASE_URL": "sqlite:////nonexistent-okl-import-check/okl.db",
           "PYTHONDONTWRITEBYTECODE": "1"}     # imports here must not leave __pycache__ in the checkout
    got = subprocess.run([sys.executable, "-c", code], cwd=REPO, capture_output=True, text=True, timeout=300, env=env)
    result = __import__("json").loads(got.stdout.strip().splitlines()[-1])
    assert result == {"used": False, "bad": {}, "printed": ""}, got.stderr[-600:]
    after = subprocess.run(["git", "status", "--porcelain", "--ignored"], cwd=REPO, capture_output=True,
                           text=True).stdout
    assert after == before
