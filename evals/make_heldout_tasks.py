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


def main() -> int:
    """Everything make_heldout_tasks does when run, which it did on import before #486: importing it now does nothing."""
    tasks = {json.loads(line)["id"]: json.loads(line)
             for line in (REPO / "evals" / "tasks.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    held = json.loads((REPO / "evals" / "heldout_variants.json").read_text(encoding="utf-8"))
    out = [{"id": f"{tid}/{label}", "base": tid, "variant": label, "task": held[tid][label],
            "signal": base["signal"], "defect_node": base["defect_node"]}
           for tid, base in tasks.items() for label in ("ticket", "paraphrase", "bug-report")]
    (REPO / "evals" / "heldout_tasks.jsonl").write_text("".join(json.dumps(t, ensure_ascii=False) + "\n" for t in out), encoding="utf-8")
    print(f"wrote evals/heldout_tasks.jsonl ({len(out)} tasks)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
