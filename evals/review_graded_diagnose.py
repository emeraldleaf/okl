"""REPORT §4bk: where §4bj's review lost the broken tasks it failed, read from the sessions' saved transcripts.

No model is called. For each of §4bj's review sessions on a broken task it records, from the transcript Claude
Code saved for the session and its sub-agents:
- whether any sub-agent was handed the right lesson, matched as `review_graded.right_checked` matches it, but on
  the full Agent inputs (the rows keep only their first 600 characters);
- how many listed lessons the sub-agents were handed, and where the right lesson sat in the review's list;
- whether the session itself opened the right lesson's file;
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
LISTED = re.compile(r"^- \[([^\]]+)\]", re.M)
LESSON_FILE = re.compile(r"review-lessons/([^\s/`'\"]+?)\.md")


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
    """The session's saved-transcript folder. Claude Code names it after the working directory with every
    character other than a letter, digit or hyphen turned into a hyphen, so a room `okl-4aw-ab_c` is `…-ab-c`."""
    hits = list((Path.home() / ".claude" / "projects").glob(f"*{row['room'].replace('_', '-')}"))
    return hits[0] if len(hits) == 1 else None


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
    agents, opened = [], set()
    for part in _parts(_events(main[0]), "assistant"):
        if part.get("type") != "tool_use":
            continue
        if part.get("name") in ("Agent", "Task"):
            agents.append(part.get("input"))
        else:
            opened.update(LESSON_FILE.findall(json.dumps(part.get("input"))))
    if len(agents) != row["sub_agents"]:
        raise SystemExit(f"{row['id']} review{row['rep']}: {len(agents)} Agent calls, the row counted {row['sub_agents']}")
    blob = json.dumps(agents)
    handed = [lesson for lesson in listed if any(n in blob for n in _names(lesson))]
    if (right in handed) != bool(row["right_checked"]):
        raise SystemExit(f"{row['id']} review{row['rep']}: handed the right lesson disagrees with the run's right_checked")
    final = None
    for meta in sorted(folder.glob("*/subagents/*.meta.json")):
        sub = _events(meta.with_name(meta.name.removesuffix(".meta.json") + ".jsonl"))
        asked = json.dumps(list(_parts(sub, "user"))[:1]) + json.loads(meta.read_text()).get("description", "")
        if any(n in asked for n in _names(right)):
            texts = [p["text"] for p in _parts(sub, "assistant") if p.get("type") == "text"]
            final = texts[-1] if texts else ""
            break
    if (final is not None) != (right in handed):
        raise SystemExit(f"{row['id']} review{row['rep']}: the right lesson's sub-agent transcript was not found")
    return {"id": row["id"], "rep": row["rep"], "passed": row["passed"], "in_sample": bool(task.get("in_sample")),
            "sub_agents": row["sub_agents"], "listed": len(listed),
            "right_position": listed.index(right) + 1 if right in listed else None,
            "handed": len(handed), "right_handed": right in handed, "opened_right": right in opened,
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
        "handed_called_not_broken": [s for s in out if s["verdict"] == "not_broken"],
        "handed_called_broken": [s for s in out if s["verdict"] == "broken"],
    }
    dismissed: dict[str, int] = {}
    for s in steps["handed_called_not_broken"]:
        dismissed[s["id"]] = dismissed.get(s["id"], 0) + 1
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
    }
    receipt = guard.stamp({"section": "4bk", "at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
                           "of_receipt": "review-graded-20261116-0321.json", "inputs": g.inputs(),
                           "verdicts_sha256": hashlib.sha256(VERDICTS.read_bytes()).hexdigest(),
                           "classifier": verdicts["classifier"],
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
