#!/usr/bin/env python3
"""What the warm model costs a prompt (REPORT §4z): the prompt hook's own command,
`okl check --format hook`, timed end to end over real prompts with the model off and on, in
turn, against this repo's store, with the server already loaded; and the server's memory.

    okl warm start --wait 60 && okl warm index      # once
    python3 evals/warm_latency.py                   # writes evals/results/warm-latency-<stamp>.txt

The prompts are the held-out half's sampled task prompts (evals/bench/private/, kept local);
the receipt holds timings only. Each run is a new process, as the hook's is. No model call
leaves this machine.
"""
from __future__ import annotations

import json
import os
import statistics
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "evals" / "bench"))

from okl import core, warm  # noqa: E402


def main() -> int:
    """Time both settings over the same prompts and write the receipt."""
    up = warm.ping()
    if not up:
        sys.exit("ABORT: the warm model is not running; `okl warm start --wait 60` first")
    meta = json.loads((REPO / "evals" / "bench" / "private" / "real-arms-heldout.json").read_text())
    by_id = {json.loads(x)["id"]: json.loads(x)["text"]
             for x in (REPO / "evals" / "bench" / "private" / "prompts.jsonl").read_text().splitlines() if x.strip()}
    texts = [by_id[pid] for kind, pid in meta["chosen"] if kind == "task"]
    # Not OKL_QUIET: the person's line is the check's own word on whether the model ran.
    env = {**os.environ, "OKL_BRIEFING_LOG": "0", "PYTHONPATH": str(REPO / "src")}
    for name in ("OKL_DATABASE_URL", "OKL_QUIET"):
        env.pop(name, None)
    times: dict[str, list[float]] = {"off": [], "on": []}
    for text in texts:
        for setting in ("off", "on"):
            t0 = time.perf_counter()
            r = subprocess.run([sys.executable, "-m", "okl", "check", "--format", "hook", "--warm", setting,
                                "--task", text], cwd=REPO, env=env, capture_output=True, text=True, check=False)
            times[setting].append((time.perf_counter() - t0) * 1000)
            if r.returncode != 0:
                sys.exit(f"ABORT: okl check exited {r.returncode}")
            # A check that falls back exits 0 too, so an "on" timing counts only when the check
            # itself did not say it ran without the model (its line for the person); a prompt with
            # no subject asks nothing (reviews on #300).
            said = json.loads(r.stdout).get("systemMessage", "")
            if setting == "on" and core.briefing_terms(text) and "without the warm model" in said:
                sys.exit("ABORT: a check with the model on was briefed without it; the receipt would time a fallback")
    rss = subprocess.run(["ps", "-o", "rss=", "-p", str(up["pid"])], capture_output=True, text=True,
                         check=False).stdout.strip()
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=REPO, check=False).stdout.strip()
    lines = [f"warm latency · {datetime.now(UTC):%Y-%m-%dT%H:%MZ} · code {commit} · {up['model']} · "
             f"{len(texts)} held-out task prompts · `okl check --format hook`, a new process each",
             f"server: loaded in {up['loaded_s']} s · resident memory {int(rss) / 1024:.0f} MB" if rss else "server: ?",
             f"  {'warm':5} {'median':>8} {'p95':>8} {'max':>8}   (ms, end to end)"]
    for setting, xs in times.items():
        xs = sorted(xs)
        lines.append(f"  {setting:5} {statistics.median(xs):>8.0f} {xs[int(len(xs) * .95)]:>8.0f} {xs[-1]:>8.0f}")
    diffs = sorted(on - off for on, off in zip(times["on"], times["off"], strict=True))
    lines.append(f"  added by the model, per prompt: median {statistics.median(diffs):.0f} ms, "
                 f"p95 {diffs[int(len(diffs) * .95)]:.0f} ms")
    out = REPO / "evals" / "results" / f"warm-latency-{datetime.now(UTC):%Y%m%d-%H%M}.txt"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines) + f"\nreceipt: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
