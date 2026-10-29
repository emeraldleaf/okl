#!/usr/bin/env python3
"""What the warm model holds in memory, prompt by prompt (REPORT §4z): resident memory after
loading, then after each of a series of real prompts, in a fresh process, as the server loads
and serves it. Run once with ONNX Runtime's CPU memory arena as fastembed sets it and once with
it off, to tell a one-time cost from growth.

    python3 evals/warm_memory.py          # writes evals/results/warm-memory-<stamp>.txt

The prompts are the extracted task prompts (evals/bench/private/, kept local); the receipt holds
megabytes only.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKS = (1, 2, 5, 20, 100, 300)

CHILD = """
import json, os, subprocess, sys
sys.path.insert(0, %(src)r)
from fastembed import TextEmbedding
from okl import hub, warm
warm.load_model()                                    # registers the int8 file, as the server does
def rss():
    return int(subprocess.run(["ps", "-o", "rss=", "-p", str(os.getpid())], capture_output=True, text=True).stdout) / 1024
kw = {} if %(arena)r == "default" else {"enable_cpu_mem_arena": False}
m = TextEmbedding(model_name=warm.MODEL_ID, cache_dir=str(hub.model_cache_dir()), **kw)
out = {"load": rss()}
texts = [json.loads(x)["text"] for x in open(%(prompts)r)][:max(%(marks)r)]
for i, t in enumerate(texts, 1):
    list(m.embed([warm.QUERY.format(t)]))
    if i in %(marks)r:
        out[str(i)] = rss()
print(json.dumps(out))
"""


def main() -> int:
    """Trace both settings in fresh processes and write the receipt."""
    prompts = REPO / "evals" / "bench" / "private" / "prompts.jsonl"
    env = {**os.environ, "HF_HUB_OFFLINE": "1"}
    env.pop("OKL_DATABASE_URL", None)
    commit = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], capture_output=True, text=True,
                            cwd=REPO, check=False).stdout.strip()
    lines = [f"warm memory · {datetime.now(UTC):%Y-%m-%dT%H:%MZ} · code {commit} · resident MB in a fresh process, "
             f"after loading and after the n-th real prompt",
             "  arena     load  " + "  ".join(f"{n:>5}" for n in MARKS)]
    for arena in ("default", "off"):
        code = CHILD % {"src": str(REPO / "src"), "arena": arena, "prompts": str(prompts), "marks": MARKS}
        r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, check=False)
        if r.returncode != 0:
            sys.exit(f"ABORT: the {arena} run failed:\n{r.stderr[-600:]}")
        got = json.loads(r.stdout.strip().splitlines()[-1])
        lines.append(f"  {arena:8} {got['load']:>5.0f}  " + "  ".join(f"{got[str(n)]:>5.0f}" for n in MARKS))
    out = REPO / "evals" / "results" / f"warm-memory-{datetime.now(UTC):%Y%m%d-%H%M}.txt"
    out.write_text("\n".join(lines) + "\n")
    print("\n".join(lines) + f"\nreceipt: {out.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
