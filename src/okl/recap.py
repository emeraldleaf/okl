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
import statistics
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from . import reviewlog
from .core import governing
from .drift import SNAPSHOT_FILE
from .store import RETIRED_STATUSES, Node, ReviewRun, Store

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
    from datetime import UTC, datetime
    dt = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
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


# --- the review log (#464) -------------------------------------------------------------------------
#
# What each session's review after writing did, read from the Claude Code transcript at the end of
# the session and kept in the local store, so the default can be judged on real sessions. The agent
# runs the review and okl calls no model, so only the transcript sees it. The parser is reviewlog.py;
# this is the part that reaches the store and reads the log back.


def log_review(store: Store, repo: str, transcript: str | Path, repo_dir: str | None = None
               ) -> tuple[reviewlog.ReviewReading, bool]:
    """Read `transcript` and write the session's review row; (the reading, whether a row was written).

    A session that neither asked for a review nor ran one is not written. A session logged again
    replaces its row: the transcript has grown since the stop before.
    """
    known = {n.id for n in store.all_nodes()}
    reading = reviewlog.read_review(transcript, repo_dir=repo_dir, known_ids=known)
    if not reading.loggable:
        return reading, False
    store.log_review(reading.session, repo, asked=reading.asked, ran=reading.ran,
                     files_changed=reading.files_changed, lessons_listed=reading.lessons_listed,
                     tokens=reading.tokens, cache_read_tokens=reading.cache_read_tokens,
                     duration_s=reading.duration_s, failed_launches=reading.failed_launches,
                     checks=reading.checks, pages_total=reading.pages_total, pages_read=reading.pages_read)
    return reading, True


def _checks_of(rows: list[ReviewRun]) -> list[dict[str, Any]]:
    """The checks of the reviews that ran: sub-agents the review gave at least one lesson."""
    return [c for r in rows if r.ran for c in r.checks if c.get("lessons")]


def _spread(values: list[int]) -> dict[str, float] | None:
    return ({"median": statistics.median(values), "mean": round(statistics.fmean(values), 1),
             "max": max(values)} if values else None)


def reviews_report(store: Store, repo: str, *, since_ms: int = 0, top: int = 5) -> dict[str, Any]:
    """The review log as data: how often the review was asked for and run, what it checked, how
    often a check ended in an edit, what it cost, and per lesson how often it was checked and acted on."""
    rows = [r for r in store.reviews(repo) if r.at >= since_ms]
    ran = [r for r in rows if r.ran]
    titles = {n.id: n.title for n in store.all_nodes()}
    checks = _checks_of(rows)
    read = [c for c in checks if c.get("read")]
    per_review = [len({i for c in r.checks for i in c.get("lessons", [])}) for r in ran]
    by_lesson: dict[str, dict[str, int]] = {}
    for c in checks:
        for i in c["lessons"]:
            t = by_lesson.setdefault(i, {"checked": 0, "read": 0, "edited": 0})
            t["checked"] += 1
            t["read"] += bool(c.get("read"))
            t["edited"] += bool(c.get("read") and c.get("edited"))
    ranked = sorted(by_lesson.items(), key=lambda kv: (-kv[1]["checked"], -kv[1]["edited"], kv[0]))
    return {
        "repo": repo, "since": since_ms, "sessions": len(rows),
        "asked": sum(r.asked for r in rows), "asked_and_ran": sum(r.asked and r.ran for r in rows),
        "asked_not_run": sum(r.asked and not r.ran for r in rows),
        "ran_unasked": sum(r.ran and not r.asked for r in rows),
        "ran": len(ran),
        "ran_on_changed_files": sum((r.files_changed or 0) > 0 for r in ran),
        "files_changed_unread": sum(r.files_changed is None for r in ran),
        "lessons_per_review": _spread(per_review),
        "reviews_without_subagent": sum(not r.checks for r in ran),
        "checks": len(checks), "checks_read": len(read), "checks_unread": len(checks) - len(read),
        "checks_acted_on": sum(1 for c in read if c.get("edited")),
        "subagents_without_lesson": sum(1 for r in ran for c in r.checks if not c.get("lessons")),
        "tokens": _spread([r.tokens for r in ran if r.tokens is not None]),
        "cache_read_tokens": _spread([r.cache_read_tokens for r in ran if r.cache_read_tokens is not None]),
        "failed_launches": sum(r.failed_launches for r in ran),
        "paged": sum((r.pages_total or 0) > 1 for r in ran),
        "paged_read_every_page": sum((r.pages_total or 0) > 1 and r.pages_read == r.pages_total for r in ran),
        "duration_s": _spread([r.duration_s for r in ran if r.duration_s is not None]),
        "lessons": [{"id": i, "title": titles.get(i, "(no longer in the store)"), **t}
                    for i, t in ranked[:top]],
        "lessons_total": len(ranked),
    }


def _pct(part: int, whole: int) -> str:
    return f"{round(100 * part / whole)}%" if whole else "none"


def _stat(label: str, s: dict[str, float] | None, unit: str) -> str:
    if not s:
        return f"{label}: not readable for any review."
    return (f"{label}: median {s['median']:,.0f}{unit}, mean {s['mean']:,.0f}{unit}, "
            f"largest {s['max']:,.0f}{unit}.")


def _n(count: int, word: str) -> str:
    """A count and its noun, singular for one: "1 session", "2 sessions"."""
    return f"{count} {word}" + ("" if count == 1 else "s")


def render_reviews(r: dict[str, Any]) -> str:
    """The review log as Markdown, for a terminal or a pull request."""
    out = [f"## okl review log · {r['repo']} · {_n(r['sessions'], 'session')} logged", "",
           "The review after writing, read from the transcripts of Claude Code sessions. Other agents "
           "leave no transcript okl can read, so this covers Claude Code sessions only. A session "
           "that neither asked for the review nor ran one is not logged."]
    if not r["sessions"]:
        out += ["", "Nothing is logged for this repo yet. The Stop hook logs a session at a later stop "
                "once the review was asked for or run."]
        return "\n".join(out) + "\n"
    more = f" ({r['ran_unasked']} more ran without being asked)" if r["ran_unasked"] else ""
    unread = (f" ({r['files_changed_unread']} where the review's own output could not be read)"
              if r["files_changed_unread"] else "")
    out += ["",
            f"**Asked for:** {_n(r['asked'], 'session')}. It ran in {r['asked_and_ran']} "
            f"({_pct(r['asked_and_ran'], r['asked'])}) and was skipped in {r['asked_not_run']}{more}.",
            f"**Reviews run:** {r['ran']}, {r['ran_on_changed_files']} against sessions that changed "
            f"files{unread}."]
    spread = r["lessons_per_review"]
    if spread:
        out.append(f"**Lessons checked per review:** median {spread['median']:g}, mean {spread['mean']:g}, "
                   f"most {spread['max']:g}; {_n(r['reviews_without_subagent'], 'review')} started no sub-agent.")
    out.append(f"**Checks:** {r['checks']} (a sub-agent given a lesson); {r['checks_unread']} could not be "
               f"read, and of the {r['checks_read']} that could, {r['checks_acted_on']} "
               f"({_pct(r['checks_acted_on'], r['checks_read'])}) "
               f"{'was' if r['checks_acted_on'] == 1 else 'were'} followed by an edit.")
    if r["subagents_without_lesson"]:
        n = r["subagents_without_lesson"]
        out.append(f"{_n(n, 'sub-agent')} the review started named no lesson and "
                   f"{'is' if n == 1 else 'are'} not counted as checks.")
    tokens = _stat("Tokens", r["tokens"], "")
    if r["cache_read_tokens"]:
        cache = r["cache_read_tokens"]
        tokens = (tokens.rstrip(".") + f" (cache reads, which a call makes of the whole context and which cost "
                  f"far less, not counted: median {cache['median']:,.0f}, largest {cache['max']:,.0f}).")
    out += ["", f"**Cost per review.** {tokens} {_stat('Duration', r['duration_s'], ' s')}"]
    if r["failed_launches"]:
        n = r["failed_launches"]
        out.append(f"{n} Agent {'call' if n == 1 else 'calls'} came back as an error and started no sub-agent.")
    if r.get("paged"):
        out.append(f"**Pages:** {_n(r['paged'], 'review')} came in pages; {r['paged_read_every_page']} "
                   f"({_pct(r['paged_read_every_page'], r['paged'])}) read every page.")
    if r["lessons"]:
        out += ["", f"**Per lesson**, most checked first ({_n(r['lessons_total'], 'lesson')} checked):"]
        out += [f"- [{x['id']}] {x['title']}: checked {x['checked']}×, {x['edited']} of the {x['read']} "
                "read followed by an edit" for x in r["lessons"]]
        if r["lessons_total"] > len(r["lessons"]):
            out.append(f"  and {r['lessons_total'] - len(r['lessons'])} more: `--limit` shows more.")
    out += ["", "An edit after a check means the review acted on that lesson, not that it caught a break: "
            "whether the edit fixed a real break is not something this log can tell. A check that opened "
            "several lessons counts its edit for each."]
    return "\n".join(out) + "\n"
