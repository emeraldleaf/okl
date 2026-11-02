"""`okl review`: the opt-in model review of the lessons nothing re-checks (#315, REPORT §4ai)."""
import importlib.util
import json
import os
import shlex
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from okl import review
from okl.cli.parser import build_parser
from okl.store import Node

ROOT = Path(__file__).resolve().parents[1]

# A judge that answers by the lesson's title, and notes what it could see from where it ran.
FAKE_JUDGE = r'''
import json, os, sys
prompt = sys.stdin.read()
seen = {"cwd": os.getcwd(), "drift_json": os.path.exists("okl-drift.json"),
        "uncommitted": os.path.exists("draft.txt"), "committed": os.path.exists("README.md")}
with open(os.environ["JUDGE_LOG"], "a") as f:
    f.write(json.dumps(seen) + "\n")
title = prompt.split("Title: ", 1)[1].split("\n", 1)[0]
if "WRONG" in title:
    answer = {"verdict": "detail wrong", "no_longer": "run make lint", "instead": "the Makefile is gone",
              "evidence": ["README.md:1"], "reason": "the target moved", "checkable": True}
elif "BARE" in title:
    answer = {"verdict": "stale", "reason": "it no longer holds"}      # no quoted words: no answer
else:
    answer = {"verdict": "current", "evidence": [], "reason": "it holds", "checkable": False}
if "PLAIN" in title:
    print("Here is my answer: " + json.dumps(answer))
else:
    print(json.dumps({"type": "result", "result": "Reading done. " + json.dumps(answer)}))
'''


def _repo(tmp_path: Path) -> Path:
    """A committed git repository, with one uncommitted file the judge must not see."""
    repo = tmp_path / "repo"; repo.mkdir()
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True)
    (repo / "README.md").write_text("# demo\n"); (repo / "okl-drift.json").write_text("{}\n")
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True)
    (repo / "draft.txt").write_text("not committed\n")
    return repo


def _okl(tmp_path: Path, repo: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """Run the CLI in `repo` against a throwaway store, with the fake judge's log beside it."""
    env = {k: v for k, v in os.environ.items() if k not in ("OKL_SERVICE_URL", "OKL_TOKEN")}
    env["OKL_DATABASE_URL"] = f"sqlite:///{tmp_path / 'store.db'}"
    env["PYTHONPATH"] = str(ROOT / "src")
    env["JUDGE_LOG"] = str(tmp_path / "judge.log")
    return subprocess.run([sys.executable, "-m", "okl", *args], cwd=repo, env=env, capture_output=True,
                          text=True, input=stdin)


def _judge_cmd(tmp_path: Path) -> str:
    script = tmp_path / "judge.py"; script.write_text(FAKE_JUDGE)
    return shlex.join([sys.executable, str(script)])


def _record(tmp_path, repo, id, title, *extra):
    r = _okl(tmp_path, repo, "record", "--type", "Rule", "--scope", "org", "--id", id, "--title", title,
             "--fix", "do the thing", *extra)
    assert r.returncode == 0, r.stdout + r.stderr


def _judged(tmp_path):
    log = tmp_path / "judge.log"
    return [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []


def test_the_review_is_the_one_4ai_measured():
    """The shipped prompt and default judge are the instrument's, so the help's catch rates are
    this command's own; a change to either is a new instrument (REPORT §4ai)."""
    spec = importlib.util.spec_from_file_location("lesson_census", ROOT / "evals" / "lesson_census.py")
    lc = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("lesson_census", lc)
    spec.loader.exec_module(lc)
    assert review.PROMPT == lc.JUDGE_PROMPT_4AI
    assert review.JUDGE == lc.JUDGE
    assert review.VERDICTS == lc.VERDICTS_4AI and review.QUESTIONED == lc.QUESTIONED
    assert review.TIMEOUT == lc.TIMEOUT


def test_the_help_quotes_the_receipts_catch_rates():
    """Every figure the help and the report quote is recomputed from §4ai's receipt."""
    s = json.loads((ROOT / "evals" / "results" / review.MEASURED["receipt"]).read_text())["summary"]
    assert review.MEASURED["planted"] == (s["planted_caught"]["caught"], s["planted_caught"]["of"])
    assert review.MEASURED["over_called"] == (s["negatives_over_called"]["over"], s["negatives_over_called"]["of"])
    assert review.MEASURED["outlived"] == (s["outlived_caught"]["caught"], s["outlived_caught"]["of"])
    sub = next(a for a in build_parser()._actions if hasattr(a, "choices") and isinstance(a.choices, dict))
    described = " ".join(sub.choices["review"].description.split())
    planted, over = review.MEASURED["planted"], review.MEASURED["over_called"]
    assert f"caught {planted[0]} of {planted[1]} planted wrong details" in described
    assert f"questioned {over[0]} of {over[1]} lessons known to be current" in described


def test_it_judges_only_the_lessons_nothing_re_checks():
    """Own, live advice lessons with no governed files and no observed check: the ones the
    briefing marks UNCHECKED. A bundled pack's, a retired one, a declaration, one with files
    (drift's) and one a check backs are left out."""
    def node(id, **kw):
        return Node(id=id, type=kw.pop("type", "Rule"), title=id, scope="org", **kw)
    at = int(datetime(2026, 11, 2, 10, 0, tzinfo=UTC).timestamp() * 1000)
    observed = {"verified_at": at, "verified_by": "`pytest -q` exit 0 @ 2026-11-02T10:00Z"}
    forged = {"verified_at": at, "verified_by": "trust me"}           # a stamp with no evidence is no check
    nodes = [node("mine"), node("claim", type="Claim"), node("forged", **forged),
             node("seed:python-canon:x"), node("gone", status="obsolete"), node("tag", type="Vocabulary"),
             node("watched", files="src/a.py"), node("checked", **observed)]
    assert {n.id for n in review.unchecked(nodes)} == {"mine", "claim", "forged"}


def test_an_answer_that_questions_a_lesson_must_quote_it():
    """A questioning verdict without the words that no longer hold, or what is there instead, is
    no answer; the last valid object wins over braces written before it."""
    full = '{"verdict": "outlived", "no_longer": "until X lands", "instead": "X landed"}'
    assert review.parse("I read {braces} first. " + full)["verdict"] == "outlived"
    assert review.parse('{"verdict": "stale", "no_longer": "x"}') is None
    assert review.parse('{"verdict": "detail wrong", "no_longer": " ", "instead": "y"}') is None
    assert review.parse('{"verdict": "current"}')["verdict"] == "current"
    assert review.parse('{"verdict": "probably"}') is None and review.parse("no json") is None
    assert review._answer(json.dumps({"result": full})) == full
    assert review._answer("plain " + full) == "plain " + full


def test_okl_review_reports_what_no_longer_holds_and_writes_nothing(tmp_path):
    """End to end with a stand-in judge: it reads HEAD in a scratch worktree (not the working
    tree, and with no okl-drift.json), each questioned lesson is reported with its quoted words,
    an incomplete answer counts as no answer, the store is unchanged, and the worktree is gone."""
    repo = _repo(tmp_path)
    _record(tmp_path, repo, "a-wrong", "Lint with make: WRONG now")
    _record(tmp_path, repo, "b-fine", "Keep the README short (PLAIN answer)")
    _record(tmp_path, repo, "c-bare", "A BARE verdict")
    before = _okl(tmp_path, repo, "show", "a-wrong", "--format", "json").stdout

    r = _okl(tmp_path, repo, "review", "--yes", "--judge", _judge_cmd(tmp_path))

    assert r.returncode == 1, r.stdout + r.stderr                 # something was questioned
    assert "[a-wrong] DETAIL WRONG · Lint with make: WRONG now" in r.stdout
    assert 'no longer holds: "run make lint"' in r.stdout and "the repository has: the Makefile is gone" in r.stdout
    assert "3 judged — 1 current, 1 detail wrong, 1 no answer" in r.stdout
    assert "no answer for [c-bare]" in r.stderr
    assert "This is not the judge §4ai measured" in r.stdout
    seen = _judged(tmp_path)
    assert len(seen) == 3
    assert all(s["committed"] and not s["uncommitted"] and not s["drift_json"] for s in seen)
    assert not Path(seen[0]["cwd"]).exists()                       # the scratch worktree was removed
    assert "okl-review-" not in subprocess.run(["git", "-C", str(repo), "worktree", "list"],
                                               capture_output=True, text=True).stdout
    assert _okl(tmp_path, repo, "show", "a-wrong", "--format", "json").stdout == before


def test_okl_review_never_calls_a_model_unasked(tmp_path):
    """Unattended without --yes it refuses, --list judges nothing, a declined prompt runs
    nothing, and a judge not on PATH, or an unknown id, stops before any call."""
    repo = _repo(tmp_path)
    _record(tmp_path, repo, "a-wrong", "Lint with make: WRONG now")
    judge = _judge_cmd(tmp_path)

    refused = _okl(tmp_path, repo, "review", "--judge", judge, stdin="")
    assert refused.returncode == 2 and "pass --yes" in refused.stderr
    listed = _okl(tmp_path, repo, "review", "--list", "--judge", judge)
    assert listed.returncode == 0 and "[a-wrong] Rule · Lint with make: WRONG now" in listed.stdout
    missing = _okl(tmp_path, repo, "review", "--yes", "--judge", "no-such-judge-anywhere --flag")
    assert missing.returncode == 2 and "not on PATH" in missing.stderr
    unknown = _okl(tmp_path, repo, "review", "nope", "--yes", "--judge", judge)
    assert unknown.returncode == 2 and "no lesson with id nope" in unknown.stderr
    assert _judged(tmp_path) == []


def test_okl_review_names_lessons_and_answers_in_json(tmp_path):
    """Named ids are judged whatever their class; --format json carries every verdict; exit 0
    when none is questioned."""
    repo = _repo(tmp_path)
    _record(tmp_path, repo, "b-fine", "Keep the README short")
    _record(tmp_path, repo, "w-files", "Lint with make: WRONG now", "--files", "README.md")

    r = _okl(tmp_path, repo, "review", "b-fine", "--yes", "--format", "json", "--judge", _judge_cmd(tmp_path))

    assert r.returncode == 0, r.stdout + r.stderr
    out = json.loads(r.stdout)
    assert out["measured"] is False and [x["id"] for x in out["lessons"]] == ["b-fine"]
    assert out["lessons"][0]["verdict"] == "current"
    nothing = _okl(tmp_path, repo, "review", "--list")              # w-files is drift's, b-fine is listed
    assert "w-files" not in nothing.stdout and "b-fine" in nothing.stdout
