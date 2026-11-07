"""docs/ARCHITECTURE.md's diagrams stay true to the code.

okl retired its last hand-drawn architecture diagram (93933d7) after a review found it wrong in
four places that nothing had checked. Two of the four diagrams now are generated from the code
and must match what the generator writes today; the two drawn ones must name only commands,
flags, MCP tools, hook events, scripts and briefing marks the code still has.
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "ci" / "check-diagram-names.py"


def test_the_generated_architecture_diagrams_are_current():
    """The layers and storage diagrams are what docs/render_architecture.py writes from the
    code right now. --check compares without writing: a test that repaired what it checks
    would always pass."""
    r = subprocess.run([sys.executable, str(ROOT / "docs" / "render_architecture.py"), "--check"],
                       capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stderr


def test_the_drawn_diagrams_name_only_what_the_code_has():
    """Both drawn diagrams pass the name check CI runs on them."""
    diagrams = sorted(str(p) for p in (ROOT / "docs" / "architecture").glob("*.excalidraw"))
    assert len(diagrams) == 2, diagrams
    r = subprocess.run([sys.executable, str(CHECK), *diagrams], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0, r.stdout + r.stderr


def test_the_name_check_fails_on_each_kind_of_name_the_code_lacks(tmp_path):
    """Each kind it checks, given a name the code does not have, is reported; real names and
    prose beside them are not. Without this, a check that matched nothing would pass every
    diagram."""
    def diagram(*texts: str) -> Path:
        p = tmp_path / f"d{len(list(tmp_path.iterdir()))}.excalidraw"
        p.write_text(json.dumps({"type": "excalidraw", "elements": [
            {"type": "text", "text": t} for t in texts]}))
        return p

    def run(p: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(CHECK), str(p)], capture_output=True,
                              text=True, cwd=ROOT)

    # ARRANGE / ACT — real names, and prose that only looks like a command
    good = run(diagram("okl check --task x --format hook", "okl_record", "UserPromptSubmit",
                       "stop-okl-encode.sh", ".github/workflows/okl-verify.yml", "STALE",
                       "okl runs it", "git push --no-verify"))
    # ASSERT (1)
    assert good.returncode == 0, good.stdout + good.stderr

    # ACT / ASSERT (2) — one unknown of each kind, each named in the report
    bad = run(diagram("okl frobnicate", "okl check --no-such-flag", "okl_teleport", "PreCompact",
                      "stop-okl-encode2.sh", "gates/ghost.yml", "UNVANISHED"))
    assert bad.returncode == 1, bad.stdout
    for name in ("okl frobnicate", "--no-such-flag", "okl_teleport", "PreCompact",
                 "stop-okl-encode2.sh", "gates/ghost.yml", "UNVANISHED"):
        assert f"FAIL: {name}" in bad.stdout, (name, bad.stdout)
