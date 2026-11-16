"""REPORT §4bk: where §4bj's review lost the broken tasks it failed, read from the sessions' saved transcripts.

No model is called. For each of §4bj's review sessions on a broken task it records, from the transcript Claude
Code saved for the session and its sub-agents:
- whether any sub-agent was handed the right lesson, matched as `review_graded.right_checked` matches it, but on
  the full Agent inputs (the rows keep only their first 600 characters);
- how many listed lessons the sub-agents were handed, and where the right lesson sat in the review's list;
- whether the session itself opened the right lesson's file, whether the right lesson's line in the list was in
  any tool result the session got back, and whether a read of the list came back cut to Claude Code's preview
  (its tool output past about 30,000 characters is saved to a file, and the session sees the first 2 KB);
- what the sub-agent handed the right lesson concluded: the class in `VERDICTS`, assigned by an agent (Claude)
  reading each final message, not blind to whether the session passed.

The transcripts and rows are private (`evals/bench/private`, `~/.claude/projects`), so this runs only where §4bj
ran; the receipt keeps ids, counts and classes, no session text.

    python3 evals/review_graded_diagnose.py [--receipt]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from statistics import median
from typing import Any

import review_graded as g
import run_guard

REPO = Path(__file__).resolve().parent.parent
VERDICTS = REPO / "evals" / "review-graded-4bj-verdicts.json"
FIT = REPO / "evals" / "review-graded-4bj-fit.json"   # an agent's reading of each right lesson against its defect
LISTED = re.compile(r"^- \[([^\]]+)\]", re.M)
LESSON_FILE = re.compile(r"review-lessons/([^\s/`'\"]+?)\.md")
PREVIEW = "<persisted-output>"          # Claude Code's mark on a tool result cut to a preview
LIST_HEADING = "OKL review after writing"   # the first line of the review's list


def _events(path: Path) -> list[dict[str, Any]]:
    out = []
    with path.open() as f:
        for line in f:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def _parts(events: list[dict[str, Any]], role: str) -> Iterator[dict[str, Any]]:
    """The content parts of every `role` message; a bare string counts as one text part."""
    for e in events:
        if e.get("type") != role:
            continue
        content = (e.get("message") or {}).get("content") or []
        if isinstance(content, str):
            yield {"type": "text", "text": content}
            continue
        yield from (c for c in content if isinstance(c, dict))


def _names(lesson: str) -> tuple[str, str]:
    return lesson, lesson.replace("/", "_")


def _room(row: dict[str, Any]) -> Path | None:
    """The session's saved-transcript folder. Claude Code names it after the working directory with its
    separators and underscores turned into hyphens, so a room `okl-4aw-ab_c` is `…-okl-4aw-ab-c`; a room name
    is a temporary directory's, which holds no other character that changes."""
    hits = list((Path.home() / ".claude" / "projects").glob(f"*{row['room'].replace('_', '-')}"))
    return hits[0] if len(hits) == 1 else None


def _result_text(part: dict[str, Any]) -> str:
    content = part.get("content")
    if isinstance(content, str):
        return content
    return "\n".join(c.get("text", "") for c in content or [] if isinstance(c, dict))


def _final(events: list[dict[str, Any]]) -> str:
    """The text of the last assistant message that has any text."""
    for e in reversed(events):
        if e.get("type") != "assistant":
            continue
        texts = [p["text"] for p in _parts([e], "assistant") if p.get("type") == "text"]
        if texts:
            return "\n".join(texts)
    return ""


def session(row: dict[str, Any], task: dict[str, Any]) -> dict[str, Any]:
    """One review session's picking and checking, from its transcripts."""
    right = task["lesson"]
    listed = LISTED.findall((g.BUILT / row["id"] / "REVIEW.md").read_text())
    folder = _room(row)
    if folder is None:
        raise SystemExit(f"{row['id']} review{row['rep']}: no single transcript folder for room {row['room']}")
    main = list(folder.glob("*.jsonl"))
    if len(main) != 1:
        raise SystemExit(f"{row['id']} review{row['rep']}: {len(main)} main transcripts")
    events = _events(main[0])
    agents: dict[str, Any] = {}
    opened: set[str] = set()
    for part in _parts(events, "assistant"):
        if part.get("type") != "tool_use":
            continue
        if part.get("name") in ("Agent", "Task"):
            agents.setdefault(part["id"], part.get("input"))
        else:
            opened.update(LESSON_FILE.findall(json.dumps(part.get("input"))))
    results = [_result_text(p) for p in _parts(events, "user") if p.get("type") == "tool_result"]
    saw_line = any(f"[{right}]" in t for t in results)
    list_cut = any(PREVIEW in t and LIST_HEADING in t for t in results)
    if len(agents) != row["sub_agents"]:
        raise SystemExit(f"{row['id']} review{row['rep']}: {len(agents)} Agent calls, the row counted {row['sub_agents']}")
    blob = json.dumps(list(agents.values()))
    handed = [lesson for lesson in listed if any(n in blob for n in _names(lesson))]
    if (right in handed) != bool(row["right_checked"]):
        raise SystemExit(f"{row['id']} review{row['rep']}: handed the right lesson disagrees with the run's right_checked")
    # The sub-agent handed the right lesson, joined on the Agent call's id: exactly one, or the session is refused.
    given = {i for i, a in agents.items() if any(n in json.dumps(a) for n in _names(right))}
    metas = [m for m in folder.glob("*/subagents/*.meta.json") if json.loads(m.read_text()).get("toolUseId") in given]
    if len(given) > 1 or len(metas) != len(given):
        raise SystemExit(f"{row['id']} review{row['rep']}: {len(given)} Agent calls named the right lesson, "
                         f"{len(metas)} sub-agent transcripts matched")
    final = _final(_events(metas[0].with_name(metas[0].name.removesuffix(".meta.json") + ".jsonl"))) if metas else None
    return {"id": row["id"], "rep": row["rep"], "passed": row["passed"], "in_sample": bool(task.get("in_sample")),
            "sub_agents": row["sub_agents"], "listed": len(listed),
            "right_position": listed.index(right) + 1 if right in listed else None,
            "handed": len(handed), "right_handed": right in handed, "opened_right": right in opened,
            "saw_right_line": saw_line, "list_cut": list_cut,
            "final_sha256": hashlib.sha256(final.encode()).hexdigest()[:16] if final is not None else None}


def diagnose(write: bool) -> int:
    """Every review session on a broken task, the losses by step, and with --receipt the receipt."""
    guard = run_guard.start()
    tasks = {t["id"]: t for t in g.tasks()}
    rows = [r for r in g.kept().values() if r["arm"] == "review" and not tasks[r["id"]].get("needs_nothing")]
    verdicts = json.loads(VERDICTS.read_text())
    out = []
    for r in sorted(rows, key=lambda r: (r["id"], r["rep"])):
        s = session(r, tasks[r["id"]])
        key = f"{r['id']} review{r['rep']}"
        s["verdict"] = verdicts["sessions"].get(key)
        s["broken_in_part"] = key in verdicts["broken_in_part"]
        if (s["verdict"] is None) == s["right_handed"]:
            raise SystemExit(f"{key}: a handed session needs a verdict class, and only a handed one has one")
        out.append(s)
    count = lambda pred: sum(1 for s in out if pred(s))  # noqa: E731
    by_task: dict[str, int] = {}
    for s in out:
        by_task[s["id"]] = by_task.get(s["id"], 0) + s["right_handed"]
    steps = {
        "never_handed": [s for s in out if not s["right_handed"]],
        "never_handed_no_sub_agent": [s for s in out if not s["right_handed"] and s["sub_agents"] == 0],
        "never_handed_with_sub_agents": [s for s in out if not s["right_handed"] and s["sub_agents"] > 0],
        "never_handed_never_saw_line": [s for s in out if not s["right_handed"] and not s["saw_right_line"]],
        "never_handed_with_sub_agents_saw_line": [s for s in out if not s["right_handed"] and s["sub_agents"] > 0
                                                  and s["saw_right_line"]],
        "handed_called_not_broken": [s for s in out if s["verdict"] == "not_broken"],
        "handed_called_broken": [s for s in out if s["verdict"] == "broken"],
    }
    dismissed: dict[str, int] = {}
    for s in steps["handed_called_not_broken"]:
        dismissed[s["id"]] = dismissed.get(s["id"], 0) + 1
    both_failed = sorted(t for t, v in dismissed.items() if v == 2 and not any(s["passed"] for s in out if s["id"] == t))
    fit = json.loads(FIT.read_text())
    never = sorted(t for t, v in by_task.items() if v == 0)
    if sorted(fit["never_handed"]) != never or sorted(fit["dismissed_both_failed"]) != both_failed:
        raise SystemExit(f"{FIT.name} reads other tasks than the sessions give: {never}, {both_failed}")
    fits = {k: {c: sum(1 for x in fit[k].values() if x[0] == c) for c in sorted({x[0] for x in fit[k].values()})}
            for k in ("never_handed", "dismissed_both_failed")}
    summary = {
        "sessions": len(out), "passed": count(lambda s: s["passed"]),
        "steps": {k: {"sessions": len(v), "passed": sum(s["passed"] for s in v)} for k, v in steps.items()},
        "tasks_handed_in": {str(k): sum(1 for v in by_task.values() if v == k) for k in (2, 1, 0)},
        "never_handed_tasks": sorted(t for t, v in by_task.items() if v == 0),
        "opened_right_when_never_handed": {
            "no_sub_agent": count(lambda s: not s["right_handed"] and s["sub_agents"] == 0 and s["opened_right"]),
            "with_sub_agents": count(lambda s: not s["right_handed"] and s["sub_agents"] > 0 and s["opened_right"])},
        "handed_median_when_never_handed_with_sub_agents": median(
            s["handed"] for s in steps["never_handed_with_sub_agents"]),
        "right_position_share_median": {
            "handed": round(median(s["right_position"] / s["listed"] for s in out if s["right_handed"]), 2),
            "never_handed": round(median(s["right_position"] / s["listed"] for s in out if not s["right_handed"]), 2)},
        "dismissed_in_both_sessions": sorted(t for t, v in dismissed.items() if v == 2),
        "dismissed_in_both_sessions_both_failed": both_failed,
        "fit": fits,
        "list_cut": {"sessions": count(lambda s: s["list_cut"]),
                     "passed": count(lambda s: s["list_cut"] and s["passed"])},
        "never_saw_line": {"with_sub_agents": count(lambda s: not s["saw_right_line"] and s["sub_agents"] > 0),
                           "no_sub_agent": count(lambda s: not s["saw_right_line"] and s["sub_agents"] == 0),
                           "handed": count(lambda s: not s["saw_right_line"] and s["right_handed"])},
    }
    receipt = guard.stamp({"section": "4bk", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                           "of_receipt": "review-graded-20261116-0321.json", "inputs": g.inputs(),
                           "verdicts_sha256": hashlib.sha256(VERDICTS.read_bytes()).hexdigest(),
                           "fit_sha256": hashlib.sha256(FIT.read_bytes()).hexdigest(),
                           "classifier": verdicts["classifier"],
                           # No model is called here; without this the guard would stamp sandbox.clean_env, set by
                           # an import, not by any call (#479).
                           "model_env": "none: no model is called",
                           "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                           "summary": summary, "sessions": out})
    print(json.dumps(summary, indent=1))
    if write:
        dest = REPO / "evals" / "results" / f"review-graded-diagnosis-{datetime.now(UTC):%Y%m%d-%H%M}.json"
        dest.write_text(json.dumps(receipt, indent=1) + "\n")
        print(f"receipt: {dest.relative_to(REPO)}")
    return 0


def main() -> int:
    """Run the diagnosis."""
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--receipt", action="store_true")
    return diagnose(ap.parse_args().receipt)


if __name__ == "__main__":
    raise SystemExit(main())
