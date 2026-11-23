"""ci/lesson-review.sh: the review after writing, run on a pull request with any model's CLI.

A stand-in reviewer records each prompt it is given and the folder it ran in, and answers as the
test tells it: a pick, then a verdict per lesson, or a failure."""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from okl.scaffold_cmd import scaffold

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ci" / "lesson-review.sh"

FAKE = r'''
import json, os, sys, tempfile, time
prompt = sys.stdin.read()
if any(k.startswith("OKL_") for k in os.environ):
    open(os.path.join(os.environ["CALLS_DIR"], "okl-env-seen"), "w").write(" ".join(sorted(os.environ)))
fd, path = tempfile.mkstemp(dir=os.environ["CALLS_DIR"], prefix="call-", suffix=".txt")
with os.fdopen(fd, "w") as f:
    f.write(os.getcwd() + "\n" + prompt)
if "--- THE LESSONS, ONE LINE EACH ---" in prompt:
    print(os.environ.get("PICK_REPLY") or json.dumps({"explanation": ["it adds a line to a.py"],
                                                      "picked": json.loads(os.environ["PICKED"])}))
    sys.exit(0)
lesson = prompt.split("--- END OF THE LESSON ---")[0]
for lid, verdict in json.loads(os.environ.get("VERDICTS", "{}")).items():
    if "[%s]" % lid in lesson:
        if verdict == "FAIL":
            sys.stderr.write("Error: rate limited\n")
            sys.exit(3)
        if verdict == "SLEEP":
            time.sleep(float(os.environ.get("SLEEP_SECONDS", "60")))
        quoted = 'Asked to reply as {"verdict": "breaks or holds or no bearing"}; {not json} either.'
        if verdict == "QUOTE_ONLY":
            print(quoted)
            sys.exit(0)
        if os.environ.get("NOISE"):
            print(quoted)
        print("My answer:\n```json\n" + json.dumps({"paths": [{"path": "a.py", "holds": verdict != "breaks", "why": "w"}],
              "verdict": verdict, "file": "a.py", "line": 2,
              "finding": "finding for %s | cc @someone" % lid}) + "\n```")
        sys.exit(0)
print("I could not decide.")
'''


def _git(repo: Path, *args: str) -> str:
    # The identity per command, never `git config`, and always run in `repo` (lesson
    # probe-cd-fails-into-real-repo: a probe's git writes once landed in the real checkout).
    return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", *args],
                          cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def setup(tmp_path):
    """A repository with one committed change, a store of three lessons, okl on PATH as this checkout's
    code, and the stand-in reviewer as REVIEW_CMD."""
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"
    (repo / "ci").mkdir(parents=True)
    shutil.copy(SCRIPT, repo / "ci" / "lesson-review.sh")
    (repo / "a.py").write_text("x = 1\n")
    _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    base = _git(repo, "rev-parse", "HEAD")
    (repo / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\n")
    _git(repo, "commit", "-qam", "change")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    shim = bin_dir / "okl"
    shim.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m okl "$@"\n')
    shim.chmod(0o755)
    fake = tmp_path / "fake_reviewer.py"
    fake.write_text(FAKE)
    calls = tmp_path / "calls"
    calls.mkdir()
    env = {"PATH": f"{bin_dir}:{Path(sys.executable).parent}:/usr/bin:/bin", "HOME": str(tmp_path),
           "PYTHONPATH": str(ROOT / "src"), "OKL_DATABASE_URL": f"sqlite:///{tmp_path / 'store.db'}",
           "OKL_BRIEFING_LOG": "0", "CALLS_DIR": str(calls), "REVIEW_BASE_REF": base,
           "REVIEW_CMD": f"{sys.executable} {fake}", "LESSON_REVIEW_PARALLEL": "1"}
    def record(lid: str, title: str) -> None:
        subprocess.run([sys.executable, "-m", "okl", "record", "--type", "Rule", "--scope", "org", "--tags", "method",
                        "--id", lid, "--title", title, "--fix", f"the fix for {lid}", "--body", "cause: c"],
                       cwd=repo, env=env, check=True, capture_output=True, text=True)

    for lid, title in (("l-alpha", "ALPHA-TITLE: retries need a deadline"),
                       ("l-beta", "BETA-TITLE: a cache key names every input"),
                       ("l-gamma", "GAMMA-TITLE: exit codes are public API")):
        record(lid, title)

    def run(*args: str, **extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(repo / "ci" / "lesson-review.sh"), *args], cwd=repo,
                              env={**env, **extra}, capture_output=True, text=True)

    def prompts() -> list[tuple[str, str]]:
        out = []
        for f in sorted(calls.glob("call-*.txt")):
            cwd, _, prompt = f.read_text().partition("\n")
            out.append((cwd, prompt))
        return out

    return {"repo": repo, "run": run, "prompts": prompts, "tmp": tmp_path, "record": record, "calls": calls,
            "env": env}


def test_the_lesson_review_ships_with_the_kit_and_soft_passes_until_it_is_configured(tmp_path):
    """Installing the kit calls nobody's model: with no REVIEW_CMD, with one not installed, or with no
    okl to read the lessons, the step passes and says why."""
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    script = tmp_path / "ci" / "lesson-review.sh"
    assert script.read_bytes() == SCRIPT.read_bytes(), "the kit must ship the script this repo runs"

    def run(extra: dict[str, str]) -> subprocess.CompletedProcess:
        return subprocess.run(["bash", str(script)], capture_output=True, text=True, cwd=str(tmp_path),
                              env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), **extra})

    r = run({})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "soft pass" in r.stdout
    assert "REVIEW_CMD" in r.stdout
    r = run({"REVIEW_CMD": "definitely-not-installed -p"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "not on PATH" in r.stderr
    r = run({"REVIEW_CMD": "cat"})
    assert r.returncode == 0, r.stdout + r.stderr
    assert "okl is not on PATH" in r.stderr


def test_one_call_picks_and_one_fresh_call_checks_each_picked_lesson(setup):
    """The steps `okl check --change` prints, as a script makes them: the pick sees every lesson and
    the change; each check sees one lesson's full text and the path question, from an empty folder;
    an id the pick invented is left out and named."""
    r = setup["run"](PICKED=json.dumps(["l-alpha", "[l-beta]", "n_invented", "l-alpha"]),
                     VERDICTS=json.dumps({"l-alpha": "breaks", "l-beta": "holds"}),
                     REVIEW_PR_TITLE="TITLE-MARKER", GITHUB_ACTIONS="true", **{"OKL_TOKEN": "stand-in"},
                     REVIEW_REPO_DIR=str(setup["repo"]), GIT_DIR=str(setup["repo"] / ".git"),
                     LESSON_REVIEW_REPORT=str(setup["tmp"] / "report.md"))
    assert r.returncode == 0, r.stdout + r.stderr
    # The model reads PR text, so none of okl's settings or credentials reach it.
    assert not (setup["calls"] / "okl-env-seen").exists()
    calls = setup["prompts"]()
    assert all("git already points at the checkout" in p for _c, p in calls)
    assert len(calls) == 3, [p[:80] for _c, p in calls]           # one pick, two checks
    pick = [p for _c, p in calls if "--- THE LESSONS, ONE LINE EACH ---" in p]
    assert len(pick) == 1
    for marker in ("[l-alpha]", "[l-beta]", "[l-gamma]", "CHANGE-MARKER", "TITLE-MARKER", "a.py"):
        assert marker in pick[0], marker
    checks = [p for _c, p in calls if "--- THE LESSON ---" in p]
    assert len(checks) == 2
    for p in checks:
        lesson = p.split("--- END OF THE LESSON ---")[0]
        assert sum(t in lesson for t in ("ALPHA-TITLE", "BETA-TITLE", "GAMMA-TITLE")) == 1, lesson
        assert "list every path the lesson's rule covers" in p
        assert "CHANGE-MARKER" in p
    for cwd, _p in calls:
        assert not Path(cwd).resolve().is_relative_to(setup["repo"].resolve()), cwd
    report = (setup["tmp"] / "report.md").read_text()
    assert report.startswith("<!-- okl-lesson-review -->")
    assert "2 of the 2 lessons picked from 3 in scope were checked" in report
    assert "| `l-alpha` ALPHA-TITLE: retries need a deadline | **breaks** |" in report
    assert "finding for l-alpha \\| cc @\u200bsomeone (`a.py:2`)" in report     # no column break, no mention
    assert "| `l-beta` BETA-TITLE: a cache key names every input | holds |" in report
    assert "`n_invented`" in report
    assert "GAMMA" not in report.split("<details>")[0]
    assert "::warning file=a.py,line=2,title=lesson review%3A l-alpha::finding for l-alpha" in r.stdout


def test_a_broken_lesson_fails_the_job_only_when_told_to_block(setup):
    """A check in CI has no measured false-alarm rate, so a broken lesson blocks only with
    LESSON_REVIEW_BLOCKING=1, and a lesson with no bearing never does."""
    picks = {"PICKED": json.dumps(["l-alpha"]), "VERDICTS": json.dumps({"l-alpha": "breaks"}), "GITHUB_ACTIONS": "true"}
    r = setup["run"](**picks, LESSON_REVIEW_BLOCKING="1")
    assert r.returncode == 1, r.stdout + r.stderr
    assert "::error file=a.py,line=2,title=lesson review%3A l-alpha::" in r.stdout
    r = setup["run"](**{**picks, "VERDICTS": json.dumps({"l-alpha": "no bearing"})}, LESSON_REVIEW_BLOCKING="1")
    assert r.returncode == 0, r.stdout + r.stderr
    # Blocking, a run that checked none of its lessons did not run: 2, never a pass.
    r = setup["run"](**{**picks, "VERDICTS": json.dumps({"l-alpha": "FAIL"})}, LESSON_REVIEW_BLOCKING="1")
    assert r.returncode == 2, r.stdout + r.stderr


def test_a_check_that_fails_is_named_with_why_and_the_rest_still_report(setup):
    """A failed call and a reply with no verdict each leave a lesson unchecked, named with why: the
    failed call's exit status and last error line, as ci/review-agent.sh keeps them."""
    r = setup["run"](PICKED=json.dumps(["l-alpha", "l-beta", "l-gamma"]),
                     VERDICTS=json.dumps({"l-alpha": "FAIL", "l-beta": "holds"}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 of the 3 lessons picked from 3 in scope were checked" in r.stdout
    assert "- `l-alpha`: it exited 3: Error: rate limited" in r.stdout
    assert "- `l-gamma`: its reply held no verdict" in r.stdout
    assert "| `l-beta`" in r.stdout


@pytest.mark.parametrize("extra,says", [
    ({"PICK_REPLY": "I could not pick."}, "gave no pick"),
    ({"PICKED": json.dumps(["n_invented"])}, "named no lesson in scope"),
])
def test_no_pick_is_no_review_and_says_so(setup, extra, says):
    """A run with no pick has checked nothing: the report and an annotation say so, rather than an
    empty report a reader takes for a clean one."""
    report = setup["tmp"] / "report.md"
    r = setup["run"](**extra, GITHUB_ACTIONS="true", LESSON_REVIEW_REPORT=str(report))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "No review" in r.stdout
    assert says in r.stdout
    assert "::warning title=lesson review::no lesson review" in r.stdout
    assert len(setup["prompts"]()) == 1
    # The report is written, so a comment from an earlier run does not stand as this one's.
    assert says in report.read_text()
    assert setup["run"](**extra, LESSON_REVIEW_BLOCKING="1").returncode == 2


def test_it_reviews_uncommitted_work_as_okl_lists_it_and_nothing_when_nothing_changed(setup):
    """Run on a machine, the change is what okl lists, committed or not; with nothing changed no
    model is called."""
    head = _git(setup["repo"], "rev-parse", "HEAD")
    (setup["repo"] / "a.py").write_text("x = 1\ny = 2\nz = 3  # UNCOMMITTED-MARKER\n")
    (setup["repo"] / "new.py").write_text("NEW-FILE-MARKER = 1\n")          # not added to git yet
    (setup["repo"] / "deps.lock").write_text("LOCKFILE-MARKER\n")          # data: left out
    r = setup["run"](PICKED=json.dumps(["l-gamma"]), VERDICTS=json.dumps({"l-gamma": "holds"}))
    assert r.returncode == 0, r.stdout + r.stderr
    for _c, p in setup["prompts"]():
        assert "UNCOMMITTED-MARKER" in p
        assert "+NEW-FILE-MARKER = 1" in p
        assert "LOCKFILE-MARKER" not in p
    _git(setup["repo"], "checkout", "--", "a.py")
    (setup["repo"] / "new.py").unlink()
    (setup["repo"] / "deps.lock").unlink()
    for f in (setup["tmp"] / "calls").glob("call-*"):
        f.unlink()
    r = setup["run"](REVIEW_BASE_REF=head)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "Nothing changed since" in r.stdout
    assert setup["prompts"]() == []


def test_a_store_okl_cannot_read_is_a_warning_and_no_call(setup):
    """With no store okl can read, nothing is reviewed and the run says so, with no model call."""
    report = setup["tmp"] / "report.md"
    r = setup["run"](OKL_DATABASE_URL="", GITHUB_ACTIONS="true", LESSON_REVIEW_REPORT=str(report))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "okl could not list the change and its lessons" in r.stderr
    assert "::warning title=lesson review::no lesson review: okl could not list" in r.stdout
    assert "No review: okl could not list" in report.read_text()
    assert setup["prompts"]() == []
    assert setup["run"](OKL_DATABASE_URL="", LESSON_REVIEW_BLOCKING="1").returncode == 2


def test_a_shortened_id_resolves_to_the_one_lesson_it_ends_and_an_ambiguous_one_is_left_out(setup):
    """A model echoing `seed:pack:key` back often drops the namespace (lesson
    model-echoed-ids-get-shortened): the one id in scope that ends in it is checked, and one that
    several end in is left out and named, never guessed."""
    setup["record"]("seed:pack:l-delta", "DELTA-TITLE: a lesson from a pack")
    setup["record"]("a:l-dup", "DUP-A-TITLE")
    setup["record"]("b:l-dup", "DUP-B-TITLE")
    r = setup["run"](PICKED=json.dumps(["l-delta", "pack:l-delta", "l-dup"]),
                     VERDICTS=json.dumps({"seed:pack:l-delta": "holds"}))
    assert r.returncode == 0, r.stdout + r.stderr
    checks = [p for _c, p in setup["prompts"]() if "--- THE LESSON ---" in p]
    assert len(checks) == 1
    assert "DELTA-TITLE" in checks[0]
    assert "| `seed:pack:l-delta` DELTA-TITLE: a lesson from a pack | holds |" in r.stdout
    assert "left out: `l-dup`" in r.stdout


def test_a_verdict_is_found_past_prose_stray_braces_and_a_quoted_format_and_a_reply_without_one_is_flagged(setup):
    """The last object with a verdict is the verdict; the format quoted back is not one. A lesson whose
    reply holds none is an annotation on the pull request, not only a line in the report (lesson
    model-reply-parse-fails-open-loudly)."""
    r = setup["run"](PICKED=json.dumps(["l-alpha", "l-beta"]), NOISE="1", GITHUB_ACTIONS="true",
                     VERDICTS=json.dumps({"l-alpha": "breaks", "l-beta": "QUOTE_ONLY"}))
    assert r.returncode == 0, r.stdout + r.stderr
    assert "| `l-alpha` ALPHA-TITLE: retries need a deadline | **breaks** |" in r.stdout
    assert "- `l-beta`: its reply held no verdict" in r.stdout
    assert "::warning title=lesson review%3A l-beta not checked::its reply held no verdict" in r.stdout


def test_the_run_deadline_stops_a_slow_call_and_the_report_is_still_written(setup):
    """Each call's own timeout does not bound the run, and a CI step stopped by its host writes no
    report (lesson remote-timeout-not-a-deadline): past LESSON_REVIEW_DEADLINE the running call is
    stopped and none starts, and the report says which lessons that left unchecked."""
    report = setup["tmp"] / "report.md"
    began = time.monotonic()
    r = setup["run"](PICKED=json.dumps(["l-alpha", "l-beta"]), LESSON_REVIEW_DEADLINE="8",
                     VERDICTS=json.dumps({"l-alpha": "SLEEP", "l-beta": "holds"}), LESSON_REVIEW_REPORT=str(report))
    assert r.returncode == 0, r.stdout + r.stderr
    assert time.monotonic() - began < 40, "the slow call ran past the run's deadline"
    text = report.read_text()
    assert re.search(r"- `l-alpha`: it ran past \d+s, the run's deadline", text), text
    assert "- `l-beta`: the run's deadline (LESSON_REVIEW_DEADLINE, 8s) passed before it started" in text


def test_the_documented_defaults_and_the_ci_deadline_match_the_script():
    """The numbers the docs give for the lesson review are the script's defaults, and okl's CI sets
    the run's deadline under its step's timeout (lesson doc-claim-governs-doc-and-code)."""
    script = SCRIPT.read_text()
    default = {name: int(v) for name, v in re.findall(r'number\("([A-Z_]+)", (\d+)\)', script)}
    words = {4: "four", 10: "ten", 11: "eleven"}

    def flat(path: str) -> str:
        return " ".join((ROOT / path).read_text().replace("*", "").split())

    rows = {m[0]: m[1] for m in re.findall(r"^\| `([A-Z_]+)` \| `ci/lesson-review\.sh` \| (.*)$",
                                           (ROOT / "docs" / "SCAFFOLD.md").read_text(), re.M)}
    for name in ("LESSON_REVIEW_PICK", "LESSON_REVIEW_PARALLEL", "LESSON_REVIEW_TIMEOUT", "REVIEW_MAX_LINES"):
        assert f"{default[name]:,} unless set" in rows[name], (name, rows.get(name))
    before_push = int(re.search(r'LESSON_REVIEW_DEADLINE="\$\{LESSON_REVIEW_DEADLINE:-(\d+)\}"', script)[1])
    assert default["LESSON_REVIEW_DEADLINE"] == 0 and "none unless set" in rows["LESSON_REVIEW_DEADLINE"]
    assert f"{before_push} with `--before-push`" in rows["LESSON_REVIEW_DEADLINE"], rows["LESSON_REVIEW_DEADLINE"]
    pick, calls, parallel = (words[default["LESSON_REVIEW_PICK"]], words[default["LESSON_REVIEW_PICK"] + 1],
                             words[default["LESSON_REVIEW_PARALLEL"]])
    costs = flat("docs/COSTS-AND-KNOBS.md")
    section = costs.split("## Lesson review before a push")[1].split("## ")[0]
    assert f"stops after {before_push} seconds" in section and f"{pick} unless `LESSON_REVIEW_PICK`" in section
    assert f"about {calls} calls" in section
    assert f"picks the {pick} lessons" in costs and f"{calls} model calls a run, {parallel} at a time" in costs
    manifest = flat("src/okl/scaffold/MANIFEST.md")
    assert f"picks the {pick} lessons" in manifest and f"{calls.capitalize()} calls a run" in manifest
    assert f"pick the {pick} lessons" in flat("README.md")
    step = (ROOT / ".github" / "workflows" / "ci.yml").read_text().split("      - name: Lesson review\n", 1)[1]
    step = step.split("\n      - ", 1)[0]
    minutes = int(re.search(r"timeout-minutes: (\d+)", step)[1])
    deadline = int(re.search(r'LESSON_REVIEW_DEADLINE: "(\d+)"', step)[1])
    assert deadline <= minutes * 60 - 120, "the run's deadline must leave the step time to write the report"


# --- before a push ---------------------------------------------------------------------------------
BREAKS = {"PICKED": '["l-alpha", "l-beta"]', "VERDICTS": '{"l-alpha": "breaks", "l-beta": "holds"}'}
CLEAN = {"PICKED": '["l-alpha", "l-beta"]', "VERDICTS": '{"l-alpha": "holds", "l-beta": "no bearing"}'}
HOLD = {"LESSON_REVIEW_HOLD": "1"}      # in the foreground, holding the push: what "review_before_push": "hold" asks for


def _state(setup) -> Path:
    return setup["repo"] / ".git" / "okl-lesson-review"


def _forget(setup) -> None:
    """Drop what the review remembers, so the next push is a branch's first again."""
    shutil.rmtree(_state(setup), ignore_errors=True)


def _commit(setup, line: str) -> None:
    path = setup["repo"] / "a.py"
    path.write_text(path.read_text() + line + "\n")
    _git(setup["repo"], "commit", "-qam", f"add {line}")


def _wait(what, seconds: float = 30.0):
    """The first truthy answer of `what()`, asked until `seconds` pass: a review in the background
    ends on its own time."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        got = what()
        if got:
            return got
        time.sleep(0.1)
    raise AssertionError("the background review did not finish in time")


def _okl_set_up(setup) -> Path:
    """Give the repo an okl config, as `okl init` does, ignored by git: where a report nobody has
    read is left."""
    folder = setup["repo"] / ".okl"
    folder.mkdir(exist_ok=True)
    (folder / "config.json").write_text(json.dumps({"repo": "repo"}))
    (folder / ".gitignore").write_text("*\n")
    return folder


def test_before_a_push_a_broken_lesson_holds_the_change_once(setup):
    """The review where the work is. A session's Stop hook asks for it once, and a session that opened
    five pull requests ran it for none; a push is once per change. `--before-push` reviews the change,
    exits 1 when a lesson is reported broken, and remembers the change: pushed again as it is, it is
    not reviewed or held a second time, so a false alarm costs one push and no flag."""
    held = setup["run"]("--before-push", **HOLD, **BREAKS)
    assert held.returncode == 1, held.stdout + held.stderr
    assert "**breaks**" in held.stdout and "1 lesson(s) reported broken (above), so this push is held" in held.stderr
    assert "push again as it is" in held.stderr and "--no-verify" in held.stderr
    assert "stops after 480 seconds" in held.stderr, "bounded by default, so the push returns"
    calls = len(setup["prompts"]())
    assert calls == 3, "one pick and one call per picked lesson"
    again = setup["run"]("--before-push", **HOLD, **BREAKS)
    assert again.returncode == 0 and len(setup["prompts"]()) == calls, again.stdout + again.stderr
    assert "This change was reviewed" in again.stdout and "1 broken" in again.stdout and "`l-alpha`" in again.stdout
    assert "reviewed once" in again.stdout
    # What it remembers is in the repository's own git directory, never the work tree: the change, and its branch.
    assert _git(setup["repo"], "status", "--porcelain") == ""
    assert sorted(f.name[:7] for f in _state(setup).glob("*.json") if f.name.startswith("branch-")) == ["branch-"]
    assert len([f for f in _state(setup).glob("*.json") if not f.name.startswith("branch-")]) == 1
    assert not list(_state(setup).glob("*.running")), "nothing is left saying a review is under way"


def test_a_branch_is_reviewed_in_full_once_and_then_only_what_was_broken(setup):
    """A full review on every push was eleven calls a push, and a branch pushed five times paid for
    five. The first push of a branch is reviewed in full. A later push of it checks again only the
    lessons that review reported broken, with no call to pick: one call while a lesson is still
    broken, none once nothing is. Another branch starts again with a full review."""
    assert setup["run"]("--before-push", **HOLD, **BREAKS).returncode == 1
    assert len(setup["prompts"]()) == 3, "the first push: one pick and one call per picked lesson"
    # The same change in a worktree of the repo is the same change: what was remembered is shared.
    wt = setup["tmp"] / "wt"
    _git(setup["repo"], "worktree", "add", "-q", "--detach", str(wt))
    r = subprocess.run(["bash", str(wt / "ci" / "lesson-review.sh"), "--before-push"], cwd=wt,
                       env={**setup["env"], **HOLD, **BREAKS}, capture_output=True, text=True)
    assert r.returncode == 0 and "This change was reviewed" in r.stdout and len(setup["prompts"]()) == 3, r.stdout + r.stderr
    _commit(setup, "z = 3")
    earlier = {prompt for _, prompt in setup["prompts"]()}
    still = setup["run"]("--before-push", **HOLD, **BREAKS)
    assert still.returncode == 1 and len(setup["prompts"]()) == 4, still.stdout + still.stderr
    assert "THE LESSONS, ONE LINE EACH" not in _new_prompts(setup, earlier), "no pick on a later push"
    assert "[l-alpha]" in _new_prompts(setup, earlier) and "[l-beta]" not in _new_prompts(setup, earlier)
    assert "1 of the 1 lessons this branch's first review reported broken were checked again" in still.stdout
    _commit(setup, "fixed = True")
    fixed = setup["run"]("--before-push", **HOLD, **CLEAN)
    assert fixed.returncode == 0 and len(setup["prompts"]()) == 5 and "0 broken, 1 held" in fixed.stdout, fixed.stdout
    _commit(setup, "later = 1")
    nothing = setup["run"]("--before-push", **HOLD, **BREAKS)
    assert nothing.returncode == 0 and len(setup["prompts"]()) == 5, "nothing left broken: no call at all"
    assert "nothing is left that it reported broken, so this push adds no review" in nothing.stdout
    # Another branch is another piece of work: its first push is reviewed in full.
    _git(setup["repo"], "checkout", "-q", "-b", "another-branch")
    _commit(setup, "other = 2")
    assert setup["run"]("--before-push", **HOLD, **BREAKS).returncode == 1 and len(setup["prompts"]()) == 8


def test_before_a_push_the_review_runs_in_the_background_and_holds_nothing(setup):
    """Held for the review, every push of a new change waited about five minutes. By default the
    push goes at once and the review goes on without it. A report with a broken lesson in it is
    left where it will be read: okl adds it to the agent's next briefing, once, since a report that
    only sat in a file was one no agent read. A clean review leaves nothing to read."""
    inbox = _okl_set_up(setup) / "review-unread.md"
    started = time.monotonic()
    r = setup["run"]("--before-push", **BREAKS)
    assert r.returncode == 0 and "in the background. This push is not held" in r.stderr, r.stdout + r.stderr
    assert time.monotonic() - started < 10, "the push does not wait for the review"
    report = _wait(lambda: (_state(setup) / "last-report.md").is_file() and (_state(setup) / "last-report.md").read_text())
    assert "**breaks**" in report and "l-alpha" in report
    _wait(lambda: inbox.is_file() and not list(_state(setup).glob("*.running")))
    assert len(setup["prompts"]()) == 3
    again = setup["run"]("--before-push", **BREAKS)
    assert again.returncode == 0 and "This change was reviewed" in again.stdout and len(setup["prompts"]()) == 3

    def briefing(*args: str) -> str:
        return subprocess.run([sys.executable, "-m", "okl", "check", *args, "--format", "hook"], cwd=setup["repo"],
                              env=setup["env"], capture_output=True, text=True, check=True).stdout

    assert "lesson review of your last push" not in briefing("--path", "a.py"), "a file's briefing is about the file"
    assert inbox.is_file()
    # The hook's output is one JSON object, and the report is in the context it hands the agent.
    # Printed after the object, it made the output unparseable, and the briefing was lost with it.
    context = json.loads(briefing("--task", "add a retry to the fetch call"))["hookSpecificOutput"]["additionalContext"]
    assert "the lesson review of your last push reported this" in context and "l-alpha" in context and "**breaks**" in context
    again_context = json.loads(briefing("--task", "add a retry to the fetch call"))["hookSpecificOutput"]["additionalContext"]
    assert "lesson review of your last push" not in again_context, "once"
    assert not inbox.exists() and (inbox.parent / "review-last.md").is_file()
    # As plain text, for a person or another agent's hook, it follows the briefing the same way.
    inbox.write_text("a report nobody has read\n")
    plain = subprocess.run([sys.executable, "-m", "okl", "check", "--task", "add a retry"], cwd=setup["repo"],
                           env=setup["env"], capture_output=True, text=True, check=True).stdout
    assert "the lesson review of your last push reported this" in plain and "a report nobody has read" in plain
    assert not inbox.exists()
    # A file's briefing shows no report, in either format, and leaves it for the task briefing that will:
    # it marked the report read all the same, and the report was lost unshown (found by CI's review).
    inbox.write_text("a report nobody has read\n")
    for form in ([], ["--format", "hook"]):
        shown = subprocess.run([sys.executable, "-m", "okl", "check", "--path", "a.py", *form], cwd=setup["repo"],
                               env=setup["env"], capture_output=True, text=True, check=True).stdout
        assert "lesson review of your last push" not in shown and inbox.is_file(), form
    inbox.unlink()
    # Read without marking, and marked only when told: a briefing that fails to print keeps the report.
    from okl.client import mark_review_read, unread_review
    inbox.write_text("a report nobody has read\n")
    old_dir = Path.cwd()
    os.chdir(setup["repo"])
    try:
        assert unread_review() == "a report nobody has read" and unread_review() == "a report nobody has read"
        mark_review_read()
        assert unread_review() is None
    finally:
        os.chdir(old_dir)
    # A clean review has nothing a person or an agent must be told.
    _forget(setup)
    _commit(setup, "clean = 1")
    assert setup["run"]("--before-push", **CLEAN).returncode == 0
    _wait(lambda: any(not f.name.startswith("branch-") for f in _state(setup).glob("*.json"))
          and not list(_state(setup).glob("*.running")))
    assert not inbox.exists()


def test_a_second_push_does_not_start_a_second_review_of_the_same_change(setup):
    """In the background a push returns before its review ends, so the next push can come while it
    runs. It is told so, and starts nothing."""
    slow = {"PICKED": '["l-alpha"]', "VERDICTS": '{"l-alpha": "SLEEP"}', "SLEEP_SECONDS": "3"}
    assert setup["run"]("--before-push", **slow).returncode == 0
    second = setup["run"]("--before-push", **slow)
    assert second.returncode == 0 and "already running" in second.stdout, second.stdout + second.stderr
    _wait(lambda: not list(_state(setup).glob("*.running")) and (_state(setup) / "last-report.md").is_file())
    assert len(setup["prompts"]()) == 2, "one pick and one check: the second push called nobody"
    # A review that was killed is not one under way: the file it left names a process that is gone,
    # and the next push reviews. Counted by the file's age alone, it held every push off for minutes.
    import signal
    _forget(setup)
    _commit(setup, "killed = 1")
    assert setup["run"]("--before-push", **slow).returncode == 0
    (marker,) = _wait(lambda: list(_state(setup).glob("*.running")))
    pid = int(_wait(lambda: marker.read_text().strip()))
    os.kill(pid, signal.SIGKILL)
    _wait(lambda: subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode != 0)
    assert marker.exists(), "killed outright, it removed nothing"
    after = setup["run"]("--before-push", **HOLD, **CLEAN)
    assert after.returncode == 0 and "already running" not in after.stdout and "0 broken" in after.stdout, after.stdout


def test_before_a_push_a_review_that_could_not_run_never_holds_it(setup, tmp_path):
    """An outage of the model must not stop work. No pick, no verdict, no reviewer, or a fault in the
    script itself ends as "did not run" (exit 2, as everywhere in okl), which the hook lets through;
    it says LESSONS NOT REVIEWED so it is not read as clean, and remembers nothing, so the next push
    tries again. Python exits 1 on its own error, which a hook would read as a hold."""
    no_pick = setup["run"]("--before-push", **HOLD, PICK_REPLY="I would rather not say.", PICKED="[]")
    assert no_pick.returncode == 2 and "LESSONS NOT REVIEWED" in no_pick.stderr, no_pick.stdout + no_pick.stderr
    failed = setup["run"]("--before-push", **HOLD, PICKED='["l-alpha"]', VERDICTS='{"l-alpha": "FAIL"}')
    assert failed.returncode == 2 and "LESSONS NOT REVIEWED" in failed.stderr, failed.stdout + failed.stderr
    assert not list(_state(setup).glob("*.json")), "nothing checked, nothing remembered"
    nowhere = str(tmp_path / "no-such-folder" / "report.md")
    fault = setup["run"]("--before-push", **HOLD, LESSON_REVIEW_REPORT=nowhere, **BREAKS)
    assert fault.returncode == 2 and "Traceback" in fault.stderr and "LESSONS NOT REVIEWED" in fault.stderr
    # A reviewer command that is not a command line fails on the line that reads it, the script's first.
    quote = setup["run"]("--before-push", **HOLD, REVIEW_CMD="python3 'unbalanced", **BREAKS)
    assert quote.returncode == 2 and "LESSONS NOT REVIEWED" in quote.stderr, quote.stdout + quote.stderr
    unset = setup["run"]("--before-push", **HOLD, REVIEW_CMD="", **BREAKS)
    assert unset.returncode == 2 and "LESSONS NOT REVIEWED" in unset.stderr and "REVIEW_CMD not set" in unset.stdout
    # The same fault outside a push is the error it is.
    assert setup["run"](LESSON_REVIEW_REPORT=nowhere, **CLEAN).returncode == 1
    # A change whose report was never kept is not remembered as reviewed: it is reviewed, and held, next time.
    assert not list(_state(setup).glob("*.json"))
    assert not list(_state(setup).glob("*.running")), "a review that died is not one under way"
    before = len(setup["prompts"]())
    assert setup["run"]("--before-push", **HOLD, **BREAKS).returncode == 1 and len(setup["prompts"]()) > before


def test_a_review_run_by_hand_counts_for_the_push_and_is_otherwise_unchanged(setup):
    """Without the flag nothing is remembered: CI reviews every push it is given, as before. Asked to
    remember (LESSON_REVIEW_ONCE=1), a review run by hand before the push counts for it, which is how
    an agent whose tool gives a command two minutes gets the review done outside the push."""
    assert setup["run"](**BREAKS).returncode == 0 and setup["run"](**BREAKS).returncode == 0
    assert len(setup["prompts"]()) == 6, "no memory without the flag"
    by_hand = setup["run"](LESSON_REVIEW_ONCE="1", **BREAKS)
    assert by_hand.returncode == 0 and "**breaks**" in by_hand.stdout, "it reports, and holds nothing"
    pushed = setup["run"]("--before-push", **HOLD, **BREAKS)
    assert pushed.returncode == 0 and "This change was reviewed" in pushed.stdout and len(setup["prompts"]()) == 9
    (setup["repo"] / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\nw = 4\n")
    _git(setup["repo"], "commit", "-qam", "another change")
    timed = setup["run"]("--before-push", **HOLD, LESSON_REVIEW_DEADLINE="60", **CLEAN)
    assert timed.returncode == 0 and "stops after 60 seconds" in timed.stderr, timed.stdout + timed.stderr


def _path_without_okl(tmp: Path) -> str:
    """A PATH with python3 and the system's tools and no `okl`, whatever this machine's holds: pip puts
    okl beside python, so python's own folder cannot be on it."""
    bare = tmp / "bare-bin"
    bare.mkdir(exist_ok=True)
    (bare / "python3").write_text(f'#!/bin/sh\nexec {shlex.quote(sys.executable)} "$@"\n')
    (bare / "python3").chmod(0o755)
    path = f"{bare}:/usr/bin:/bin"
    assert shutil.which("okl", path=path) is None and shutil.which("git", path=path), "needs git and no okl"
    return path


def _new_prompts(setup, before: set) -> str:
    """The text of the prompts made since `before` (a set of earlier ones): they are kept in files
    with random names, so their order says nothing about when they were made."""
    return "\n".join(prompt for _, prompt in setup["prompts"]() if prompt not in before)


def test_before_a_push_only_what_is_committed_is_reviewed(setup):
    """A push carries commits. The review after writing reads the work in progress, and read that way
    before a push an uncommitted edit or a scratch file decided whether the push was held and what
    counted as the same change (found by the first real run of this mode, against the lesson that a
    verdict on what ships reads what is committed)."""
    repo = setup["repo"]
    assert setup["run"]("--before-push", **HOLD, **CLEAN).returncode == 0
    calls = len(setup["prompts"]())
    (repo / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\nNOT_COMMITTED = True\n")
    (repo / "scratch.py").write_text("SCRATCH_FILE = 1\n")
    again = setup["run"]("--before-push", **HOLD, **BREAKS)
    assert again.returncode == 0 and "This change was reviewed" in again.stdout and len(setup["prompts"]()) == calls
    _git(repo, "commit", "-qam", "commit the edit, not the scratch file")
    _forget(setup)
    earlier = {prompt for _, prompt in setup["prompts"]()}
    held = setup["run"]("--before-push", **HOLD, **BREAKS)
    assert held.returncode == 1, held.stdout + held.stderr
    seen = _new_prompts(setup, earlier)
    assert "NOT_COMMITTED" in seen and "SCRATCH_FILE" not in seen and "scratch.py" not in seen
    # Outside a push, the same script still reads the work in progress, as the review after writing does.
    earlier = {prompt for _, prompt in setup["prompts"]()}
    assert setup["run"](**CLEAN).returncode == 0
    assert "SCRATCH_FILE" in _new_prompts(setup, earlier)
    # A lesson that governs the scratch file is not put at the head of what the pick reads either: which
    # lessons govern the change is asked of the committed files (found by the mode's third real run).
    setup["record"]("l-scratch", "SCRATCH-TITLE: governs a scratch file")
    subprocess.run([sys.executable, "-m", "okl", "update", "l-scratch", "--files", "scratch.py"], cwd=repo,
                   env=setup["env"], check=True, capture_output=True, text=True)
    (repo / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\nNOT_COMMITTED = True\nmore = 1\n")
    _git(repo, "commit", "-qam", "one more commit")
    _forget(setup)
    earlier = {prompt for _, prompt in setup["prompts"]()}
    setup["run"]("--before-push", **HOLD, **CLEAN)
    pick = next(p for p in _new_prompts(setup, earlier).split("--- END OF THE LESSON ---") if "THE LESSONS, ONE LINE EACH" in p)
    listed = pick.split("THE LESSONS, ONE LINE EACH")[1]
    assert listed.index("[l-alpha]") < listed.index("[l-scratch]"), "id order: the scratch file moved nothing forward"
    earlier = {prompt for _, prompt in setup["prompts"]()}
    setup["run"](**CLEAN)
    listed = next(p for _, p in setup["prompts"]() if p not in earlier and "THE LESSONS, ONE LINE EACH" in p)
    listed = listed.split("THE LESSONS, ONE LINE EACH")[1]
    assert listed.index("[l-scratch]") < listed.index("[l-alpha]"), "outside a push the work in progress counts, as before"
    # Nothing committed since the base: nothing to review, and no model is called.
    before = len(setup["prompts"]())
    nothing = setup["run"]("--before-push", **HOLD, REVIEW_BASE_REF="HEAD", **BREAKS)
    assert nothing.returncode == 0 and "Nothing is committed since" in nothing.stdout and len(setup["prompts"]()) == before


def test_the_reviewer_and_okl_are_read_as_command_lines(setup, tmp_path):
    """A hook runs without the shell's PATH: a GUI git client, an IDE, an agent. The script asked for
    a bare `okl`, so there the review was skipped while the same hook's drift gate, which resolves
    okl in layers, ran (found by the first real run, against the lesson on resolving a CLI from a
    hook). okl is taken as the command line the hook resolved, and a reviewer in a folder with a
    space in its name is no longer "not on PATH", the cut at the first space that #140 was."""
    no_okl = {"PATH": _path_without_okl(tmp_path)}
    skipped = setup["run"]("--before-push", **HOLD, **no_okl, **BREAKS)
    assert skipped.returncode == 2 and "okl is not on PATH" in skipped.stderr and "LESSONS NOT REVIEWED" in skipped.stderr
    assert setup["run"](**no_okl, **BREAKS).returncode == 0, "outside a push it passes softly, as before"
    assert setup["prompts"]() == []
    resolved = setup["run"]("--before-push", **HOLD, LESSON_REVIEW_OKL=f"{shlex.quote(sys.executable)} -m okl", **no_okl, **BREAKS)
    assert resolved.returncode == 1 and len(setup["prompts"]()) == 3, resolved.stdout + resolved.stderr
    spaced = tmp_path / "my tools"; spaced.mkdir()
    reviewer = spaced / "reviewer"
    reviewer.write_text(f"#!/bin/sh\nexec {shlex.quote(sys.executable)} {shlex.quote(str(setup['tmp'] / 'fake_reviewer.py'))}\n")
    reviewer.chmod(0o755)
    (setup["repo"] / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\nq = 9\n")
    _git(setup["repo"], "commit", "-qam", "another change")
    _forget(setup)
    r = setup["run"]("--before-push", **HOLD, REVIEW_CMD=shlex.quote(str(reviewer)), **BREAKS)
    assert r.returncode == 1 and len(setup["prompts"]()) == 6, r.stdout + r.stderr


def _older_git(tmp: Path) -> str:
    """A PATH whose git answers as git 2.30 does: it prints an option it does not know, here
    --path-format, back as a line of its answer, then answers the rest."""
    folder = tmp / "older-git"
    folder.mkdir(exist_ok=True)
    (folder / "git").write_text(
        "#!/bin/sh\n"
        'for a in "$@"; do case "$a" in --path-format=*) echo "$a";; esac; done\n'
        'n=$#; i=0\n'
        'while [ $i -lt $n ]; do a=$1; shift; i=$((i+1)); case "$a" in --path-format=*) ;; *) set -- "$@" "$a";; esac; done\n'
        f'exec {shlex.quote(shutil.which("git"))} "$@"\n')
    (folder / "git").chmod(0o755)
    return f"{folder}:{os.environ['PATH']}"


def test_the_review_keeps_its_state_in_the_git_directory_under_an_older_git(setup):
    """Found by running it for real: the first git on the machine was 2.30, which does not know
    `--path-format` and prints it back, so three real reviews kept what they remembered in a folder
    named after the option, in the work tree, and none was ever found again. The suite's git was
    newer, so it passed. Under a git that answers the old way, the state is in the git directory, a
    change is remembered, and a worktree's push finds the repo's settings."""
    path = _older_git(setup["tmp"])
    probe = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], cwd=setup["repo"],
                           env={**setup["env"], "PATH": path}, capture_output=True, text=True).stdout
    assert probe.startswith("--path-format=absolute\n"), "the stand-in must answer as the older git does"
    held = setup["run"]("--before-push", **HOLD, **BREAKS, PATH=f"{setup['tmp'] / 'bin'}:{path}")
    assert held.returncode == 1, held.stdout + held.stderr
    assert len([f for f in _state(setup).glob("*.json")]) == 2, "the change and its branch, in .git"
    assert not [f for f in setup["repo"].iterdir() if f.name.startswith("--path-format")], "nothing in the work tree"
    again = setup["run"]("--before-push", **HOLD, **BREAKS, PATH=f"{setup['tmp'] / 'bin'}:{path}")
    assert again.returncode == 0 and "This change was reviewed" in again.stdout
    # git's hook, in a worktree of the repo: the settings are the main checkout's, found without the option.
    push, pushed = _hooked(setup)
    _forget(setup)
    wt = setup["tmp"] / "pushed-from-a-worktree"
    _git(setup["repo"], "worktree", "add", "-q", "-b", "in-a-worktree", str(wt))
    (wt / "a.py").write_text((wt / "a.py").read_text() + "from_worktree = 1\n")
    _git(wt, "commit", "-qam", "a change made in a worktree")
    env = {**setup["env"], **BREAKS, "OKL_BIN": f"{sys.executable} -m okl", "PATH": f"{setup['tmp'] / 'bin'}:{path}"}
    env.pop("REVIEW_CMD")
    r = subprocess.run(["git", "push", "-q", "origin", "HEAD:refs/heads/from-worktree"], cwd=wt, env=env,
                       capture_output=True, text=True)
    assert r.returncode != 0 and "so this push is held" in r.stdout + r.stderr, r.stdout + r.stderr


def _hooked(setup, review: bool | str = "hold", cmd: bool = True):
    """The setup's repo with a remote to push to, okl's pre-push hook where git runs it, and the
    repo's config asking for the review: "hold" to hold the push for it, True for the default, in
    the background. Returns a `push` that goes through git."""
    repo, env = setup["repo"], dict(setup["env"])
    remote = setup["tmp"] / "remote.git"
    if not remote.exists():
        subprocess.run(["git", "init", "-q", "--bare", str(remote)], check=True, capture_output=True)
        _git(repo, "remote", "add", "origin", str(remote))
        hook = repo / ".git" / "hooks" / "pre-push"
        shutil.copy(ROOT / "src" / "okl" / "scaffold" / "git-hooks" / "pre-push", hook)
        hook.chmod(0o755)
    config = {"repo": "r", "review_before_push": review}
    if cmd:
        config["review_cmd"] = env["REVIEW_CMD"]
    (repo / ".okl").mkdir(exist_ok=True)
    (repo / ".okl" / "config.json").write_text(json.dumps(config))
    (repo / ".okl" / ".gitignore").write_text("*\n")
    env.pop("REVIEW_CMD")          # the hook reads the reviewer from the config
    env["OKL_BIN"] = f"{sys.executable} -m okl"

    def push(**extra: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", "-c", "user.email=t@example.invalid", "-c", "user.name=t", "push", "-q",
                               "origin", "HEAD:main"], cwd=repo, env={**env, **extra}, capture_output=True, text=True)

    def pushed() -> bool:
        there = subprocess.run(["git", "--git-dir", str(remote), "rev-parse", "-q", "--verify", "refs/heads/main"],
                               capture_output=True, text=True).stdout.strip()
        return there == _git(repo, "rev-parse", "HEAD")

    return push, pushed


def test_gits_pre_push_hook_runs_the_review_where_the_repo_asks_for_it(setup):
    """Through git itself, asked to hold ("review_before_push": "hold"): a push whose change breaks a
    lesson is refused and nothing reaches the remote; pushed again it goes, without a second review.
    A commit on top checks that lesson again, and goes when it holds. The hook reads the reviewer
    from the config."""
    push, pushed = _hooked(setup)
    held = push(**BREAKS)
    said = held.stdout + held.stderr
    assert held.returncode != 0 and "so this push is held" in said and "**breaks**" in said, said
    assert not pushed() and len(setup["prompts"]()) == 3
    again = push(**BREAKS)
    assert again.returncode == 0 and pushed() and len(setup["prompts"]()) == 3, again.stdout + again.stderr
    (setup["repo"] / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\nz = 3\n")
    _git(setup["repo"], "commit", "-qam", "more")
    clean = push(**CLEAN)
    assert clean.returncode == 0 and pushed() and len(setup["prompts"]()) == 4, clean.stdout + clean.stderr
    # The hook hands the script the okl it resolved (OKL_BIN here), so the review runs where no `okl` is on PATH.
    (setup["repo"] / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\nz = 3\nk = 5\n")
    _git(setup["repo"], "commit", "-qam", "more again")
    _forget(setup)
    bare = push(PATH=_path_without_okl(setup["tmp"]), **BREAKS)
    assert bare.returncode != 0 and not pushed() and len(setup["prompts"]()) == 7, bare.stdout + bare.stderr


def test_gits_pre_push_hook_reviews_in_the_background_and_shows_the_report_at_the_next_push(setup):
    """The default ("review_before_push": true). The push reaches the remote at once, whatever the
    review will say. The report with the broken lesson is printed at the next push, once, for a
    person at a terminal; an agent gets it from okl's next briefing when that comes first."""
    push, pushed = _hooked(setup, review=True)
    inbox = setup["repo"] / ".okl" / "review-unread.md"
    first = push(**BREAKS)
    assert first.returncode == 0 and pushed(), first.stdout + first.stderr
    assert "in the background. This push is not held" in first.stderr
    _wait(lambda: inbox.is_file() and not list(_state(setup).glob("*.running")))
    assert len(setup["prompts"]()) == 3
    _commit(setup, "next = 1")
    second = push(**CLEAN)
    assert second.returncode == 0 and pushed(), second.stdout + second.stderr
    assert "the lesson review of your last push reported:" in second.stderr and "**breaks**" in second.stderr
    assert "l-alpha" in second.stderr and not inbox.exists() and (inbox.parent / "review-last.md").is_file()
    _wait(lambda: not list(_state(setup).glob("*.running")) and len(setup["prompts"]()) == 4)
    _commit(setup, "third = 1")
    third = push(**CLEAN)
    assert third.returncode == 0 and "of your last push reported" not in third.stderr, "shown once"


def test_gits_pre_push_hook_reviews_nothing_unless_asked_and_never_blocks_on_setup(setup):
    """Off by default: it calls a model about eleven times and takes minutes. One push can turn it on
    or off (OKL_REVIEW_BEFORE_PUSH). Asked for with no reviewer named, or with the script not in the
    repo, it says LESSONS NOT REVIEWED and the push goes."""
    push, pushed = _hooked(setup, review=False)
    assert push(**BREAKS).returncode == 0 and pushed() and setup["prompts"]() == [], "off: no model is called"

    def commit(n: int) -> None:
        (setup["repo"] / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\n" + "".join(f"v{i} = {i}\n" for i in range(n)))
        _git(setup["repo"], "commit", "-qam", f"change {n}")

    commit(1)
    forced = push(OKL_REVIEW_BEFORE_PUSH="hold", **BREAKS)
    assert forced.returncode != 0 and not pushed() and len(setup["prompts"]()) == 3, forced.stdout + forced.stderr
    push, pushed = _hooked(setup)
    commit(2)
    assert push(OKL_REVIEW_BEFORE_PUSH="0", **BREAKS).returncode == 0 and pushed() and len(setup["prompts"]()) == 3
    push, pushed = _hooked(setup, cmd=False)
    commit(3)
    unnamed = push(**BREAKS)
    assert unnamed.returncode == 0 and pushed() and "LESSONS NOT REVIEWED" in unnamed.stderr and "review_cmd" in unnamed.stderr
    # A copy of the script from before this mode would run a plain review, with nothing remembered,
    # held or timed: the kit never replaces a copy the repo has. The hook says so and pushes.
    push, pushed = _hooked(setup)
    real = (setup["repo"] / "ci" / "lesson-review.sh").read_text()
    (setup["repo"] / "ci" / "lesson-review.sh").write_text(real.replace("--before-push", "--some-older-flag"))
    _git(setup["repo"], "commit", "-qam", "an older review script")
    older = push(**BREAKS)
    assert older.returncode == 0 and pushed() and "from before the review" in older.stderr and "okl scaffold --force" in older.stderr
    assert len(setup["prompts"]()) == 3
    (setup["repo"] / "ci" / "lesson-review.sh").write_text(real)
    _git(setup["repo"], "commit", "-qam", "the current review script")
    # A push of some other commit than the checked-out one is not this change: not reviewed, and pushed.
    side = _git(setup["repo"], "commit-tree", "HEAD^{tree}", "-p", "HEAD", "-m", "another branch's commit")
    other = subprocess.run(["git", "push", "-q", "origin", f"{side}:refs/heads/side"], cwd=setup["repo"],
                           env={**setup["env"], **BREAKS, "OKL_BIN": f"{sys.executable} -m okl"}, capture_output=True, text=True)
    assert other.returncode == 0 and "not of the checked-out commit" in other.stderr and len(setup["prompts"]()) == 3
    # A git client's PATH with no python3: the setting is still read, and the review, which needs
    # python3, says it did not run. Read with python3 alone, the setting was silently off there.
    bare = setup["tmp"] / "no-python"; bare.mkdir()
    for tool in ("bash", "git", "sed", "grep", "awk", "cat", "dirname"):
        (bare / tool).symlink_to(shutil.which(tool))
    config = setup["repo"] / ".okl" / "config.json"
    config.write_text(json.dumps(json.loads(config.read_text()), indent=2) + "\n")      # a key a line, as okl writes it
    (setup["repo"] / "a.py").write_text("x = 1\ny = 2  # CHANGE-MARKER\nno_python = 1\n")
    _git(setup["repo"], "commit", "-qam", "pushed from a client with no python3")
    quiet = push(PATH=str(bare), **BREAKS)
    assert quiet.returncode == 0 and pushed(), quiet.stdout + quiet.stderr
    assert "python3 is not on PATH" in quiet.stderr and "LESSONS NOT REVIEWED" in quiet.stderr, quiet.stderr
    # A review script that dies of something else (exit 3 here) is not a held push: only its exit 1 is.
    push, pushed = _hooked(setup, review=True)
    (setup["repo"] / "ci" / "lesson-review.sh").write_text("#!/usr/bin/env bash\n# --before-push\nexit 3\n")
    _git(setup["repo"], "commit", "-qam", "a review script that dies")
    assert push(**BREAKS).returncode == 0 and pushed()
    (setup["repo"] / "ci" / "lesson-review.sh").write_text(real)
    _git(setup["repo"], "commit", "-qam", "the review script again")
    push, pushed = _hooked(setup)
    (setup["repo"] / "ci" / "lesson-review.sh").rename(setup["repo"] / "ci" / "moved.sh")
    _git(setup["repo"], "add", "-A"); _git(setup["repo"], "commit", "-qm", "the script is gone")
    gone = push(**BREAKS)
    assert gone.returncode == 0 and pushed() and "LESSONS NOT REVIEWED" in gone.stderr and "okl scaffold" in gone.stderr
    assert len(setup["prompts"]()) == 3


def test_init_says_when_the_review_before_a_push_is_on_and_cannot_run(tmp_path, monkeypatch, capsys):
    """The setting is two lines in a config; what runs it is a hook and a script, each of which okl
    keeps when it is another tool's or an older copy. Each case left the setting on and doing nothing
    until a push went unreviewed (found by the first real run, against the lesson that a feature in an
    okl-owned file must check the copy that is there). init says which, and nothing when all is well
    or the setting is off."""
    from okl.cli import install
    _git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    on = {"review_before_push": True}
    install._say_review_before_push({"review_before_push": "hold"})
    assert "no pre-push hook here runs it" in capsys.readouterr().out, "asked to hold, it is on as well"
    install._say_review_before_push({})
    install._say_review_before_push({"review_before_push": False})
    assert capsys.readouterr().out == "", "off: nothing to say"
    install._say_review_before_push(on)
    said = capsys.readouterr().out
    assert "no pre-push hook here runs it (none is installed" in said
    assert "ci/lesson-review.sh is not in this repo" in said
    hook = tmp_path / ".git" / "hooks" / "pre-push"
    hook.parent.mkdir(exist_ok=True)
    hook.write_text("#!/bin/sh\n# another tool's hook\n")
    (tmp_path / "ci").mkdir()
    (tmp_path / "ci" / "lesson-review.sh").write_text("#!/usr/bin/env bash\n# a copy from before the mode\n")
    install._say_review_before_push(on)
    said = capsys.readouterr().out
    assert "add this line" in said and "bash ci/lesson-review.sh --before-push || [ $? -ne 1 ] || exit 1" in said
    assert "is from before it" in said and "okl scaffold --force" in said
    shutil.copy(ROOT / "src" / "okl" / "scaffold" / "git-hooks" / "pre-push", hook)
    shutil.copy(SCRIPT, tmp_path / "ci" / "lesson-review.sh")
    install._say_review_before_push(on)
    assert capsys.readouterr().out == "", "okl's hook and the current script: nothing to say"
    # The line it gives another tool's hook is the one the docs give.
    costs = " ".join((ROOT / "docs" / "COSTS-AND-KNOBS.md").read_text().split())
    assert install._REVIEW_LINE.replace('"<your reviewer>"', '"..."') in costs


def test_init_wires_the_review_before_a_push_itself(tmp_path, capsys, monkeypatch):
    """`okl init --review-before-push <reviewer>` is the whole setup: it records the setting and the
    reviewer, installs the pre-push hook even where an earlier init chose none, and puts the review
    script in the repo. An init that printed those as steps to take was the lesson it broke on its
    second real run ("init must wire, not instruct"). The dry run lists both files and writes
    neither; a script already in the repo is never replaced; --no-review-before-push turns it off and
    keeps the reviewer."""
    from okl.cli import main
    _git(tmp_path, "init", "-q")
    monkeypatch.chdir(tmp_path)
    base = ["init", "--repo", "r", "--no-claude", "--no-seed", "--no-ci"]
    assert main([*base, "--no-git-hook"]) == 0
    hook, script, config = tmp_path / ".git" / "hooks" / "pre-push", tmp_path / "ci" / "lesson-review.sh", tmp_path / ".okl" / "config.json"
    assert not hook.exists() and json.loads(config.read_text())["git_hook"] is False
    capsys.readouterr()
    assert main([*base, "--review-before-push", "claude -p --model sonnet", "--dry-run"]) == 0
    listed = capsys.readouterr().out
    assert "ci/lesson-review.sh" in listed and "and the review before a push" in listed
    assert not hook.exists() and not script.exists(), "a dry run writes nothing"
    assert main([*base, "--review-before-push", "claude -p --model sonnet"]) == 0
    said = capsys.readouterr().out
    cfg = json.loads(config.read_text())
    assert (cfg["review_before_push"], cfg["review_cmd"], cfg["git_hook"]) == (True, "claude -p --model sonnet", True)
    assert "--before-push" in hook.read_text() and script.read_bytes() == SCRIPT.read_bytes()
    assert script.stat().st_mode & 0o111, "git runs it with bash, and a person runs it by name"
    assert "installed the review script" in said and "review before a push: on, with `claude -p --model sonnet`" in said
    assert "in the background, so no push waits" in said and "--review-holds-push" in said
    assert "! review before a push" not in said, "nothing is left for the person to do"
    script.write_text(script.read_text() + "# edited here\n")
    assert main(base) == 0
    assert script.read_text().endswith("# edited here\n"), "a script already in the repo is kept"
    assert "installed the review script" not in capsys.readouterr().out
    assert main([*base, "--review-holds-push"]) == 0
    assert json.loads(config.read_text())["review_before_push"] == "hold"
    assert "the push waits a few minutes, and a lesson reported broken holds it once" in capsys.readouterr().out
    assert main(base) == 0 and json.loads(config.read_text())["review_before_push"] == "hold", "a plain init keeps it"
    capsys.readouterr()
    assert main([*base, "--no-review-before-push"]) == 0
    cfg = json.loads(config.read_text())
    assert cfg["review_before_push"] is False and cfg["review_cmd"] == "claude -p --model sonnet"
    assert "review before a push: on" not in capsys.readouterr().out


def test_no_doc_says_the_pre_push_hook_holds_a_push_only_for_drift():
    """The hook holds a push for drift and, where turned on, for a lesson the review reports broken.
    Three places kept saying "only when lessons have drifted" after the hook changed, and no check
    tied them to it (found by the mode's second real run). The sentence is gone from every shipped
    text, and the places that say what the hook does name the review."""
    shipped = subprocess.run(["git", "ls-files", "*.md", "src/okl/cli/*.py", "src/okl/scaffold"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split()
    assert len(shipped) > 40
    stale = [f for f in shipped if f != "CHANGELOG.md" and (ROOT / f).is_file() and
             re.search(r"only when (?:okl ran and found drift|lessons (?:have )?drifted)|blocks only on drift",
                       " ".join((ROOT / f).read_text(errors="replace").split()), re.I)]
    assert stale == [], f"these still say drift is the only thing that holds a push: {stale}"
    for path in ("README.md", "docs/GETTING-STARTED.md", "docs/WHAT-INIT-WRITES.md", "docs/COSTS-AND-KNOBS.md",
                 "src/okl/scaffold/MANIFEST.md", "src/okl/scaffold/git-hooks/pre-push", "docs/ARCHITECTURE.md"):
        text = " ".join((ROOT / path).read_text().split())
        assert re.search(r"review before a push|--review-before-push|--before-push|reviews the push", text), path


def test_an_agent_that_asks_over_mcp_is_handed_the_report_once(tmp_path, monkeypatch):
    """An agent with no hooks asks for its briefing with okl_check. A task's briefing carries the
    last push's review, once; a path's carries none and leaves the report unread for the task
    briefing that will show it."""
    pytest.importorskip("mcp")
    import asyncio

    from okl.client import Client
    from okl.mcp_server import _build
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    Client().record(type="Rule", title="retries need a deadline", scope="org", fix="give each retry a deadline")
    inbox = tmp_path / ".okl" / "review-unread.md"
    inbox.write_text("| `l-alpha` | **breaks** | the report nobody has read |\n")

    def text(res) -> str:
        res = res[0] if isinstance(res, tuple) else res        # mcp 1.x: (content blocks, structured result)
        c = getattr(res, "content", res)
        c = c[0] if isinstance(c, list | tuple) else c
        return getattr(c, "text", str(c))

    async def ask() -> tuple[str, str, str]:
        mcp = _build()
        by_path = text(await mcp.call_tool("okl_check", {"path": ["a.py"]}))
        still_unread = inbox.is_file()
        first = text(await mcp.call_tool("okl_check", {"task": "add a retry to the fetch call"}))
        second = text(await mcp.call_tool("okl_check", {"task": "add a retry to the fetch call"}))
        assert still_unread, "a path's briefing must leave the report unread"
        return by_path, first, second

    by_path, first, second = asyncio.run(ask())
    assert "lesson review of your last push" not in by_path
    assert "the lesson review of your last push reported this" in first and "the report nobody has read" in first
    assert "lesson review of your last push" not in second and not inbox.exists()


def _markers(setup) -> list[Path]:
    """The changes remembered as reviewed (the branch records beside them are not changes)."""
    return [f for f in _state(setup).glob("*.json") if not f.name.startswith("branch-")]


def _branch_record(setup) -> dict:
    (record,) = _state(setup).glob("branch-*.json")
    return json.loads(record.read_text())


def test_a_lesson_left_with_no_verdict_is_checked_at_the_next_push(setup):
    """A change was remembered as reviewed when one picked lesson got a verdict, and a branch kept
    only the lessons reported broken: a lesson whose check failed or timed out was never checked
    again (found by the review before the pull request). A change counts as reviewed only when every
    lesson picked for it has a verdict, and what got none is left for the next push. Pushed again as
    it is, the change is checked for what is left alone: what was reported does not hold it twice."""
    partly = {"PICKED": '["l-alpha", "l-beta"]', "VERDICTS": '{"l-alpha": "breaks", "l-beta": "FAIL"}'}
    held = setup["run"]("--before-push", **HOLD, **partly)
    assert held.returncode == 1 and len(setup["prompts"]()) == 3, held.stdout + held.stderr
    assert "- `l-beta`:" in held.stdout and "The lessons not checked are checked at the next push of this branch" in held.stdout
    assert "does not hold it twice, and the 1 lesson(s) not checked are checked then" in held.stderr
    assert _markers(setup) == [], "one lesson has no verdict, so the change is not remembered as reviewed"
    assert (_branch_record(setup)["broken"], _branch_record(setup)["unfinished"]) == (["l-alpha"], ["l-beta"])
    # The same push again: one call, for the lesson left, and no pick. l-alpha was reported, and is not asked twice.
    again = setup["run"]("--before-push", **HOLD, PICKED="[]", VERDICTS='{"l-alpha": "breaks", "l-beta": "holds"}')
    assert again.returncode == 0 and len(setup["prompts"]()) == 4, again.stdout + again.stderr
    assert "1 of the 1 lessons this branch's last review reported broken or did not check were checked again" in again.stdout
    assert "reported broken or did not check" in again.stderr
    checks = [p.split("--- END OF THE LESSON ---")[0] for _, p in setup["prompts"]() if "--- END OF THE LESSON ---" in p]
    assert (sum("[l-beta]" in c for c in checks), sum("[l-alpha]" in c for c in checks)) == (2, 1)
    # Now every picked lesson has a verdict: the change is remembered whole, with what the first try found.
    assert len(_markers(setup)) == 1 and _branch_record(setup)["broken"] == ["l-alpha"] and not _branch_record(setup)["unfinished"]
    seen = setup["run"]("--before-push", **HOLD, **partly)
    assert seen.returncode == 0 and len(setup["prompts"]()) == 4, seen.stdout
    assert "This change was reviewed" in seen.stdout and "1 broken, 1 held" in seen.stdout and "`l-alpha`" in seen.stdout
    # On a later push, a lesson checked again that gets no verdict stays on the branch's list.
    _forget(setup)
    both = {"PICKED": '["l-alpha", "l-beta"]', "VERDICTS": '{"l-alpha": "breaks", "l-beta": "breaks"}'}
    assert setup["run"]("--before-push", **HOLD, **both).returncode == 1
    _commit(setup, "z = 3")
    calls = len(setup["prompts"]())
    lost = setup["run"]("--before-push", **HOLD, PICKED="[]", VERDICTS='{"l-alpha": "holds", "l-beta": "FAIL"}')
    assert lost.returncode == 0 and len(setup["prompts"]()) == calls + 2, lost.stdout + lost.stderr
    assert (_branch_record(setup)["broken"], _branch_record(setup)["unfinished"]) == ([], ["l-beta"])
    _commit(setup, "w = 4")
    found = setup["run"]("--before-push", **HOLD, PICKED="[]", VERDICTS='{"l-beta": "breaks"}')
    assert found.returncode == 1 and len(setup["prompts"]()) == calls + 3, "l-beta is checked again, and only it"
    assert "nothing is left" not in found.stdout and "`l-beta`" in found.stdout and "**breaks**" in found.stdout
    # The limit on one run's checks leaves a lesson for the next push, where it goes first: never out twice.
    _forget(setup)
    _commit(setup, "v = 5")
    assert setup["run"]("--before-push", **HOLD, **both).returncode == 1
    _commit(setup, "u = 6")
    one = setup["run"]("--before-push", **HOLD, **both, LESSON_REVIEW_PICK="1")
    assert "- `l-beta`: over the 1 lessons one run checks" in one.stdout, one.stdout
    assert (_branch_record(setup)["broken"], _branch_record(setup)["unfinished"]) == (["l-alpha"], ["l-beta"])
    _commit(setup, "t = 7")
    two = setup["run"]("--before-push", **HOLD, **both, LESSON_REVIEW_PICK="1")
    assert "| `l-beta` " in two.stdout and "- `l-alpha`: over the 1 lessons" in two.stdout, two.stdout


def test_the_branch_is_remembered_at_the_commit_that_was_reviewed(setup):
    """The branch's head was read when the review ended. A review runs for minutes in the
    background, and a commit made meanwhile was remembered as the one reviewed, though no check had
    seen it. The commit is read once, before the diff, and that one is remembered."""
    reviewed = _git(setup["repo"], "rev-parse", "HEAD")
    slow = {"PICKED": '["l-alpha", "l-beta"]', "VERDICTS": '{"l-alpha": "SLEEP", "l-beta": "breaks"}', "SLEEP_SECONDS": "3"}
    review = subprocess.Popen(["bash", str(setup["repo"] / "ci" / "lesson-review.sh"), "--before-push"], cwd=setup["repo"],
                              env={**setup["env"], **HOLD, **slow}, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        _wait(lambda: len(setup["prompts"]()) >= 2)      # the pick is over and a check is under way
        _commit(setup, "meanwhile = 1")
        out, err = review.communicate(timeout=60)
    finally:
        review.kill()
    assert review.returncode == 1, out + err
    assert _git(setup["repo"], "rev-parse", "HEAD") != reviewed
    assert _branch_record(setup)["head"] == reviewed, "the commit the checks read, not the one made meanwhile"
    assert "meanwhile" not in "\n".join(p for _, p in setup["prompts"]())


def test_a_review_whose_report_could_not_be_kept_is_not_remembered(setup):
    """In the background the report is read from a file at the next push. Where that file could not
    be written, the change was remembered as reviewed all the same, and its findings were never
    shown to anyone. Held in the foreground, the report was printed to the person, and counts."""
    (_state(setup) / "last-report.md").mkdir(parents=True)      # a folder where the report goes: it cannot be written
    assert setup["run"]("--before-push", **BREAKS).returncode == 0
    _wait(lambda: len(setup["prompts"]()) == 3)
    _wait(lambda: not list(_state(setup).glob("*.running")))
    time.sleep(0.5)
    assert list(_state(setup).glob("*.json")) == [], "nothing is remembered of a review nobody was shown"
    shown = setup["run"]("--before-push", **HOLD, **BREAKS)
    assert shown.returncode == 1 and len(setup["prompts"]()) == 6 and "**breaks**" in shown.stdout, "reviewed again"
    assert "could not be kept" in shown.stderr
    assert len(_markers(setup)) == 1, "printed to the person, it was delivered"


def test_a_second_unread_report_is_added_to_the_first(setup):
    """Two branches reviewed before either report is read: the second report was written over the
    first, whose change stayed remembered as reviewed, so its findings were gone. Each unread report
    is kept, under its branch's name, until it is shown."""
    inbox = _okl_set_up(setup) / "review-unread.md"
    first = _git(setup["repo"], "rev-parse", "--abbrev-ref", "HEAD")
    assert setup["run"]("--before-push", **HOLD, **BREAKS).returncode == 1
    assert inbox.read_text().startswith(f"Branch `{first}`\n\n") and "---" not in inbox.read_text().split("|---|")[0]
    _git(setup["repo"], "checkout", "-q", "-b", "second-branch")
    _commit(setup, "other = 2")
    assert setup["run"]("--before-push", **HOLD, PICKED='["l-gamma"]', VERDICTS='{"l-gamma": "breaks"}').returncode == 1
    unread = inbox.read_text()
    one, two = unread.split("\n---\n\n")
    assert one.startswith(f"Branch `{first}`") and "`l-alpha`" in one and "l-gamma" not in one
    assert two.startswith("Branch `second-branch`") and "`l-gamma`" in two and "l-alpha" not in two
    # last-report.md is the last review alone: it is where one report is looked up, not the unread ones.
    assert "l-alpha" not in (_state(setup) / "last-report.md").read_text()


def test_init_copies_the_review_script_byte_for_byte_and_the_dry_run_lists_it_wherever_it_is_written(tmp_path, capsys, monkeypatch):
    """Copied as text, the script got CRLF line endings on Windows and bash could not run it: it is
    copied as bytes. And the dry run named the script only beside the pre-push hook, so with
    --no-git-hook, or outside a git repository, it listed nothing where init writes the file."""
    from okl.cli import install, main
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.chdir(repo)
    base = ["init", "--repo", "r", "--no-claude", "--no-seed", "--no-ci", "--review-before-push", "claude -p"]
    for extra in (["--no-git-hook"], []):       # in no git repository both times
        assert main([*base, *extra, "--dry-run"]) == 0
        listed = capsys.readouterr().out
        assert "ci/lesson-review.sh" in listed and "the review the pre-push hook runs" in listed, extra
        assert not (repo / "ci").exists(), "a dry run writes nothing"
    # A shipped script with a carriage return in it shows a copy made as text on any system: read as
    # text, the line ending is rewritten, as written as text it is on Windows.
    shipped = tmp_path / "shipped.sh"
    shipped.write_bytes(b"#!/usr/bin/env bash\n# --before-push\necho 'one\r\ntwo'\n")
    monkeypatch.setattr(install, "REVIEW_SCRIPT_SRC", shipped)
    assert main([*base, "--no-git-hook"]) == 0
    script = repo / "ci" / "lesson-review.sh"
    assert script.read_bytes() == shipped.read_bytes(), "byte for byte"
    capsys.readouterr()
    assert main([*base, "--dry-run"]) == 0
    assert "ci/lesson-review.sh" not in capsys.readouterr().out, "it is there now, and a script in the repo is kept"
