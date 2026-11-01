#!/usr/bin/env python3
"""What a drift_mutate run's model sessions saw and did (REPORT §4ah), read from the transcripts
Claude Code keeps for each headless session.

    python3 evals/harness_transcripts.py <run> [--rejudge <dir>] [--earlier <run>]
        # writes evals/results/harness-transcripts-<run>.json

<run> is the suffix of the run's scratch folder (okl-mutate-<run>, its breakers' worktrees
okl-mutate-<run>/breaker-*); --rejudge names the folder a re-judge ran in (okl-rejudge-<dir>);
--earlier names another run, of which only the hidden snapshot's visibility is counted. The
transcripts live under ~/.claude/projects and are swept in time, so this receipt is the record.
It holds counts and repository file names only: no prompt, no answer, nothing a session's
context carried beyond the worktree's git status lines.

Per breaker session:
- the git status lines the session's context carried, how many name a deleted (hidden) file,
  whether the status was cut short, and which hidden check scripts, snapshot and write-ups it
  named (counted per session, per lesson);
- each Read, Grep, Glob or Edit call aimed at a hidden path (drift_mutate.BLIND, or the
  lesson's own check files), and whether it returned content;
- each call aimed at a path outside its worktree, and of those, under this repository's main
  checkout.
Per judge session: whether an answer was saved at all, and whether an answer wrote a tool call
out as text (the judge runs with no tools).
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from drift_mutate import BLIND  # the run's own list of what --blind hides

REPO = Path(__file__).resolve().parent.parent
PROJECTS = Path.home() / ".claude" / "projects"
# What a breaker could learn its lesson's check from, by name.
NOTED = ("okl-drift.json", "evals/REPORT.md", "CHANGELOG.md", "tests/test_ci_checks.py")


def own_checks(rule: dict) -> list[str]:
    """The files under ci/ or evals/ a lesson's check names, as drift_mutate.hidden reads them."""
    return [w for w in re.findall(r"[\w./-]+", str(rule.get("verified_by") or "")) if w.startswith(("ci/", "evals/"))]


def events(path: Path) -> list[dict]:
    """A transcript's events, skipping lines that are not JSON."""
    out = []
    for line in path.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def blocks(e: dict) -> list[dict]:
    """An event's content blocks; a plain string is one text block."""
    content = (e.get("message") or {}).get("content")
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    return content if isinstance(content, list) else []


def status_lines(evs: list[dict]) -> tuple[list[str], bool]:
    """The deleted files the session's git status named, and whether the status was cut short."""
    for e in evs:
        for b in blocks(e):
            m = re.search(r"Status:\n(.*?)\n\s*Recent commits", str(b.get("text") or ""), re.S)
            if m:
                return re.findall(r"^ ?D (\S+)", m.group(1), re.M), "(truncated" in m.group(1)
    return [], False


def breaker(path: Path, main: str, hidden: tuple[str, ...]) -> dict:
    """One breaker session: what its status named, and its calls at hidden or outside paths."""
    evs = events(path)
    deleted, cut = status_lines(evs)
    cwd = next((str(e["cwd"]) for e in evs if e.get("cwd")), "")
    roots = {cwd, cwd.removeprefix("/private")} - {""}
    asked, answered, outside, in_main = {}, 0, 0, 0
    for e in evs:
        for b in blocks(e):
            if b.get("type") == "tool_use":
                target = str((b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("path") or "")
                rel = next((target[len(r):].lstrip("/") for r in roots if target == r or target.startswith(r + "/")), None)
                if target.startswith("/") and rel is None:
                    outside += 1
                    in_main += target == main or target.startswith(main + "/")
                rel = target if rel is None else rel
                if any(rel == h or rel.startswith(h.rstrip("/") + "/") for h in (*hidden, *deleted)):
                    asked[b["id"]] = rel
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in asked:
                said = json.dumps(b.get("content"))
                answered += not any(s in said for s in ("does not exist", "No files found", "No matches found"))
    return {"deleted_named": len(deleted), "cut": cut,
            "named": sorted({d for d in deleted if d.startswith("ci/check-") or d in NOTED}),
            "hidden_asked": len(set(asked.values())), "hidden_returned": answered,
            "outside_worktree_calls": outside, "main_checkout_calls": in_main}


def judge(path: Path) -> dict:
    """One judge session: an answer saved or not, and a tool call written out as text."""
    said = [b.get("text") or "" for e in events(path) if (e.get("message") or {}).get("role") == "assistant"
            for b in blocks(e) if b.get("type") == "text"]
    return {"answered": bool(said), "tool_call_as_text": any("<invoke name=" in s for s in said)}


def folder(name: str) -> list[Path]:
    """The transcripts of the sessions run in a folder whose path ends in `name`."""
    return sorted(p for d in PROJECTS.glob(f"*{name}") for p in d.glob("*.jsonl"))


def main() -> int:
    """Read the run's sessions and write the receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="the suffix of the run's scratch folder, okl-mutate-<run>")
    ap.add_argument("--rejudge", help="the suffix of the re-judge's folder, okl-rejudge-<dir>")
    ap.add_argument("--earlier", help="another run whose breakers' sight of okl-drift.json is counted")
    args = ap.parse_args()
    main_checkout = str(REPO)
    if (REPO / ".git").is_file():   # a worktree: its .git file names <main>/.git/worktrees/<name>
        main_checkout = str(Path((REPO / ".git").read_text().split(":", 1)[1].strip()).parents[2])
    # A folder's name is cut and its underscores made dashes: read the lesson id back from the snapshot.
    rules = {r["id"]: r for r in json.loads((REPO / "okl-drift.json").read_text())["rules"]}
    lessons: dict[str, list[dict]] = {}
    for d in sorted(PROJECTS.glob(f"*okl-mutate-{args.run}-breaker-*")):
        cut = d.name.split("-breaker-", 1)[1].split("-", 1)[1]
        lid = next((i for i in rules if i.replace("_", "-").startswith(cut)), cut)
        hidden = (*BLIND, *own_checks(rules.get(lid) or {}))
        lessons[lid] = [breaker(p, main_checkout, hidden) for p in sorted(d.glob("*.jsonl"))]
    if not lessons:
        sys.exit(f"harness_transcripts: no breaker sessions for okl-mutate-{args.run} under {PROJECTS}")
    every = [s for ss in lessons.values() for s in ss]
    judges = {"first pass": [judge(p) for p in folder(f"okl-mutate-{args.run}")]}
    if args.rejudge:
        judges["re-judge"] = [judge(p) for p in folder(f"okl-rejudge-{args.rejudge}")]
    receipt = {
        "section": "§4ah", "what": "what the run's breaker and judge sessions saw and did, from their transcripts",
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "run": args.run, "rejudge": args.rejudge,
        "code": subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short=12", "HEAD"],
                               capture_output=True, text=True, check=True).stdout.strip(),
        "breakers": {
            "sessions": len(every), "status_cut": sum(s["cut"] for s in every),
            "deleted_named": dict(Counter(s["deleted_named"] for s in every)),
            "hidden_asked": sum(s["hidden_asked"] for s in every),
            "hidden_returned": sum(s["hidden_returned"] for s in every),
            "outside_worktree_calls": sum(s["outside_worktree_calls"] for s in every),
            "main_checkout_calls": sum(s["main_checkout_calls"] for s in every),
            # Per lesson: its sessions, and how many of them named each file.
            "named_per_lesson": {lid: {"sessions": len(ss), **Counter(n for s in ss for n in s["named"])}
                                 for lid, ss in lessons.items()},
        },
        "judges": {k: {"sessions": len(v), "no_answer_saved": sum(not j["answered"] for j in v),
                       "tool_call_as_text": sum(j["tool_call_as_text"] for j in v)} for k, v in judges.items()},
    }
    if args.earlier:
        earlier = [breaker(p, main_checkout, BLIND) for d in PROJECTS.glob(f"*okl-mutate-{args.earlier}-breaker-*")
                   for p in sorted(d.glob("*.jsonl"))]
        receipt["earlier"] = {"run": args.earlier, "sessions": len(earlier),
                              "named_okl_drift_json": sum("okl-drift.json" in s["named"] for s in earlier)}
    out = REPO / "evals" / "results" / f"harness-transcripts-{args.run}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps({k: receipt[k] for k in ("breakers", "judges")}, indent=1))
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
