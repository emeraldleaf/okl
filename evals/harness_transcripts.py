#!/usr/bin/env python3
"""What a drift_mutate run's model sessions saw and did (REPORT §4ah), read from the transcripts
Claude Code keeps for each headless session.

    python3 evals/harness_transcripts.py <run> [--rejudge <dir>] [--earlier <run>]
        # writes evals/results/harness-transcripts-<run>.json
    python3 evals/harness_transcripts.py <run> --rule-mutate [--rejudge <dir>]
        # §4bf's layout: okl-4bf-<run>, breakers okl-4bf-<run>-breaker-<slot>, the slot being the
        # lesson's place in rule_mutate.POPULATION; writes evals/results/harness-transcripts-4bf-<run>.json

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
    for line in path.read_text(encoding="utf-8").splitlines():
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


def parse_status(text: str) -> tuple[list[str], bool] | None:
    """The deleted files a git status text names and whether it was cut short, or None if it
    holds no status. Found by search, not one regex: a lazy span before \\s* backtracks."""
    start = text.find("Status:\n")
    end = text.find("Recent commits", start) if start >= 0 else -1
    if end < 0:
        return None
    status = text[start + len("Status:\n"):end]
    return re.findall(r"^ ?D (\S+)", status, re.M), "(truncated" in status


def status_lines(evs: list[dict]) -> tuple[list[str], bool]:
    """The deleted files the session's git status named, and whether the status was cut short.
    The status's own home is the session_context attachment's gitStatus; a copy inside a
    message's text is the fallback, since not every transcript carries one (review on #328)."""
    for e in evs:
        att = e.get("attachment") or {}
        if att.get("type") == "session_context" and isinstance(att.get("context"), dict):
            found = parse_status(str(att["context"].get("gitStatus") or ""))
            if found:
                return found
    for e in evs:
        for b in blocks(e):
            found = parse_status(str(b.get("text") or ""))
            if found:
                return found
    return [], False


def breaker(path: Path, main: str, hidden: tuple[str, ...]) -> dict:
    """One breaker session: what its status named, and its calls at hidden or outside paths."""
    evs = events(path)
    deleted, cut = status_lines(evs)
    cwd = next((str(e["cwd"]) for e in evs if e.get("cwd")), "")
    # macOS spells the temp folder both with and without /private; a call may use either (#446).
    bare = cwd.removeprefix("/private")
    roots = {bare, "/private" + bare} - {"", "/private"}
    asked, answered, outside, in_main = {}, 0, 0, 0
    seen_calls, seen_results = set(), set()   # each call is saved twice: in its event and its request blob
    tree = Path(bare).name
    for e in evs:
        for b in blocks(e):
            if b.get("type") == "tool_use":
                if b.get("id") in seen_calls:
                    continue
                seen_calls.add(b.get("id"))
                given = b.get("input") or {}
                target = str(given.get("file_path") or given.get("path") or "")
                rel = next((target[len(r):].lstrip("/") for r in roots if target == r or target.startswith(r + "/")), None)
                # A path the model garbled (a dash for the temp folder's underscore or slash) still names its
                # own tree by that tree's folder name; read the part after it (review on #451).
                if rel is None and tree and f"/{tree}/" in target:
                    rel = target.split(f"/{tree}/", 1)[1]
                if target.startswith("/") and rel is None:
                    outside += 1
                    in_main += target == main or target.startswith(main + "/")
                rel = target if rel is None else rel
                if any(rel == h or rel.startswith(h.rstrip("/") + "/") for h in (*hidden, *deleted)):
                    asked[b["id"]] = rel
                # A shell command naming a hidden file reaches for it too, even where the tool was refused.
                command = str(given.get("command") or "")
                if command and any(h in command for h in (*hidden, *deleted) if "/" in h or "." in h):
                    asked[b["id"]] = next(h for h in (*hidden, *deleted) if h in command)
            elif b.get("type") == "tool_result" and b.get("tool_use_id") in asked:
                if b.get("tool_use_id") in seen_results:
                    continue
                seen_results.add(b.get("tool_use_id"))
                said = json.dumps(b.get("content"))
                refused = ("does not exist", "No files found", "No matches found", "is outside", "No such tool")
                answered += not any(s in said for s in refused)
    return {"deleted_named": len(deleted), "cut": cut, "sessions_hidden_calls": sorted(set(asked.values())),
            "named": sorted({d for d in deleted if d.startswith("ci/check-") or d in NOTED}),
            "hidden_asked": len(set(asked.values())), "hidden_returned": answered,
            "outside_worktree_calls": outside, "main_checkout_calls": in_main}


def facts(path: Path) -> dict:
    """What any session sent and loaded, read from its saved file: the effort each request carried,
    whether the repository's CLAUDE.md was in its context, whether a git status was, and whether
    that status's commit subjects named §4bf (#446)."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    return {"efforts": sorted(set(re.findall(r'"effort":"([a-z]+)"', raw))),
            "claude_md": "okl \u2014 repo instructions" in raw or "okl — repo instructions" in raw,
            "git_status": "Recent commits" in raw,
            "names_4bf": bool(re.search(r"4bf (pre-registration|instrument)", raw))}


def judge(path: Path) -> dict:
    """One judge session: an answer saved or not, and a tool call written out as text."""
    said = [b.get("text") or "" for e in events(path) if (e.get("message") or {}).get("role") == "assistant"
            for b in blocks(e) if b.get("type") == "text"]
    return {"answered": bool(said), "tool_call_as_text": any("<invoke name=" in s for s in said)}


def folder(name: str) -> list[Path]:
    """The transcripts of the sessions run in a folder whose path ends in `name`."""
    return sorted(p for d in PROJECTS.glob(f"*{name}") for p in d.glob("*.jsonl"))


def main_4bf(run: str, rejudge: str | None, main_checkout: str) -> int:
    """§4bf's sessions: what the breakers' context carried and what they reached for, and the judges'
    effort and answers. Counts and repository file names only."""
    import rule_mutate as rm
    lessons = list(rm.POPULATION)
    per: dict[str, list[dict]] = {}
    # Folders before #446's renaming (okl-4bf-<run>-breaker-<slot>) and after (okl-w-<run>/t<slot>).
    dirs = [*PROJECTS.glob(f"*okl-4bf-{run}-breaker-*"), *PROJECTS.glob(f"*okl-w-{run}-t[0-9]*")]
    for d in sorted(dirs):
        slot = int(d.name.rsplit("-", 1)[1].lstrip("t"))
        lid = lessons[slot]
        governed = ["README.md", "docs/"] if lid == "docs-agent-neutral" else []   # its own files stay visible
        hidden = tuple(x for x in rm.HIDE if not any(x == g.rstrip("/") or x.startswith(g) for g in governed))
        per[lid] = [{**breaker(f, main_checkout, hidden), **facts(f)} for f in sorted(d.glob("*.jsonl"))]
    if not per:
        sys.exit(f"harness_transcripts: no breaker sessions for okl-4bf-{run} under {PROJECTS}")
    every = [x for xs in per.values() for x in xs]
    first = [{**judge(f), **facts(f)} for f in folder(f"okl-4bf-{run}") + folder(f"okl-w-{run}")]
    again = [{**judge(f), **facts(f)} for f in folder(f"okl-4bf-rejudge-{rejudge}")] if rejudge else []

    def tally(xs: list[dict]) -> dict:
        return {"sessions": len(xs), "effort": dict(Counter(",".join(x["efforts"]) or "none" for x in xs)),
                "claude_md": sum(x["claude_md"] for x in xs), "git_status": sum(x["git_status"] for x in xs)}
    receipt = {
        "section": "§4bf", "what": "what §4bf's breaker and judge sessions sent, saw and did, from their saved files",
        "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "run": run, "rejudge": rejudge,
        "code": subprocess.run(["git", "-C", str(REPO), "rev-parse", "--short=12", "HEAD"],
                               capture_output=True, text=True, check=True).stdout.strip(),
        "breakers": {**tally(every),
                     "status_named_4bf": sum(x["names_4bf"] for x in every),
                     "status_named_a_deleted_file": sum(bool(x["deleted_named"]) for x in every),
                     "status_named_a_check_script": sum(any(n.startswith("ci/check-") for n in x["named"]) for x in every),
                     "check_scripts_named": dict(Counter(n for x in every for n in x["named"])),
                     "sessions_reaching_for_a_hidden_file": sum(bool(x["hidden_asked"]) for x in every),
                     "hidden_paths_reached_for": sum(x["hidden_asked"] for x in every),
                     "hidden_reads_that_returned_content": sum(x["hidden_returned"] for x in every),
                     "outside_worktree_calls": sum(x["outside_worktree_calls"] for x in every),
                     "main_checkout_calls": sum(x["main_checkout_calls"] for x in every),
                     "per_lesson_sessions": {lid: len(xs) for lid, xs in per.items()}},
        "judges": {"first pass": {**tally(first), "no_answer_saved": sum(not j["answered"] for j in first),
                                  "tool_call_as_text": sum(j["tool_call_as_text"] for j in first)},
                   **({"re-judge": {**tally(again), "no_answer_saved": sum(not j["answered"] for j in again),
                                    "tool_call_as_text": sum(j["tool_call_as_text"] for j in again)}} if again else {})},
    }
    out = REPO / "evals" / "results" / f"harness-transcripts-4bf-{run}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("breakers", "judges")}, indent=1))
    print(f"wrote {out.relative_to(REPO)}")
    return 0


def main() -> int:
    """Read the run's sessions and write the receipt."""
    ap = argparse.ArgumentParser()
    ap.add_argument("run", help="the suffix of the run's scratch folder, okl-mutate-<run>")
    ap.add_argument("--rejudge", help="the suffix of the re-judge's folder, okl-rejudge-<dir>")
    ap.add_argument("--earlier", help="another run whose breakers' sight of okl-drift.json is counted")
    ap.add_argument("--rule-mutate", action="store_true", help="§4bf's layout (rule_mutate.py), not drift_mutate's")
    args = ap.parse_args()
    main_checkout = str(REPO)
    if (REPO / ".git").is_file():   # a worktree: its .git file names <main>/.git/worktrees/<name>
        main_checkout = str(Path((REPO / ".git").read_text(encoding="utf-8").split(":", 1)[1].strip()).parents[2])
    if args.rule_mutate:
        return main_4bf(args.run, args.rejudge, main_checkout)
    # A folder's name is cut and its underscores made dashes: read the lesson id back from the snapshot.
    rules = {r["id"]: r for r in json.loads((REPO / "okl-drift.json").read_text(encoding="utf-8"))["rules"]}
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
    out.write_text(json.dumps(receipt, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({k: receipt[k] for k in ("breakers", "judges")}, indent=1))
    print(f"wrote {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
