#!/usr/bin/env python3
"""Write evals/heldout_tasks.jsonl: one harness task per held-out rephrasing (REPORT §4r).

    python3 evals/make_heldout_tasks.py

Each line pairs a rephrasing from evals/heldout_variants.json (written blind from the task
text; see its _provenance) with the signal and defect_node of the authored task it rephrases,
so the blind judge checks the same defect class. Ids read "<task>/<variant>".
"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
tasks = {json.loads(line)["id"]: json.loads(line)
         for line in (REPO / "evals" / "tasks.jsonl").read_text().splitlines() if line.strip()}
held = json.loads((REPO / "evals" / "heldout_variants.json").read_text())
out = [{"id": f"{tid}/{label}", "base": tid, "variant": label, "task": held[tid][label],
        "signal": base["signal"], "defect_node": base["defect_node"]}
       for tid, base in tasks.items() for label in ("ticket", "paraphrase", "bug-report")]
(REPO / "evals" / "heldout_tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in out))
print(f"wrote evals/heldout_tasks.jsonl ({len(out)} tasks)")
