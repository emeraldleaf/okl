#!/usr/bin/env python3
"""What stemming costs a prompt (REPORT §4ad): the prompt hook's own command,
`okl check --format hook --decision tiered --warm off`, timed end to end over real prompts,
unstemmed and stemmed in turn.

    python3 evals/stem_latency.py      # writes evals/results/stem-latency-<stamp>.txt
    OKL_DATABASE_URL=sqlite:////path/to/okl.db python3 evals/stem_latency.py   # another store, copied

Each setting runs against its own copy of the store, its index built for that setting before any
timing, so no timed run rebuilds an index and the live store is only read through SQLite's
backup, never opened by this code (opening it with another tokenizer would rebuild its index
under the installed release). The unstemmed setting is the index's unicode61 tokenizer with
§4w's line, as the product ships; the stemmed one is §4ad's. Both are set explicitly. The prompts are the held-out half's sampled task prompts (evals/bench/private/, kept
local); the receipt holds timings only. Each run is a new process, as the hook's is.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRIVATE = REPO / "evals" / "bench" / "private"
sys.path.insert(0, str(REPO / "src"))
from okl.client import _find_config  # noqa: E402 - the client's own rule for which config applies
from okl.store import fts_tokenizer  # noqa: E402

# Each setting enters the CLI through the same `python -c`, so both pay the same start-up.
RUN = "import runpy, sys; sys.argv[0] = 'okl'; runpy.run_module('okl', run_name='__main__', alter_sys=True)"
TOKENIZE = {"unstemmed": "unicode61", "stemmed": "porter unicode61"}
LINE = {"unstemmed": 2.0017173, "stemmed": 3.0014486}
SETTINGS = {s: f"import okl.store, okl.decide; okl.store.FTS_TOKENIZE = {TOKENIZE[s]!r}; "
               f"okl.decide.CALIBRATED_LINE = {LINE[s]}; " + RUN for s in TOKENIZE}


def index_tokenizer(db: Path) -> str | None:
    """The tokenizer `db`'s full-text index was built with (none named is unicode61, as the store
    reads it), or None when it has no full-text index: a SQLite without FTS5 searches by LIKE,
    and its timings would measure neither setting (review on #309)."""
    with contextlib.closing(sqlite3.connect(db)) as c:
        row = c.execute("SELECT sql FROM sqlite_master WHERE name = 'node_fts'").fetchone()
    return fts_tokenizer(row[0]) if row else None


def store_copy(live: Path, where: Path, setting: str, env: dict[str, str]) -> Path:
    """A copy of the live store with its index built for `setting`, read through SQLite's
    backup so a write the live store has in flight is not copied half done."""
    dst = where / f"{setting}.db"
    src, out = sqlite3.connect(f"file:{live}?mode=ro", uri=True), sqlite3.connect(dst)
    try:
        src.backup(out)
    finally:
        src.close()
        out.close()
    # One untimed check builds the index the setting wants.
    subprocess.run([sys.executable, "-c", SETTINGS[setting], "check", "--task", "warm up the index", "--warm", "off"],
                   env={**env, "OKL_DATABASE_URL": f"sqlite:///{dst}"}, cwd=REPO, capture_output=True, check=True)
    if index_tokenizer(dst) != TOKENIZE[setting]:
        sys.exit(f"ABORT: the {setting} copy's index is not built with {TOKENIZE[setting]!r}, so its timings "
                 "would not measure that setting")
    return dst


def child_env(repo: Path = REPO) -> dict[str, str]:
    """The environment every run gets: this checkout's code, no briefing log, and nothing that
    picks a store or a service, so each run reads only the copy it is handed. A service named in
    the environment or the config the client finds makes it go remote whatever OKL_DATABASE_URL
    says, and both arms would time the service (review on #309)."""
    cfg = _find_config(repo)
    if cfg and json.loads(cfg.read_text()).get("service_url"):
        sys.exit(f"ABORT: {cfg} names a service, so the runs would time it, not the store copies")
    env = {**os.environ, "OKL_BRIEFING_LOG": "0", "PYTHONPATH": str(repo / "src")}
    for name in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_QUIET", "OKL_DECISION"):
        env.pop(name, None)
    return env


def source_store(repo: Path = REPO) -> Path:
    """The store the CLI would open here: the SQLite file OKL_DATABASE_URL names, else the one
    beside the nearest .okl/config.json, found as the client finds it. A URL that is not SQLite,
    or no config at all, stops the run: this copies SQLite files only (review on #309)."""
    url = os.environ.get("OKL_DATABASE_URL", "")
    if url:
        if not url.startswith("sqlite:///"):
            sys.exit("ABORT: OKL_DATABASE_URL names a store that is not SQLite; this copies only SQLite files")
        return Path(url.removeprefix("sqlite:///"))
    cfg = _find_config(repo)
    if cfg is None:
        sys.exit(f"ABORT: no .okl/config.json at or above {repo}, so there is no store to copy")
    return cfg.parent / "okl.db"


def main() -> int:
    """Time both settings over the same prompts, alternating which runs first, and write the receipt."""
    meta = json.loads((PRIVATE / "real-arms-heldout.json").read_text())
    by_id = {json.loads(x)["id"]: json.loads(x)["text"]
             for x in (PRIVATE / "prompts.jsonl").read_text().splitlines() if x.strip()}
    texts = [by_id[pid] for kind, pid in meta["chosen"] if kind == "task"]
    live = source_store()
    env = child_env()
    times: dict[str, list[float]] = {s: [] for s in SETTINGS}
    with tempfile.TemporaryDirectory() as tmp:
        dbs = {s: store_copy(live, Path(tmp), s, env) for s in SETTINGS}
        for i, text in enumerate(texts):
            for setting in (list(SETTINGS) if i % 2 == 0 else list(reversed(SETTINGS))):
                cmd = [sys.executable, "-c", SETTINGS[setting], "check", "--format", "hook", "--warm", "off",
                       "--decision", "tiered", "--task", text]
                t0 = time.perf_counter()
                r = subprocess.run(cmd, cwd=REPO, env={**env, "OKL_DATABASE_URL": f"sqlite:///{dbs[setting]}"},
                                   capture_output=True, text=True, check=False)
                times[setting].append((time.perf_counter() - t0) * 1000)
                if r.returncode != 0:
                    sys.exit(f"ABORT: okl check exited {r.returncode} under {setting}")
        c = sqlite3.connect(dbs["stemmed"])
        try:
            records = c.execute("SELECT count(*) FROM node").fetchone()[0]
        finally:
            c.close()
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=REPO, check=False).stdout.strip()
    lines = [f"stem latency · {datetime.now(UTC):%Y-%m-%dT%H:%MZ} · code {commit} · {len(texts)} held-out task "
             f"prompts · `okl check --format hook --decision tiered --warm off`, a new process each, "
             f"against a copy of the store ({records} records)",
             f"  {'setting':10} {'median':>8} {'p95':>8} {'max':>8}   (ms, end to end)"]
    for setting, xs in times.items():
        xs = sorted(xs)
        lines.append(f"  {setting:10} {statistics.median(xs):>8.0f} {xs[int(len(xs) * .95)]:>8.0f} {xs[-1]:>8.0f}")
    diffs = sorted(b - a for a, b in zip(times["unstemmed"], times["stemmed"], strict=True))
    lines.append(f"  added by stemming, per prompt: median {statistics.median(diffs):.0f} ms, "
                 f"p95 {diffs[int(len(diffs) * .95)]:.0f} ms")
    out = REPO / "evals" / "results" / f"stem-latency-{datetime.now(UTC):%Y%m%d-%H%M}.txt"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines) + f"\nreceipt: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
