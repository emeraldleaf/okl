#!/usr/bin/env python3
"""Collect the prompts a person actually typed into Claude Code sessions, for the benchmark's
abstention set: the real prompts against which "brief nothing" is measured.

    python3 evals/bench/extract_prompts.py [--projects ~/.claude/projects] > /dev/null

Writes evals/bench/private/prompts.jsonl, which .gitignore keeps out of the repository: these
are a person's own words from their own sessions, so they are read on the machine that holds
them and only counts and hashes ever reach a receipt. A prompt is kept when it is a plain user
turn in a main session (not a subagent's sidechain, not a tool result), is not a harness
wrapper (command output, task notifications, interrupted-request notes), and is not a paste
longer than the limit. Duplicates are dropped by normalised text. Each row keeps a hash of the
text, the project folder, the session's hash and the timestamp, so a sample can be traced
without the text leaving the machine.
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent / "private" / "prompts.jsonl"
MAX_CHARS = 1500
# Harness text that arrives as a user turn but was not typed by the person.
WRAPPERS = ("<command-", "<local-command", "<task-notification", "<system-reminder", "<user-prompt-submit-hook",
            "[Request interrupted", "Caveat:", "This session is being continued", "<bash-", "<ide_")


def user_text(entry: dict) -> str | None:
    """The typed text of a main-session user turn, or None for anything else."""
    if entry.get("type") != "user" or entry.get("isSidechain") or entry.get("userType") not in (None, "external"):
        return None
    content = entry.get("message", {}).get("content")
    if isinstance(content, list):
        if any(b.get("type") == "tool_result" for b in content if isinstance(b, dict)):
            return None
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return None
    text = content.strip()
    if not text or text.startswith(WRAPPERS) or len(text) > MAX_CHARS:
        return None
    return text


def main() -> None:
    """Walk every session transcript and write the private prompt file."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--projects", default=str(Path.home() / ".claude" / "projects"))
    args = ap.parse_args()
    seen: set[str] = set()
    rows = []
    for path in sorted(Path(args.projects).glob("*/*.jsonl")):
        for line in path.open(errors="ignore"):
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            text = user_text(entry)
            if text is None:
                continue
            norm = re.sub(r"\s+", " ", text.lower()).strip()
            if norm in seen:
                continue
            seen.add(norm)
            rows.append({"id": hashlib.sha256(norm.encode()).hexdigest()[:16], "text": text,
                         "project": path.parent.name,
                         "session": hashlib.sha256(str(entry.get("sessionId")).encode()).hexdigest()[:12],
                         "at": entry.get("timestamp")})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    projects = len({r["project"] for r in rows})
    print(f"{len(rows)} distinct prompts from {projects} project folders -> {OUT}", file=sys.stderr)


if __name__ == "__main__":
    main()
