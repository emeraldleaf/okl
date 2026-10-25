"""What a session touched: the lessons it was briefed on, and those whose files it changed.

The Stop question asked once, generically, whether a session learned anything. It told the
agent how to update or retire a lesson, never which ones to look at, so the loop only added
(okl review R4). This names them, so the agent can say which were wrong, out of date or
replaced, and propose the change to the person.

The briefed lessons come from the session's transcript, where Claude Code records each
UserPromptSubmit hook's context. That format is Claude Code's and undocumented, so every
read here fails soft: a transcript it cannot parse yields no lessons, never an error.
"""
from __future__ import annotations

import json
import re
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from .drift import SNAPSHOT_FILE, _glob_matches
from .store import RETIRED_STATUSES, Node

# A briefed lesson's id follows its bold title: `- **FIX: title** [id]` (R1).
_ID = re.compile(r"\*\* \[([^\]\s]+)\]")
# Claude Code keeps a long hook context in a file and leaves a preview in the transcript.
_SAVED = re.compile(r"Full output saved to: (\S+)")
_MAX_SAVED_BYTES = 1_000_000


def _hook_context(line: bytes) -> list[str]:
    """The text a UserPromptSubmit hook added to the context, from one transcript line."""
    # Cheap filter first: a long session's transcript runs to hundreds of megabytes.
    if b"hook_additional_context" not in line:
        return []
    try:
        att = json.loads(line).get("attachment") or {}
    except (ValueError, AttributeError):
        return []
    if att.get("type") != "hook_additional_context" or att.get("hookEvent") != "UserPromptSubmit":
        return []
    content = att.get("content")
    return [c for c in (content if isinstance(content, list) else [content]) if isinstance(c, str)]


def _full_text(text: str) -> str:
    """The whole briefing when the transcript holds only a preview of it."""
    m = _SAVED.search(text)
    if not m:
        return text
    try:
        p = Path(m.group(1))
        if p.is_file() and p.stat().st_size <= _MAX_SAVED_BYTES:
            return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        pass
    return text


def briefed_ids(transcript: str | Path) -> Counter[str]:
    """How many times each lesson id was briefed to the agent in this session.

    Only okl's own briefings count, and only as the prompt hook injected them: the same
    text in a tool result (an `okl check` the agent ran) was output it read, not a briefing.
    """
    counts: Counter[str] = Counter()
    try:
        with Path(transcript).open("rb") as f:
            for line in f:
                for text in _hook_context(line):
                    if "OKL briefing" in text:
                        counts.update(dict.fromkeys(_ID.findall(_full_text(text)), 1))
    except OSError:
        return Counter()
    return counts


def session_start(transcript: str | Path) -> str | None:
    """The first timestamp in the transcript: when the session began, as ISO 8601."""
    try:
        with Path(transcript).open("rb") as f:
            for line in f:
                try:
                    ts = json.loads(line).get("timestamp")
                except (ValueError, AttributeError):
                    continue
                if isinstance(ts, str) and ts:
                    return ts
    except OSError:
        pass
    return None


def _git_lines(repo_dir: str, *args: str) -> list[str]:
    try:
        r = subprocess.run(["git", "-C", repo_dir, *args], capture_output=True, text=True,
                           timeout=15)
    except (OSError, subprocess.TimeoutExpired):
        return []
    return r.stdout.splitlines() if r.returncode == 0 else []


def changed_paths(repo_dir: str, since: str | None) -> set[str]:
    """Paths this session changed: uncommitted edits, and files in commits since `since`.

    okl's own snapshot and store are left out; verify rewrites the snapshot on its own.
    """
    paths = set()
    for line in _git_lines(repo_dir, "status", "--porcelain", "--untracked-files=all", "--",
                           ".", f":(exclude){SNAPSHOT_FILE}", ":(exclude).okl"):
        path = line[3:]
        paths.add(path.split(" -> ", 1)[-1].strip('"'))    # a rename: the new path
    if since:
        paths.update(p for p in _git_lines(repo_dir, "log", f"--since={since}", "--name-only",
                                           "--format=") if p)
    return paths


def governing(nodes: list[Node], repo: str, paths: set[str]) -> list[Node]:
    """Live lessons in this repo's view whose governed files include one of `paths`."""
    repo_scope = f"repo:{repo}"
    out = []
    for n in nodes:
        if not n.files or n.status in RETIRED_STATUSES or n.scope not in ("org", repo_scope):
            continue
        globs = [g for g in n.files.split(",") if g.strip()]
        if any(_glob_matches(g, p) for g in globs for p in paths):
            out.append(n)
    return out


def recap(nodes: list[Node], repo: str, repo_dir: str, transcript: str | None, *,
          since: str | None = None, limit: int = 5) -> dict[str, Any]:
    """The lessons to put to the agent at the end of a session.

    `briefed`: (lesson, times briefed), most often first, live lessons only, at most
    `limit`. `changed`: live lessons whose governed files the session changed, at most
    `limit`, with `changed_more` counting the rest.
    """
    by_id = {n.id: n for n in nodes}
    counts = briefed_ids(transcript) if transcript else Counter()
    briefed = [(by_id[i], c) for i, c in counts.most_common()
               if i in by_id and by_id[i].status not in RETIRED_STATUSES][:limit]
    start = since or (session_start(transcript) if transcript else None)
    changed = governing(nodes, repo, changed_paths(repo_dir, start)) if (start or transcript) else []
    # Capped too: a session that ran for days changes most of a repo.
    return {"briefed": briefed, "changed": changed[:limit],
            "changed_more": max(0, len(changed) - limit)}


def render(result: dict[str, Any]) -> str:
    """The recap as the Stop question shows it, or "" when the session touched no lesson."""
    briefed, changed = result["briefed"], result["changed"]
    if not briefed and not changed:
        return ""
    out = []
    if briefed:
        out.append("\nLessons this session was briefed on, most often first. Is any of them "
                   "wrong, out of date, or replaced by a better one?")
        out += [f"  [{n.id}] {n.title} ({c}×)" for n, c in briefed]
    if changed:
        out.append("\nLessons whose governed files this session changed. Are they still true?")
        out += [f"  [{n.id}] {n.title} (governs {n.files})" for n in changed]
        if result.get("changed_more"):
            out.append(f"  and {result['changed_more']} more: `okl drift` lists every lesson "
                       "whose files changed since its check")
    out += ["\nIf one needs a change, propose it to the person in one line, and make it only "
            "once they agree:",
            "  wrong or replaced: okl retire <id> --reason \"...\" [--by <new-id>]",
            "  needs correcting:  okl update <id> --fix \"...\"   (keeps its proof)",
            "  still true after the change: okl verify <id>, or okl reverify for all of them",
            "  briefed but irrelevant to this work: say which, in one line. That is noise in "
            "the briefing, not a reason to retire the lesson.",
            "If none needs anything, say so in one line."]
    return "\n".join(out) + "\n"


# --- the session report (#279) ---------------------------------------------------------------
#
# "How did this session go": what okl did and what changed in the store over a window, read
# from the store's own append-only logs (briefings, check runs, retirements), the lessons'
# creation times, git, and drift as it stands now. Local stores only: a shared service keeps
# its logs on the server, which has no checkout to read commits or drift from.

_RELATIVE = re.compile(r"^(\d+(?:\.\d+)?)([mhd])$")


def window_start(since: str | None, transcript: str | None, now_ms: int) -> int:
    """Where the report's window begins, in epoch milliseconds.

    `since` may be ISO 8601 ("2026-10-24T14:00Z") or relative to now ("90m", "6h", "2d");
    without it the window starts at the transcript's first timestamp, and without that, a day
    ago. A `since` that cannot be read raises ValueError, so the command can say so.
    """
    if since:
        m = _RELATIVE.match(since.strip())
        if m:
            unit = {"m": 60_000, "h": 3_600_000, "d": 86_400_000}[m.group(2)]
            return now_ms - int(float(m.group(1)) * unit)
        return _iso_ms(since)
    start = session_start(transcript) if transcript else None
    if start:
        try:
            return _iso_ms(start)
        except ValueError:
            pass    # an unreadable transcript time is the default window, never an error
    return now_ms - 86_400_000


def _iso_ms(value: str) -> int:
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp() * 1000)


def _ms_iso(ms: int) -> str:
    from datetime import datetime
    return datetime.fromtimestamp(ms / 1000).astimezone().isoformat(timespec="minutes")


def report(store: Any, repo: str, repo_dir: str, *, since_ms: int, now_ms: int,
           top: int = 5) -> dict[str, Any]:
    """The session report as data: every list newest last, every time in epoch ms."""
    from .drift import scan_drift
    nodes = store.all_nodes()
    by_id = {n.id: n for n in nodes}

    def title(i: str) -> str:
        return by_id[i].title if i in by_id else "(no longer in the store)"

    briefings = [b for b in store.briefings(repo) if b.at >= since_ms]
    shown: Counter[str] = Counter(i for b in briefings for i in b.node_ids)
    stale: Counter[str] = Counter(i for b in briefings for i in b.drifted_ids)
    retired = sorted(({"id": n.id, "title": n.title, "kind": r.kind, "reason": r.reason, "by": r.by, "at": r.at}
                      for n in nodes for r in store.retirements(n.id) if r.at >= since_ms),
                     key=lambda r: r["at"])
    runs = sorted(((n, c) for n in nodes for c in store.checks(n.id) if c.at >= since_ms), key=lambda p: p[1].at)
    since_iso = _ms_iso(since_ms)
    changed = governing(nodes, repo, changed_paths(repo_dir, since_iso))
    # `checked` is how many lessons drift could judge; zero is no evidence, not "all proven"
    # (scan_drift's own rule, review on #281).
    hits, checked = scan_drift(nodes, repo, repo_dir)
    # The open loop (#279, review on #281): a lesson the briefing marked stale (its code changed
    # since its last check) with no check run and no retirement at or after that showing. Advice
    # with no check is "acted on" by being followed, which no log records, so it is only counted.
    # An `okl update` would also close the loop, but it carries no time yet.
    def after(first: dict[str, int]) -> set[str]:
        done = {n.id for n, c in runs if c.at >= first.get(n.id, now_ms + 1)}
        return done | {r["id"] for r in retired if r["at"] >= first.get(r["id"], now_ms + 1)}
    # Shown: from the first showing, for the broad count. Stale: from the LATEST stale showing,
    # since a lesson re-checked and then marked stale again is open again (review on #281);
    # briefings come oldest first, so the last write wins.
    first_shown: dict[str, int] = {}
    last_stale: dict[str, int] = {}
    for b in briefings:
        for i in b.node_ids:
            first_shown.setdefault(i, b.at)
        for i in b.drifted_ids:
            last_stale[i] = b.at
    quiet = sum(1 for i in shown if i in by_id and i not in after(first_shown))
    stale_open = [(i, c) for i, c in stale.most_common() if i in by_id and i not in after(last_stale)]
    return {
        "repo": repo, "since": since_ms, "until": now_ms,
        "briefings": len(briefings), "lessons_shown": len(shown),
        "most_shown": [{"id": i, "title": title(i), "times": c} for i, c in shown.most_common(top)],
        "shown_stale": [{"id": i, "title": title(i), "times": c} for i, c in stale.most_common(top)],
        "shown_stale_total": len(stale),
        "stale_not_rechecked": [{"id": i, "title": title(i), "times": c} for i, c in stale_open[:top]],
        "stale_not_rechecked_total": len(stale_open),
        "shown_then_quiet": quiet,
        "recorded": sorted(({"id": n.id, "title": n.title, "type": n.type, "at": n.created_at}
                            for n in nodes if (n.created_at or 0) >= since_ms), key=lambda r: r["at"]),
        "retired": retired,
        "checks": {"runs": len(runs), "passed": sum(c.passed for _n, c in runs),
                   "lessons": len({n.id for n, _c in runs}),
                   "failed": [{"id": n.id, "title": n.title, "command": c.command, "outcome": c.outcome,
                               "at": c.at} for n, c in runs if not c.passed]},
        "commits": len(_git_lines(repo_dir, "log", f"--since={since_iso}", "--format=%H")),
        "changed": [{"id": n.id, "title": n.title, "files": n.files} for n in changed],
        "stale_now": [{"id": h.node_id, "title": h.title, "reason": h.reason} for h in hits],
        "drift_checked": checked,
    }


def render_report(r: dict[str, Any]) -> str:
    """The report as Markdown, for a terminal or a pull request."""
    def hm(ms: int) -> str:
        return _ms_iso(ms)[11:16]
    start, end = _ms_iso(r["since"]), _ms_iso(r["until"])
    span = (f"{start[:10]} {start[11:16]} to {end[11:16]}" if start[:10] == end[:10]
            else f"{start[:10]} {start[11:16]} to {end[:10]} {end[11:16]}")
    hours = (r["until"] - r["since"]) / 3_600_000
    out = [f"## okl session report · {r['repo']} · {span} (UTC{start[16:]}, {hours:.1f} h)", ""]
    out.append(f"**Briefings:** {r['briefings']} prompts briefed, {r['lessons_shown']} distinct lessons shown"
               + (f", {r['shown_stale_total']} of them while stale" if r["shown_stale_total"] else "") + ".")
    out += [f"- [{x['id']}] {x['title']} ({x['times']}×)" for x in r["most_shown"]]
    if r["shown_then_quiet"]:
        out.append(f"{r['shown_then_quiet']} of the lessons shown saw no check run or retirement afterwards; "
                   "for advice that is normal, since following it leaves no record.")
    if r["shown_stale"]:
        out.append("\nShown while their code had changed since their last check:")
        out += [f"- [{x['id']}] {x['title']} ({x['times']}×)" for x in r["shown_stale"]]
    out.append(f"\n**Lessons recorded:** {len(r['recorded'])}.")
    out += [f"- {hm(x['at'])} [{x['id']}] ({x['type']}) {x['title']}" for x in r["recorded"]]
    out.append(f"\n**Lessons retired:** {len(r['retired'])}.")
    out += [f"- {hm(x['at'])} [{x['id']}] {x['kind']}" + (f", replaced by [{x['by']}]" if x["by"] else "")
            + f": {x['reason']}" for x in r["retired"]]
    c = r["checks"]
    out.append(f"\n**Checks run:** {c['runs']} across {c['lessons']} lessons, {c['passed']} passed, "
               f"{len(c['failed'])} failed.")
    out += [f"- {hm(x['at'])} [{x['id']}] {x['title']}: `{x['command'][:80]}` {x['outcome']}" for x in c["failed"]]
    out.append(f"\n**Code:** {r['commits']} commits; {len(r['changed'])} lessons govern files changed in the window.")
    out += [f"- [{x['id']}] {x['title']} (governs {x['files']})" for x in r["changed"]]
    if r["stale_not_rechecked_total"]:
        out.append(f"\n**Shown stale, not re-checked:** {r['stale_not_rechecked_total']} lessons. The briefing "
                   "said their code had changed and nothing re-ran their check or retired them afterwards.")
        out += [f"- [{x['id']}] {x['title']} ({x['times']}×)" for x in r["stale_not_rechecked"]]
    if r["stale_now"]:
        out.append(f"\n**Still open:** {len(r['stale_now'])} lessons are stale now. `okl reverify` re-runs their checks.")
        out += [f"- [{x['id']}] {x['title']}: {x['reason']}" for x in r["stale_now"]]
    elif r["drift_checked"]:
        out.append(f"\n**Still open:** nothing; the {r['drift_checked']} lessons that govern files are proven against them.")
    else:
        out.append("\n**Still open:** unknown. Drift could judge no lesson here (none governs a file git can "
                   "attribute), so this report cannot say what is proven.")
    out.append("\nNot covered yet: corrections made with `okl update`, which carry no timestamp, and "
               "anything a shared service logged.")
    return "\n".join(out) + "\n"
