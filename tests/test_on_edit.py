"""`okl on-edit`: a lesson's check, run when the agent edits a file the lesson governs (#435).

Only a check the person approved runs, pinned by the hash of its command: a stored command is
store data, and it reaches a shell only after a person has seen it (lesson n_adea7f2c7373). A
failure goes back to the agent beside its edit; a pass says nothing; nothing is stamped.
"""
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from okl.cli.on_edit import approval

ROOT = Path(__file__).resolve().parents[1]
EDIT_HOOK = ROOT / "src" / "okl" / "scaffold" / "hooks" / "posttooluse-okl-edit.sh"
PY = shlex.quote(sys.executable)
# The lesson's check: orders.py must never hold BAD. It prints its signal only when it holds.
CHECK = ("import sys\nt = open('src/orders.py').read()\n"
         "print('ORDERS OK' if 'BAD' not in t else 'BAD found in orders')\nsys.exit('BAD' in t)\n")
# A check that leaves a mark each time it runs, and sleeps for $SLOW seconds.
MARKS = ("import os, time\nopen('ran.txt', 'a').write('x')\n"
         "time.sleep(float(os.environ.get('SLOW', '0')))\nprint('ORDERS OK')\n")


def _repo(tmp_path):
    if shutil.which("git") is None:
        pytest.skip("git not available")
    repo = tmp_path / "repo"; (repo / "src").mkdir(parents=True)
    local = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True).stdout.split()
    env = {k: v for k, v in os.environ.items() if k not in local and k != "OKL_SERVICE_URL"}
    # Named per command, in this dict: never exported to the test process (a pytest run once
    # inherited OKL_DATABASE_URL and wrote fixture records into a real store).
    env.update(OKL_DATABASE_URL=f"sqlite:///{tmp_path / 'store.db'}", PYTHONPATH=str(ROOT / "src"))
    for cmd in (["init", "-q"], ["config", "user.email", "t@example.com"], ["config", "user.name", "t"]):
        subprocess.run(["git", "-C", str(repo), *cmd], check=True, env=env)
    (repo / "src" / "orders.py").write_text("def get(): ...\n")
    (repo / "check.py").write_text(CHECK)
    (repo / "marks.py").write_text(MARKS)
    (repo / ".okl").mkdir(); (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "r"}))
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "init"], check=True, env=env)
    return repo, env


def _okl(repo, env, *args, **extra):
    return subprocess.run([sys.executable, "-m", "okl", *args], cwd=repo, env={**env, **extra},
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


def _lesson(repo, env, lesson_id="ledger", run=f"{PY} check.py", files="src/orders.py"):
    """A lesson that governs `files`, proven by `run` the way a person proves one."""
    r = _okl(repo, env, "record", "--type", "Rule", "--scope", "repo", "--id", lesson_id,
             "--title", f"Orders never hold BAD ({lesson_id})", "--files", files,
             "--fix", "never write BAD into orders.py")
    assert r.returncode == 0, r.stderr
    v = _okl(repo, env, "verify", lesson_id, "--run", run, "--expect", "ORDERS OK")
    assert v.returncode == 0, v.stderr
    return run


def _config(repo):
    return json.loads((repo / ".okl" / "config.json").read_text())


def _context(proc):
    return json.loads(proc.stdout)["hookSpecificOutput"]["additionalContext"]


def test_add_shows_each_command_and_approves_only_on_a_yes(tmp_path):
    """Unattended, add shows the command and refuses (exit 2, stdout empty); a lesson with no
    stored check, or no such lesson, is refused with the reason; --yes pins the command's hash;
    remove drops it and leaves no empty key behind."""
    repo, env = _repo(tmp_path)
    run = _lesson(repo, env)
    r = _okl(repo, env, "record", "--type", "Rule", "--scope", "repo", "--id", "unproven",
             "--title", "a lesson nobody proved", "--files", "src/orders.py")
    assert r.returncode == 0, r.stderr

    refused = _okl(repo, env, "on-edit", "add", "ledger")
    assert refused.returncode == 2 and refused.stdout == ""
    assert run in refused.stderr and "--yes" in refused.stderr
    assert "on_edit" not in _config(repo)
    for bad, why in (("unproven", "no stored check"), ("nope", "no lesson has this id")):
        r = _okl(repo, env, "on-edit", "add", bad, "--yes")
        assert (r.returncode, r.stdout) == (2, ""), r.stdout
        assert why in r.stderr

    ok = _okl(repo, env, "on-edit", "add", "ledger", "--yes")
    assert ok.returncode == 0, ok.stderr
    assert _config(repo)["on_edit"] == {"ledger": approval(run, "ORDERS OK")}
    assert "1 lesson check(s) run when the agent edits" in ok.stdout and "[ledger]" in ok.stdout
    gone = _okl(repo, env, "on-edit", "remove", "ledger")
    assert gone.returncode == 0 and "on_edit" not in _config(repo)
    assert "[ledger]" in gone.stdout.split("could be added")[1], "an approvable lesson is listed as one"


def test_run_hands_a_failure_back_says_nothing_on_a_pass_and_stamps_nothing(tmp_path):
    """The approved check of a lesson governing the edited file runs: a pass prints nothing in
    hook format, a failure names the lesson, its fix, the command and what it printed, with exit
    1. A file no approved lesson governs, and one outside the repository, run nothing."""
    repo, env = _repo(tmp_path)
    _lesson(repo, env)
    assert _okl(repo, env, "on-edit", "add", "ledger", "--yes").returncode == 0
    proof = _okl(repo, env, "show", "ledger").stdout
    orders = str(repo / "src" / "orders.py")

    passed = _okl(repo, env, "on-edit", "run", "--format", "hook", orders)
    assert (passed.returncode, passed.stdout) == (0, ""), passed.stderr
    (repo / "src" / "orders.py").write_text("BAD = 1\n")
    failed = _okl(repo, env, "on-edit", "run", "--format", "hook", orders)
    assert failed.returncode == 1, failed.stderr
    context = _context(failed)
    assert context.startswith("OKL CHECK FAILED after editing src/orders.py")
    for part in ("[ledger]", "never write BAD into orders.py", "check.py", "BAD found in orders", "exit 1"):
        assert part in context, (part, context)
    assert _okl(repo, env, "show", "ledger").stdout == proof, "an edit-time run stamped the lesson"

    for elsewhere in (str(repo / "check.py"), "/etc/hosts"):
        r = _okl(repo, env, "on-edit", "run", "--format", "hook", elsewhere)
        assert (r.returncode, r.stdout) == (0, ""), r.stdout
    text = _okl(repo, env, "on-edit", "run", str(repo / "check.py"))
    assert text.stdout.startswith("okl on-edit: no approved check governs check.py")


def test_only_an_approved_unchanged_command_runs(tmp_path):
    """A lesson nobody approved does not run on edit, and neither does one whose stored command
    changed after it was approved: that one is named, so the person can review it again."""
    repo, env = _repo(tmp_path)
    _lesson(repo, env, "marks", run=f"{PY} marks.py")
    mark = repo / "ran.txt"
    mark.unlink()   # verify ran it once
    orders = str(repo / "src" / "orders.py")

    unapproved = _okl(repo, env, "on-edit", "run", "--format", "hook", orders)
    assert (unapproved.returncode, unapproved.stdout) == (0, "") and not mark.exists()

    assert _okl(repo, env, "on-edit", "add", "marks", "--yes").returncode == 0
    v = _okl(repo, env, "verify", "marks", "--run", f"{PY} marks.py ", "--expect", "ORDERS OK")
    assert v.returncode == 0, v.stderr
    mark.unlink()
    changed = _okl(repo, env, "on-edit", "run", "--format", "hook", orders)
    assert changed.returncode == 0 and not mark.exists(), "a changed command ran without a new approval"
    assert "[marks]" in _context(changed) and "changed since it was approved" in _context(changed)
    listed = _okl(repo, env, "on-edit")
    assert "NOT RUN" in listed.stdout and "okl on-edit add marks" in listed.stdout


def test_a_slow_check_is_not_judged_and_the_edit_has_a_budget(tmp_path):
    """A check past its timeout is reported as not judged, not as failed (exit 0), and once the
    edit's budget is spent the remaining checks are named as not run."""
    repo, env = _repo(tmp_path)
    _lesson(repo, env, "slow-a", run=f"{PY} marks.py")
    _lesson(repo, env, "slow-b", run=f"{PY} marks.py  ")
    assert _okl(repo, env, "on-edit", "add", "slow-a", "slow-b", "--yes").returncode == 0

    r = _okl(repo, env, "on-edit", "run", "--format", "hook", "--timeout", "1", "--budget", "1",
             str(repo / "src" / "orders.py"), SLOW="5")
    assert r.returncode == 0, r.stderr
    context = _context(r)
    assert "[slow-a]" in context and "did not finish in 1s, so it was not judged" in context
    assert "[slow-b]" in context and "out of time for this edit" in context
    assert "CHECK FAILED" not in context


def _edit_hook(repo, env, file_path, **extra):
    hook_env = {**env, "CLAUDE_PROJECT_DIR": str(repo), "OKL_BIN": f"{sys.executable} -m okl", **extra}
    stdin = json.dumps({"session_id": "s1", "hook_event_name": "PostToolUse", "tool_name": "Edit",
                        "tool_input": {"file_path": file_path}})
    return subprocess.run(["bash", str(EDIT_HOOK)], cwd=repo, env=hook_env, input=stdin,
                          capture_output=True, text=True)


def test_the_edit_hook_starts_no_okl_until_a_check_is_approved_then_hands_failures_back(tmp_path):
    """With nothing approved the hook returns before starting okl; once a check is approved, a
    failing edit comes back as PostToolUse additionalContext; switched off by name it is
    silent; and when okl cannot run, it says the checks did not run instead of staying silent."""
    repo, env = _repo(tmp_path)
    _lesson(repo, env)
    (repo / "src" / "orders.py").write_text("BAD = 1\n")
    orders = str(repo / "src" / "orders.py")
    spy = tmp_path / "spy.sh"
    spy.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(tmp_path / 'started'))}\n"); spy.chmod(0o755)

    idle = _edit_hook(repo, env, orders, OKL_BIN=str(spy))
    assert (idle.returncode, idle.stdout) == (0, "") and not (tmp_path / "started").exists()

    assert _okl(repo, env, "on-edit", "add", "ledger", "--yes").returncode == 0
    hooked = _edit_hook(repo, env, orders)
    assert hooked.returncode == 0, hooked.stderr
    assert _context(hooked).startswith("OKL CHECK FAILED") and "[ledger]" in _context(hooked)

    assert _edit_hook(repo, env, orders, OKL_DISABLED_HOOKS="edit").stdout == ""
    broken = _edit_hook(repo, env, orders, OKL_BIN="/no/such/okl", PATH="/usr/bin:/bin", PYTHONPATH="/nowhere")
    assert broken.returncode == 0
    assert _context(broken).startswith(f"OKL CHECKS NOT RUN for {orders}"), broken.stdout


def test_uninstall_removes_the_edit_hook_and_its_registration(tmp_path):
    """init installs and registers the edit hook; init --uninstall takes both away again."""
    repo, env = _repo(tmp_path)
    assert _okl(repo, env, "init", "--repo", "r", "--no-seed", "--claude").returncode == 0
    hook = repo / ".claude" / "hooks" / "posttooluse-okl-edit.sh"
    assert hook.is_file()
    assert "posttooluse-okl-edit.sh" in (repo / ".claude" / "settings.json").read_text()
    r = _okl(repo, env, "init", "--uninstall")
    assert r.returncode == 0, r.stderr
    assert not hook.exists()
    settings = repo / ".claude" / "settings.json"
    assert not settings.exists() or "posttooluse-okl-edit.sh" not in settings.read_text()


def test_the_docs_state_the_edit_time_limits_the_code_has():
    """The guide and COSTS-AND-KNOBS state the per-check timeout and the per-edit budget; they
    move with the constants, and the budget stays inside Claude Code's 60-second hook limit."""
    from okl.cli.on_edit import BUDGET, TIMEOUT

    def flat(name):
        return " ".join((ROOT / "docs" / name).read_text().split())
    assert BUDGET < 60
    assert f"each gets {TIMEOUT} seconds and one edit gets {BUDGET} in all" in flat("GETTING-STARTED.md")
    assert f"at most {TIMEOUT} seconds each and {BUDGET} an edit" in flat("COSTS-AND-KNOBS.md")
