#!/usr/bin/env python3
"""What the Stop hook's review log costs a stop (#464): `okl recap --transcript <t> --log-review`, timed
as the hook runs it, a new process, on the transcripts it is given and on a synthetic worst case.

    python3 evals/review_log_time.py [--runs 3] [--synthetic-mb 146] [--no-synthetic] TRANSCRIPT ...

Each run opens the store, reads the session's transcript and its sub-agents' (the folder beside it, if any),
and writes the row, in a scratch repository with its own store, so no store of yours is touched. The
synthetic transcript is the worst case for the reader: the review starts on its first lines and no prompt
or Stop-hook summary ever closes it, so every line is parsed. A real transcript, which is closed by the
prompt after its review, is mostly skipped by two cheap tests per line.

The receipt holds sizes and seconds only: no transcript content and no path (a real transcript is named by
its rank in size), and it carries the code's commit at the start and at the end of the run
(evals/run_guard.py). The hook cuts the logger off with TERM at 4 s and KILL at 5 s.
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_guard

REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "evals" / "results"
MESSAGE = 'x' * 4000


def synthetic(path: Path, megabytes: float) -> int:
    """Write a transcript of about `megabytes` MB whose review starts at its first lines and never ends:
    a prompt, the review command and its output, then assistant and tool-result lines of about 4.5 KB."""
    def line(**kw: object) -> str:
        return json.dumps(kw) + "\n"

    def stamp(s: int) -> str:
        return f"2026-11-14T10:{s // 60 % 60:02d}:{s % 60:02d}.000Z"

    path.parent.mkdir(parents=True, exist_ok=True)
    size, i = 0, 0
    head = [line(type="user", timestamp=stamp(0), origin={"kind": "human"},
                 message={"role": "user", "content": "fix the bug"}),
            line(type="assistant", timestamp=stamp(1), message={
                "id": "m0", "role": "assistant", "model": "claude-opus-5-5", "usage": {"output_tokens": 1},
                "content": [{"type": "tool_use", "id": "t0", "name": "Bash",
                             "input": {"command": "okl check --change"}}]}),
            line(type="user", timestamp=stamp(2), message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": "t0", "content":
                    "## OKL review after writing: 3 file(s) changed since main\n\nThis review lists 50 lesson(s).\n"}]})]
    with path.open("w") as f:
        for text in head:
            f.write(text)
            size += len(text)
        while size < megabytes * 1e6:
            for text in (line(type="assistant", timestamp=stamp(3 + i % 3000), message={
                    "id": f"m{i + 1}", "role": "assistant", "model": "claude-opus-5-5",
                    "usage": {"input_tokens": 3, "output_tokens": 400, "cache_read_input_tokens": 90000},
                    "content": [{"type": "tool_use", "id": f"t{i + 1}", "name": "Bash", "input": {"command": "ls"}}]}),
                         line(type="user", timestamp=stamp(3 + i % 3000), message={"role": "user", "content": [
                             {"type": "tool_result", "tool_use_id": f"t{i + 1}", "content": MESSAGE}]})):
                f.write(text)
                size += len(text)
            i += 1
    return i


def time_one(transcript: Path, scratch: Path, runs: int) -> dict[str, object]:
    """`okl recap --log-review` on `transcript`, `runs` times, each a new process in the scratch repo."""
    env = {"PATH": os.environ["PATH"], "HOME": str(scratch), "PYTHONPATH": str(REPO / "src")}
    seconds, codes = [], []
    for _ in range(runs):
        start = time.perf_counter()
        done = subprocess.run([sys.executable, "-m", "okl", "recap", "--transcript", str(transcript),
                               "--log-review"], cwd=scratch / "repo", env=env, capture_output=True)
        seconds.append(round(time.perf_counter() - start, 2))
        codes.append(done.returncode)
    size = transcript.stat().st_size
    return {"bytes": size, "megabytes": round(size / 1e6, 1), "seconds": seconds,
            "median_seconds": round(statistics.median(seconds), 2), "exit_codes": codes}


def main() -> int:
    """Time the logger, write evals/results/review-log-time-<stamp>.json."""
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("transcripts", nargs="*", type=Path, help="real transcripts to time")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--synthetic-mb", type=float, default=146.0, help="size of the synthetic worst case")
    ap.add_argument("--no-synthetic", action="store_true")
    args = ap.parse_args()
    run = run_guard.start()
    cases: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="okl-review-log-time-") as tmp:
        scratch = Path(tmp)
        (scratch / "repo" / ".okl").mkdir(parents=True)
        (scratch / "repo" / ".okl" / "config.json").write_text(json.dumps({"repo": "timing"}))
        subprocess.run(["git", "init", "-q", str(scratch / "repo")], check=True)
        if not args.no_synthetic:
            made = synthetic(scratch / "projects" / "synthetic.jsonl", args.synthetic_mb)
            case = time_one(scratch / "projects" / "synthetic.jsonl", scratch, args.runs)
            cases.append({"label": "synthetic worst case", "messages": made, **case})
        for rank, t in enumerate(sorted(args.transcripts, key=lambda p: -p.stat().st_size), 1):
            cases.append({"label": f"real transcript {rank} by size", **time_one(t, scratch, args.runs)})
    real = [c for c in cases if str(c["label"]).startswith("real")]
    receipt: dict[str, object] = {
        "experiment": "review log read time (#464)",
        "date": datetime.now(UTC).strftime("%Y-%m-%dT%H:%MZ"),
        "command": "okl recap --transcript <t> --log-review, a new process each, in a scratch repository",
        "runs": args.runs,
        "note": "sizes and seconds only; no transcript content and no path. The Stop hook cuts the logger "
                "off with TERM at 4 s and KILL at 5 s.",
        "cases": cases,
    }
    if real:
        receipt["largest_real_megabytes"] = real[0]["megabytes"]
        receipt["largest_real_median_seconds"] = real[0]["median_seconds"]
    synth = next((c for c in cases if c["label"] == "synthetic worst case"), None)
    if synth:
        receipt["synthetic_megabytes"] = synth["megabytes"]
        receipt["synthetic_median_seconds"] = synth["median_seconds"]
    receipt = run.stamp(receipt)
    out = RESULTS / f"review-log-time-{datetime.now(UTC).strftime('%Y%m%d-%H%M')}.json"
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(out)
    for c in cases:
        print(f"  {c['label']}: {c['megabytes']} MB, median {c['median_seconds']} s ({c['seconds']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
