#!/usr/bin/env python3
"""The observations behind REPORT §4ak and #391, as a committed receipt: counts, ids and times only.

They come from two sources that stay off the repository: the store's briefing log (.okl/okl.db,
gitignored) and the working session's transcript (a Claude Code JSONL file). This writes what they
show, with no conversation text:

- every briefing the store logged in the window the code was written, with the lessons it named,
  and whether either missed lesson was among them;
- every time each missed lesson reached the session (a briefing or hook context, never a tool
  result or the agent's own words);
- when the Stop hook's question fired in the session (the stop_hook_summary entries that carry
  it; one is written at every stop), and the time of its once-a-session marker.

    python3 evals/missed_evidence.py <transcript.jsonl> [--since 2026-11-07T19:05Z --until 2026-11-07T19:40Z]
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LESSONS = ("eval-scripts-no-exposure", "seed:rag-defects:qz_fixtures")


def iso(ms: int) -> str:
    """Epoch milliseconds as a UTC minute-second string."""
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def ms(stamp: str) -> int:
    """An ISO time as epoch milliseconds."""
    return int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1000)


def main() -> int:
    """Write the receipt; print its path."""
    ap = argparse.ArgumentParser()
    ap.add_argument("transcript")
    ap.add_argument("--since", default="2026-11-07T19:05:00Z")
    ap.add_argument("--until", default="2026-11-07T19:40:00Z")
    args = ap.parse_args()
    con = sqlite3.connect(REPO / ".okl" / "okl.db")
    rows = con.execute("select at, node_ids from briefing where repo = 'okl' and at between ? and ? order by at",
                       (ms(args.since), ms(args.until))).fetchall()
    con.close()
    briefings = []
    for at, ids in rows:
        try:
            named = json.loads(ids)
        except json.JSONDecodeError:
            named = [i for i in ids.replace(",", " ").split() if i]
        briefings.append({"at": iso(at), "lessons": named, "names_a_missed_lesson": bool(set(named) & set(LESSONS))})
    reached: dict[str, list[str]] = {lesson: [] for lesson in LESSONS}
    stops: list[str] = []
    session = Path(args.transcript).stem
    for line in Path(args.transcript).read_text().splitlines():
        try:
            m = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = m.get("timestamp") or ""
        # A summary is written at every stop; only one that carries okl's question is the hook asking.
        if m.get("type") == "system" and m.get("subtype") == "stop_hook_summary" and ts and "ENCODING LOOP" in line:
            stops.append(ts[:19] + "Z")
        if m.get("type") != "attachment" or not ts:
            continue   # only context the session was given: never a tool result or the agent's own words
        for lesson in LESSONS:
            if lesson in line:
                reached[lesson].append(ts[:19] + "Z")
    # The Stop hook writes its marker under ${TMPDIR:-/tmp}; read the same place, read-only.
    marker = Path(os.environ.get("TMPDIR") or tempfile.gettempdir()) / f"okl-encode-reminder-{session}"
    receipt = {
        "for": "REPORT §4ak; #391", "made": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"), "session": session,
        "briefing_window": {"since": args.since, "until": args.until, "briefings": len(briefings),
                            "naming_a_missed_lesson": sum(b["names_a_missed_lesson"] for b in briefings),
                            "rows": briefings},
        "reached_the_session": {k: sorted(v) for k, v in reached.items()},
        "stop_hook_fired": stops,
        "stop_hook_marker_mtime": (datetime.fromtimestamp(marker.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
                                   if marker.exists() else None),
    }
    out = REPO / "evals" / "results" / f"missed-evidence-{datetime.now(UTC):%Y%m%d-%H%M}.json"
    out.write_text(json.dumps(receipt, indent=1) + "\n")
    print(json.dumps({k: v for k, v in receipt.items() if k != "briefing_window"} |
                     {"briefings": len(briefings), "naming_a_missed_lesson": receipt["briefing_window"]["naming_a_missed_lesson"]},
                     indent=1))
    print(f"receipt: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
