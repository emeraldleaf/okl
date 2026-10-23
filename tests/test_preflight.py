"""evals/preflight.py gates an A/B on the briefing the run will use, under the run's own interests."""
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# The value receipts ab-20260903-1323 through ab-20261011-2254 stamp as brief_interests.
FILTERED = "python,method,security,agent-safety,retrieval-design,eval-integrity,data-quality"


def _run(cmd: list[str], tmp_path: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    """Run `cmd` against a throwaway store under tmp_path, with no inherited okl environment."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("OKL_BRIEF_INTERESTS", "OKL_SERVICE_URL", "OKL_TOKEN", "OKL_BRIEFING_LOG")}
    env["OKL_DATABASE_URL"] = f"sqlite:///{tmp_path / 'store.db'}"
    env.update(extra)
    return subprocess.run(cmd, cwd=tmp_path, env=env, capture_output=True, text=True)


def test_preflight_reads_the_interests_the_briefed_arm_runs_with(tmp_path):
    """Set OKL_BRIEF_INTERESTS as the harness does and pre-flight gates on that briefing.

    The harness passed OKL_BRIEF_INTERESTS to `okl check` while pre-flight hard-coded
    unfiltered, so receipts ab-20260903-1323 through ab-20261011-2254 ran a filtered briefed
    arm past a gate that had checked an unfiltered one: react_fetch's rule, tagged `react`,
    was absent from the arm and present in the check (REPORT §4h; named again by an
    independent verification on 2026-10-22).
    """
    # ARRANGE — a throwaway store holding the twelve seed packs, as an A/B store does.
    seeded = _run([sys.executable, "-m", "okl", "seed", str(ROOT / "seed")], tmp_path)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    script = str(ROOT / "evals" / "preflight.py")

    # ACT — once unfiltered (the default), once with the interests those receipts stamp.
    plain = _run([sys.executable, script], tmp_path)
    filtered = _run([sys.executable, script], tmp_path, OKL_BRIEF_INTERESTS=FILTERED)

    # ASSERT — the gate names the interests it used and answers for that briefing.
    assert plain.returncode == 0 and "PRE-FLIGHT OK" in plain.stdout, plain.stdout + plain.stderr
    assert "interests=none (unfiltered" in plain.stdout, plain.stdout
    assert f"interests={FILTERED}" in filtered.stdout, filtered.stdout
    assert filtered.returncode == 1 and "[MISSING] react_fetch" in filtered.stdout, filtered.stdout + filtered.stderr


def test_preflight_gates_the_task_file_it_is_given_and_can_accept_a_missing_lesson(tmp_path):
    """The harness passes the task set it runs; a held-out task whose briefing lacks its lesson
    fails the gate unless the run declares that absence as its subject (review on #269)."""
    seeded = _run([sys.executable, "-m", "okl", "seed", str(ROOT / "seed")], tmp_path)
    assert seeded.returncode == 0, seeded.stdout + seeded.stderr
    tasks = tmp_path / "tasks.jsonl"
    tasks.write_text(json.dumps({"id": "far/paraphrase", "task": "arrange the furniture in the lobby by colour",
                                 "signal": "n/a", "defect_node": "seed:dotnet-defects:nc_idor"}) + "\n")
    script = str(ROOT / "evals" / "preflight.py")
    refused = _run([sys.executable, script, "--tasks", str(tasks)], tmp_path)
    assert refused.returncode == 1 and "[MISSING] far/paraphrase" in refused.stdout, refused.stdout
    accepted = _run([sys.executable, script, "--tasks", str(tasks), "--accept-missing"], tmp_path)
    assert accepted.returncode == 0 and "accepted by --accept-missing: far/paraphrase" in accepted.stdout, accepted.stdout
