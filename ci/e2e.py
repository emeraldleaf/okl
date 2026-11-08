#!/usr/bin/env python3
"""okl end to end, as a user runs it: an installed okl, a fresh repository, the real hooks.

Each scenario builds what it needs in a scratch folder and drives okl the way a person and
their agent do: `okl init` on a monorepo with a folder it cannot read, the prompt and Stop
hooks fed the JSON Claude Code sends, the loop from record to re-verify with the pre-push
gate, a stamp made on one branch kept out of another's snapshot, and the MCP server over
stdio. With gh and a token, it also reads real pull requests through `okl intake`. Every
check prints PASS or FAIL; it exits 1 if any failed. It reads nothing from this checkout
but the okl it is given, so it tests the install, not the source tree.

    python3 ci/e2e.py --okl /path/to/venv/bin/okl
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

RESULTS: list[tuple[str, bool, str]] = []
# Each run its own session: the Stop hook remembers a session it asked in a marker under
# $TMPDIR, so a fixed id passes once and then never blocks again.
SESSION = f"e2e-{uuid.uuid4().hex[:12]}"
OKL: list[str] = ["okl"]
ENV: dict[str, str] = {}


def check(name: str, ok: bool, detail: str = "") -> bool:
    """Record one check and print it."""
    RESULTS.append((name, ok, detail))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))  # noqa: T201 - a check script reports on stdout
    return ok


def run(args: list[str], cwd: Path, stdin: str | None = None, extra: dict[str, str] | None = None
        ) -> subprocess.CompletedProcess[str]:
    """A command in `cwd`, with this run's environment."""
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True, text=True,
                          env={**ENV, **(extra or {})}, timeout=300)


def okl(cwd: Path, *args: str, stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """The installed okl in `cwd`."""
    return run([*OKL, *args], cwd, stdin)


def git(cwd: Path, *args: str) -> str:
    """git in `cwd`; its stdout."""
    return run(["git", *args], cwd).stdout.strip()


def commit(cwd: Path, message: str) -> str:
    """Commit everything in `cwd`; the new HEAD."""
    git(cwd, "add", "-A")
    git(cwd, "commit", "-qm", message)
    return git(cwd, "rev-parse", "HEAD")


def write(root: Path, rel: str, text: str) -> None:
    """Write `text` at `root/rel`, making its folders."""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def monorepo(root: Path) -> None:
    """A repository with stacks one and two folders down, and folders detection must skip."""
    git(root, "init", "-q", "-b", "main")
    write(root, "app/frontend-react/package.json", '{"dependencies": {"react": "18.3.1"}}')
    write(root, "services/api/pyproject.toml", '[project]\nname = "api"\ndependencies = ["fastapi"]\n')
    write(root, "node_modules/vue/package.json", '{"dependencies": {"vue": "3"}}')
    write(root, "deep/a/b/package.json", '{"dependencies": {"@angular/core": "17"}}')
    write(root, "src/app.py", "def total(xs):\n    return sum(xs)\n")
    write(root, ".gitignore", "node_modules/\n__pycache__/\ndata/\n")
    commit(root, "init")


def scenario_init(root: Path) -> None:
    """okl init detects nested stacks, skips dependency folders and steps over one it cannot read."""
    monorepo(root)
    locked = root / "data" / "postgres"
    locked.mkdir(parents=True)
    (locked / "package.json").write_text("{}")
    can_lock = os.name != "nt" and os.geteuid() != 0
    if can_lock:
        locked.chmod(0)
    (root / ".claude").mkdir()
    try:
        r = okl(root, "init", "--repo", "e2e", "--git-hook", "--no-ci")
    finally:
        locked.chmod(0o755)
    out = r.stdout + r.stderr
    check("init exits 0 with a folder it cannot open" if can_lock else "init exits 0", r.returncode == 0, out[-300:])
    check("init detects react two folders down", "react (app/frontend-react/package.json)" in out, out[:300])
    check("init detects python one folder down", "python (services/api/pyproject.toml)" in out, out[:300])
    check("init skips node_modules and a manifest three folders down",
          "vue" not in out.split("interests")[0] and "angular" not in out, out[:300])
    check("init wires the hooks, the MCP server and the pre-push gate",
          (root / ".claude" / "settings.json").exists() and (root / ".mcp.json").exists()
          and (root / ".git" / "hooks" / "pre-push").exists())


def scenario_hooks(root: Path) -> None:
    """The prompt hook briefs; the Stop hook asks once, then lets the session end."""
    env = {"CLAUDE_PROJECT_DIR": str(root)}
    hook = root / ".claude" / "hooks"
    prompt = json.dumps({"session_id": SESSION, "prompt": "add a react form that posts user input to the api",
                         "cwd": str(root), "hook_event_name": "UserPromptSubmit"})
    r = run(["bash", str(hook / "userpromptsubmit-okl-check.sh")], root, prompt, env)
    try:
        context = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    except (ValueError, KeyError, TypeError):
        context = ""
    check("the prompt hook returns a briefing", r.returncode == 0 and "OKL briefing" in context, r.stderr[-200:])
    stop = json.dumps({"session_id": SESSION, "stop_hook_active": False, "cwd": str(root)})
    r = run(["bash", str(hook / "stop-okl-encode.sh")], root, stop, env)
    check("the Stop hook blocks the first stop with the encoding question",
          r.returncode == 2 and "ENCODING LOOP" in (r.stdout + r.stderr))
    again = json.dumps({"session_id": SESSION, "stop_hook_active": True, "cwd": str(root)})
    check("the Stop hook lets the second stop through",
          run(["bash", str(hook / "stop-okl-encode.sh")], root, again, env).returncode == 0)


def pre_push(root: Path) -> int:
    """The installed pre-push hook's exit, for a push of HEAD."""
    line = f"refs/heads/main {git(root, 'rev-parse', 'HEAD')} refs/heads/main {'0' * 40}\n"
    return run(["bash", str(root / ".git" / "hooks" / "pre-push"), "origin", "file:///nowhere"], root, line).returncode


def scenario_loop(root: Path) -> None:
    """record → never verified → verify → change → drift red, gate blocks → a failing check
    stamps nothing → fix → reverify → green."""
    commit(root, "wire okl")
    good = 'python3 -c "import sys; sys.path.insert(0, \'src\'); from app import total; assert total([1, 2]) == 3; print(\'sum ok\')"'
    r = okl(root, "record", "--type", "Rule", "--scope", "repo", "--tags", "python", "--id", "total-sums",
            "--title", "total() returns the sum of its inputs", "--symptom", "total returns the wrong number",
            "--fix", "keep total a plain sum", "--files", "src/app.py", "--trigger", "total is wrong")
    check("record with files and no check says drift will report it", "never verified" in r.stdout + r.stderr)
    check("the gate is red for a governed lesson never verified", okl(root, "drift", "--gate").returncode == 1)
    r = okl(root, "verify", "total-sums", "--run", good, "--expect", "sum ok")
    check("verify stamps an observed pass", r.returncode == 0 and "verified" in r.stdout, r.stdout[-200:])
    check("the gate is green after verify", okl(root, "drift", "--gate").returncode == 0)
    write(root, "src/app.py", "def total(xs):\n    return sum(xs) + 1\n")
    commit(root, "break total")
    check("the gate goes red when governed code changes", okl(root, "drift", "--gate").returncode == 1)
    check("the pre-push hook blocks the push", pre_push(root) == 1)
    r = okl(root, "reverify", "--yes")
    check("reverify on broken code stamps nothing", "0 re-verified, 1 failed" in r.stdout, r.stdout[-200:])
    write(root, "src/app.py", 'def total(xs):\n    """Sum of xs."""\n    return sum(xs)\n')
    commit(root, "fix total")
    r = okl(root, "reverify", "--yes")
    check("reverify on fixed code re-stamps", "1 re-verified" in r.stdout, r.stdout[-200:])
    check("the gate and the pre-push hook are green again",
          okl(root, "drift", "--gate").returncode == 0 and pre_push(root) == 0)


def scenario_branches(root: Path) -> None:
    """A stamp made on a feature branch stays out of main's snapshot; CI's gate on main stays green."""
    okl(root, "export", "--drift")
    commit(root, "drift snapshot")
    main_stamp = json.loads((root / "okl-drift.json").read_text())["rules"][0].get("verified_commit")
    git(root, "switch", "-qc", "feature")
    write(root, "src/app.py", 'def total(xs):\n    """Sum of xs, on the feature."""\n    return sum(xs)\n')
    commit(root, "feature edit")
    okl(root, "reverify", "--yes")
    git(root, "switch", "-q", "main")
    okl(root, "export", "--drift")
    stamp = json.loads((root / "okl-drift.json").read_text())["rules"][0].get("verified_commit")
    check("main's snapshot keeps main's own stamp", stamp == main_stamp, f"{stamp} != {main_stamp}")
    check("CI's gate on main's committed snapshot is green",
          okl(root, "drift", "--gate", "--snapshot", "okl-drift.json").returncode == 0)
    r = okl(root, "drift")
    check("the local drift names the stamp from another branch", "outside this branch" in r.stdout, r.stdout[-200:])


def scenario_mcp(root: Path) -> None:
    """The MCP server over stdio: initialize, the tools, a briefing, a record read back."""
    p = subprocess.Popen([*OKL, "mcp"], cwd=root, env=ENV, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)

    def call(i: int, method: str, params: dict) -> dict:
        if not (p.stdin and p.stdout):
            raise OSError("the MCP server's pipes are closed")
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": i, "method": method, "params": params}) + "\n")
        p.stdin.flush()
        return json.loads(p.stdout.readline())
    try:
        init = call(1, "initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                      "clientInfo": {"name": "e2e", "version": "0"}})
        check("the MCP server initializes", init.get("result", {}).get("serverInfo", {}).get("name") == "okl")
        if not p.stdin:
            raise OSError("the MCP server's stdin is closed")
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n")
        p.stdin.flush()
        tools = {t["name"] for t in call(2, "tools/list", {})["result"]["tools"]}
        check("the MCP server lists its six tools",
              tools == {"okl_check", "okl_search", "okl_get", "okl_record", "okl_update", "okl_retire"}, str(tools))
        brief = call(3, "tools/call", {"name": "okl_check", "arguments": {"task": "total returns the wrong number"}})
        check("okl_check briefs the lesson", "total-sums" in json.dumps(brief))
        call(4, "tools/call", {"name": "okl_record", "arguments": {
            "type": "Rule", "scope": "repo", "title": "recorded over MCP", "tags": "python", "id": "mcp-e2e",
            "symptom": "s", "fix": "f"}})
        got = call(5, "tools/call", {"name": "okl_get", "arguments": {"id": "mcp-e2e"}})
        check("okl_record writes and okl_get reads it back", "recorded over MCP" in json.dumps(got))
    except (ValueError, KeyError, OSError) as e:
        check("the MCP server answers", False, f"{type(e).__name__}: {e}")
    finally:
        if p.stdin:
            p.stdin.close()
        p.wait(timeout=30)


def scenario_intake(root: Path) -> None:
    """okl intake reads a real merged PR's resolved findings, and refuses a repo that is not OWNER/NAME."""
    if not shutil.which("gh") or not (ENV.get("GH_TOKEN") or ENV.get("GITHUB_TOKEN")):
        print("  SKIP  intake against GitHub: no gh or no token")  # noqa: T201
        return
    r = okl(root, "intake", "pr", "388", "--repo", "emeraldleaf/okl", "--format", "json")
    try:
        found = json.loads(r.stdout)["findings"]
    except (ValueError, KeyError):
        found = []
    check("intake lists a real PR's resolved findings with their commits",
          len(found) >= 3 and all(f.get("commit") for f in found), r.stderr[-200:])
    check("intake names a finding by its title, not a review bot's badge",
          bool(found) and not any(f["summary"].startswith(("Data Integrity", "Maintainability")) for f in found))
    r = okl(root, "intake", "pr", "388", "--repo", "okl")
    check("intake refuses a repo that is not OWNER/NAME", r.returncode == 2 and "OWNER/NAME" in r.stderr, r.stderr[-200:])


def main() -> int:
    """Run every scenario in one scratch repository; exit 1 if any check failed."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--okl", default="okl", help="the installed okl to test (a path, or a command on PATH)")
    args = ap.parse_args()
    # Resolved here: every scenario runs from its scratch repository, where a relative path is wrong.
    found = shutil.which(args.okl) if os.sep not in args.okl else str(Path(args.okl).resolve())
    if not found or not Path(found).exists():
        print(f"okl end to end: no okl at {args.okl!r}")  # noqa: T201
        return 2
    OKL[:] = [found]
    with tempfile.TemporaryDirectory(prefix="okl-e2e-") as tmp:
        root = Path(tmp) / "repo"
        root.mkdir()
        ENV.update({k: v for k, v in os.environ.items() if not k.startswith(("OKL_", "GIT_"))})
        ENV.update({"OKL_BIN": found, "OKL_BRIEFING_LOG": "1", "XDG_CACHE_HOME": str(Path(tmp) / "cache"),
                    "GIT_AUTHOR_NAME": "e2e", "GIT_AUTHOR_EMAIL": "e2e@example.invalid",
                    "GIT_COMMITTER_NAME": "e2e", "GIT_COMMITTER_EMAIL": "e2e@example.invalid"})
        scenarios: list[tuple[str, Callable[[Path], None]]] = [
            ("okl init", scenario_init), ("hooks", scenario_hooks), ("the loop", scenario_loop),
            ("branches", scenario_branches), ("MCP", scenario_mcp), ("intake", scenario_intake)]
        for name, fn in scenarios:
            print(f"── {name}")  # noqa: T201
            try:
                fn(root)
            except Exception as e:  # noqa: BLE001 - one scenario's crash is a failure, not the end of the run
                check(f"{name} ran to the end", False, f"{type(e).__name__}: {e}")
    failed = [r for r in RESULTS if not r[1]]
    print(f"\nokl end to end: {len(RESULTS) - len(failed)} of {len(RESULTS)} checks passed")  # noqa: T201
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
