#!/usr/bin/env python3
"""Does a file's briefing reach the model when Claude Code reads the file? (REPORT §4aj, #94)

Each run builds a fresh scratch repository: `src/ledger.py`, one lesson in its own store that
governs it and names a canary (`audit_trail_7Q`, which exists nowhere else), and a
`.claude/settings.json` that is empty in the control arm and, in the treatment arm, registers
only okl's PostToolUse hook on Read. `claude -p --model sonnet --setting-sources project` is
told to read the file and add `entries_for(account_id)`; it loads only that repo's settings, so
no hook of this machine runs. Per run it records:

  read      the transcript holds a Read of src/ledger.py (the hook cannot fire without one)
  arrived   the transcript holds the frame line the hook logged: `okl-briefing sha256=… bytes=…`
  used      the final src/ledger.py calls audit_trail_7Q( — a grep, no judge

Five runs per arm, alternating. The receipt (evals/results/e2e-read-briefing-<stamp>.json)
holds those extracts, the frames, the code commit and the Claude Code version; the full
transcripts stay in the run's scratch directory, since they carry the session's whole context.

    python3 evals/e2e_read_briefing.py [--runs 5]
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "evals" / "results"
HOOK = REPO / "src" / "okl" / "scaffold" / "hooks" / "posttooluse-okl-read.sh"
CANARY = "audit_trail_7Q"
TIMEOUT = 300
AGENT = ["claude", "-p", "--model", "sonnet", "--setting-sources", "project", "--strict-mcp-config",
         "--output-format", "json", "--tools", "Read,Edit,Write", "--allowedTools", "Read", "Edit", "Write"]
TASK = ("Read src/ledger.py, then add a function entries_for(account_id) to it that returns the list of "
        "that account's entries. Keep the change small.")
FIXTURE = '''"""A ledger of account entries, held in memory."""

ENTRIES = [
    {"account_id": "a1", "amount": 120},
    {"account_id": "a2", "amount": -40},
    {"account_id": "a1", "amount": 15},
]


def all_entries():
    """Every entry in the ledger."""
    return list(ENTRIES)


def balance(account_id):
    """The sum of one account's entries."""
    return sum(e["amount"] for e in ENTRIES if e["account_id"] == account_id)
'''
LESSON = ["--type", "Rule", "--scope", "repo", "--id", "ledger-audit", "--files", "src/ledger.py",
          "--title", "Every read of an account's ledger entries is recorded by the audit trail",
          "--symptom", "a function returns an account's ledger entries without recording the read",
          "--fix", f"call {CANARY}(account_id) before returning any of an account's entries "
                   f"(from audit import {CANARY})"]


def git_env() -> dict[str, str]:
    """This environment without the variables that locate a repository."""
    local = subprocess.run(["git", "rev-parse", "--local-env-vars"], capture_output=True, text=True).stdout.split()
    return {k: v for k, v in os.environ.items() if k not in local}


def build(room: Path, arm: str) -> tuple[Path, dict[str, str]]:
    """A fresh scratch repo and store for one run, and the environment the agent runs in."""
    repo = room / "repo"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "ledger.py").write_text(FIXTURE)
    (repo / ".okl").mkdir()
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "ledger-demo"}))
    (repo / ".claude" / "hooks").mkdir(parents=True)
    settings: dict = {}
    if arm == "treatment":
        shutil.copy(HOOK, repo / ".claude" / "hooks" / HOOK.name)
        settings = {"hooks": {"PostToolUse": [{"matcher": "Read", "hooks": [
            {"type": "command", "command": f'bash "$CLAUDE_PROJECT_DIR/.claude/hooks/{HOOK.name}"'}]}]}}
    (repo / ".claude" / "settings.json").write_text(json.dumps(settings, indent=2))
    env = {**git_env(), "OKL_DATABASE_URL": f"sqlite:///{room / 'store.db'}", "OKL_BIN": f"{sys.executable} -m okl",
           "PYTHONPATH": str(REPO / "src"), "OKL_FRAME_LOG": str(room / "frames.jsonl"), "TMPDIR": str(room)}
    for k in ("OKL_SERVICE_URL", "OKL_TOKEN", "OKL_DISABLED_HOOKS", "OKL_QUIET"):
        env.pop(k, None)
    git = ["git", "-C", str(repo)]
    for cmd in (["init", "-q"], ["config", "user.email", "e2e@example.com"], ["config", "user.name", "e2e"],
                ["add", "src", ".claude"], ["commit", "-qm", "fixture"]):
        subprocess.run([*git, *cmd], check=True, env=env, capture_output=True)
    rec = subprocess.run([sys.executable, "-m", "okl", "record", *LESSON], cwd=repo, env=env,
                         capture_output=True, text=True)
    if rec.returncode != 0:
        sys.exit(f"ABORT: could not record the lesson: {rec.stderr.strip()}")
    # The canary is learnable from the lesson alone: nowhere in what the agent can read.
    leak = subprocess.run(["grep", "-rlF", CANARY, str(repo)], capture_output=True, text=True).stdout.strip()
    if leak:
        sys.exit(f"ABORT: the canary is in the scratch repo before the run: {leak}")
    return repo, env


def transcript_of(session_id: str) -> Path | None:
    """The session's transcript, wherever Claude Code filed it under ~/.claude/projects."""
    found = list((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    return found[0] if found else None


def measure(repo: Path, room: Path, out: dict) -> dict:
    """read, arrived and used for one finished run."""
    session = out.get("session_id") or ""
    path = transcript_of(session) if session else None
    text = path.read_text() if path else ""
    read = False
    for line in text.splitlines():
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        for block in ((entry.get("message") or {}).get("content") or []):
            if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("name") == "Read" \
                    and str((block.get("input") or {}).get("file_path", "")).endswith("src/ledger.py"):
                read = True
    frames_file = room / "frames.jsonl"
    frames = [json.loads(x) for x in frames_file.read_text().splitlines()] if frames_file.exists() else []
    lines = [f"okl-briefing sha256={f['sha256']} bytes={f['bytes']}" for f in frames]
    arrived = bool(lines) and all(fl in text for fl in lines)
    final = (repo / "src" / "ledger.py").read_text()
    if path:
        shutil.copy(path, room / "transcript.jsonl")
    return {"session": session, "transcript_found": bool(path), "read": read, "frames": frames,
            "arrived": arrived, "used": f"{CANARY}(" in final,
            "defines_entries_for": "def entries_for(" in final,
            "cost_usd": out.get("total_cost_usd"), "secs": round((out.get("duration_ms") or 0) / 1000, 1),
            "error": out.get("error")}


def run_one(arm: str, keep: Path) -> dict:
    """One session in a fresh scratch repo; its directory is kept under `keep`."""
    room = Path(tempfile.mkdtemp(prefix=f"okl-e2e-{arm}-", dir=keep))
    repo, env = build(room, arm)
    try:
        p = subprocess.run(AGENT, input=TASK, cwd=repo, env=env, capture_output=True, text=True, timeout=TIMEOUT)
        out = json.loads(p.stdout) if p.stdout.strip().startswith("{") else {"error": (p.stderr or "no output")[-300:]}
    except subprocess.TimeoutExpired:
        out = {"error": f"no answer in {TIMEOUT} seconds"}
    result = {"arm": arm, "room": str(room), **measure(repo, room, out)}
    print(f"{arm:9} read={result['read']!s:5} arrived={result['arrived']!s:5} used={result['used']!s:5} "
          f"{result['error'] or ''}", flush=True)
    return result


def summarize(runs: list[dict]) -> dict:
    """§4aj's measures and predictions."""
    def arm(name: str) -> list[dict]:
        return [r for r in runs if r["arm"] == name]
    t, c = arm("treatment"), arm("control")
    t_read, c_read = [r for r in t if r["read"]], [r for r in c if r["read"]]
    no_read = sum(1 for r in runs if not r["read"])
    return {
        "treatment": {"runs": len(t), "read": len(t_read), "arrived": sum(r["arrived"] for r in t_read),
                      "used": sum(r["used"] for r in t_read)},
        "control": {"runs": len(c), "read": len(c_read), "used": sum(r["used"] for r in c),
                    "frames_logged": sum(bool(r["frames"]) for r in c)},
        "predictions": {"1_arrives_in_every_treatment_read": bool(t_read) and all(r["arrived"] for r in t_read),
                        "2_canary_in_at_least_4_treatment_reads": sum(r["used"] for r in t_read) >= 4,
                        "3_no_control_uses_canary": not any(r["used"] for r in c)},
        "counts_only": no_read > max(1, len(runs) // 5),
    }


def main() -> int:
    """Run §4aj and write its receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=5, help="sessions per arm")
    args = ap.parse_args()
    if shutil.which("claude") is None:
        sys.exit("ABORT: claude is not on PATH")
    stamp = f"{datetime.now(UTC):%Y%m%d-%H%M}"
    keep = Path(tempfile.gettempdir()) / f"okl-e2e-read-briefing-{stamp}"
    keep.mkdir()
    runs = [run_one(arm, keep) for _ in range(args.runs) for arm in ("treatment", "control")]
    version = subprocess.run(["claude", "--version"], capture_output=True, text=True).stdout.strip()
    receipt = {
        "what": "does a file's briefing reach the model when Claude Code reads the file (REPORT §4aj)",
        "at": f"{datetime.now(UTC):%Y-%m-%dT%H:%MZ}",
        "code": subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short=12", "HEAD"],
                               capture_output=True, text=True).stdout.strip(),
        "claude_code": version, "agent": " ".join(AGENT), "task": TASK, "canary": CANARY,
        "summary": summarize(runs),
        "runs": [{k: v for k, v in r.items() if k != "room"} for r in runs],
        "transcripts_kept_in": str(keep),
    }
    out = RESULTS / f"e2e-read-briefing-{stamp}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps(receipt["summary"], indent=1))
    print(f"receipt: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
