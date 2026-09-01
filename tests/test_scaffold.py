"""Tests for the method-kit scaffold: files land, {{REPO}} substitutes, FILL slots detected,
and the portable gates actually fail on injected drift (verify-by-making-it-fail)."""
import subprocess
import sys
from pathlib import Path

import pytest

from okl.scaffold_cmd import scaffold


def test_scaffold_writes_tree(tmp_path):
    res = scaffold(target=str(tmp_path), repo="myrepo", plugin=True, claude_dir="dotclaude")
    written = set(res["written"])
    assert "CLAUDE.md" in written
    assert "AGENTS.md" in written, "same canon must ship under both filenames"
    assert (tmp_path / "CLAUDE.md").read_bytes() == (tmp_path / "AGENTS.md").read_bytes()
    assert "METHOD.md" in written
    assert "plugin.json" in written
    assert any("skills/encoding-loop/SKILL.md" in w for w in written)
    assert any("agents/architecture-reviewer.md" in w for w in written)
    assert any("gates/run-gates.sh" in w for w in written)
    # {{REPO}} substituted
    assert "myrepo" in (tmp_path / "CLAUDE.md").read_text()
    assert "{{REPO}}" not in (tmp_path / "CLAUDE.md").read_text()
    # FILL slots detected
    assert res["fills"], "should report FILL slots to complete"


def test_scaffold_no_clobber(tmp_path):
    (tmp_path / "CLAUDE.md").write_text("MINE — keep this")
    res = scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    assert "CLAUDE.md" in res["skipped"]
    assert (tmp_path / "CLAUDE.md").read_text() == "MINE — keep this"
    res2 = scaffold(target=str(tmp_path), repo="r", force=True, claude_dir="dotclaude")
    assert "CLAUDE.md" in res2["written"]


def test_tombstone_gate_fails_on_resurrection(tmp_path):
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    ts = tmp_path / "registries" / "tombstones.txt"
    ts.write_text(ts.read_text() + "\ndead_id_v1\tstray\t2026-07\n")
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "bad.md").write_text("we still import dead_id_v1 here\n")
    r = subprocess.run(["bash", "gates/check-tombstones.sh"], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode != 0
    assert "dead_id_v1" in r.stdout


def test_retractions_gate_fails_on_restatement(tmp_path):
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    reg = tmp_path / "registries" / "RETRACTIONS.md"
    reg.write_text(reg.read_text() + '\n### R1\n- **Retracted:** "the widget is threadsafe"\n')
    (tmp_path / "docs").mkdir(exist_ok=True)
    (tmp_path / "docs" / "claim.md").write_text('Note: "the widget is threadsafe" so we skip locks.\n')
    r = subprocess.run(["bash", "gates/check-retractions.sh"], cwd=tmp_path,
                       capture_output=True, text=True)
    assert r.returncode != 0


def test_clean_repo_gates_pass(tmp_path):
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    # empty registries (only comments/FILL) => tombstone + retraction gates pass
    (tmp_path / "registries" / "tombstones.txt").write_text("# none yet\n")
    (tmp_path / "registries" / "RETRACTIONS.md").write_text("# Retractions\n\nNone yet.\n")
    for g in ["check-tombstones.sh", "check-retractions.sh", "check-canon-size.sh"]:
        r = subprocess.run(["bash", f"gates/{g}"], cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 0, f"{g} should pass on clean repo: {r.stdout}\n{r.stderr}"


def test_scaffold_stamps_both_hooks(tmp_path):
    res = scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    written = set(res["written"])
    assert any("hooks/userpromptsubmit-okl-check.sh" in w for w in written)
    assert any("hooks/stop-okl-encode.sh" in w for w in written)
    import json
    hooks_cfg = json.loads((tmp_path / "dotclaude" / "hooks" / "hooks.json").read_text())
    # UserPromptSubmit, never PreToolUse: only the former's stdout reaches the model's context
    assert "UserPromptSubmit" in hooks_cfg and "Stop" in hooks_cfg and "PreToolUse" not in hooks_cfg


def test_encode_hook_loop_guard_and_fires_once(tmp_path, monkeypatch):
    """The Stop hook: exits 0 under stop_hook_active (never loops), blocks (exit 2) exactly
    once per session when the tree changed, then passes on the next stop."""
    import json
    import shutil
    if shutil.which("git") is None or shutil.which("okl") is None:
        pytest.skip("git or okl CLI not on PATH")
    hook = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "hooks" / "stop-okl-encode.sh"
    repo = tmp_path / "wt"; repo.mkdir()
    if subprocess.run(["git", "-C", str(repo), "init"], capture_output=True).returncode != 0:
        pytest.skip("git init blocked in this environment")
    (repo / "dirty.txt").write_text("uncommitted change")
    markers = tmp_path / "markers"; markers.mkdir()
    env = {"PATH": __import__("os").environ["PATH"], "TMPDIR": str(markers)}

    def stop(payload):
        return subprocess.run(["bash", str(hook)], cwd=repo, input=json.dumps(payload),
                              capture_output=True, text=True, env=env)

    assert stop({"session_id": "s1", "stop_hook_active": True}).returncode == 0
    first = stop({"session_id": "s1", "stop_hook_active": False})
    assert first.returncode == 2 and "ENCODING LOOP" in first.stderr
    assert stop({"session_id": "s1", "stop_hook_active": False}).returncode == 0, \
        "second stop in the same session must not re-fire"
    assert stop({"session_id": "s2", "stop_hook_active": False}).returncode == 2, \
        "a new session gets its own reminder"


def test_encode_hook_resolver_layers(tmp_path):
    """The hook binary resolver: no okl reachable -> reminder silently disabled; okl_bin
    pinned in .okl/config.json -> resolves without PATH; OKL_BIN env -> resolves first."""
    import json
    import shutil
    if shutil.which("git") is None:
        pytest.skip("git not available")
    hook = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "hooks" / "stop-okl-encode.sh"
    repo = tmp_path / "wt"; repo.mkdir()
    if subprocess.run(["git", "-C", str(repo), "init"], capture_output=True).returncode != 0:
        pytest.skip("git init blocked in this environment")
    (repo / "dirty.txt").write_text("uncommitted change")
    markers = tmp_path / "markers"; markers.mkdir()
    bare_path = "/usr/bin:/bin"  # system python3 (can parse JSON) but no okl, and no okl-importing python

    def stop(payload, **extra_env):
        env = {"PATH": bare_path, "TMPDIR": str(markers), **extra_env}
        return subprocess.run(["bash", str(hook)], cwd=repo, input=json.dumps(payload),
                              capture_output=True, text=True, env=env)

    # layer-4 miss: nothing resolves -> best-effort reminder silently disabled
    assert stop({"session_id": "rA", "stop_hook_active": False}).returncode == 0
    # layer 2: okl_bin pinned in .okl/config.json resolves without PATH
    (repo / ".okl").mkdir()
    (repo / ".okl" / "config.json").write_text(json.dumps({"repo": "wt", "okl_bin": "/opt/x/bin/okl"}))
    r = stop({"session_id": "rB", "stop_hook_active": False})
    assert r.returncode == 2 and "ENCODING LOOP" in r.stderr
    # layer 1: OKL_BIN env override resolves even with no config
    shutil.rmtree(repo / ".okl")
    assert stop({"session_id": "rC", "stop_hook_active": False}, OKL_BIN="/opt/x/bin/okl").returncode == 2


def test_mirror_files_identical():
    """The repo carries dogfood copies of files whose canonical source is the scaffold
    (what consumers receive). They must stay byte-identical — edit one, copy to the
    others in the same change. A drifted mirror ships one thing and runs another."""
    root = Path(__file__).resolve().parents[1]
    pairs = [
        (root / "ci" / "okl-verify.yml", root / "src" / "okl" / "scaffold" / "ci" / "okl-verify.yml"),
        (root / "ci" / "okl-verify.yml", root / ".github" / "workflows" / "okl-verify.yml"),
        # one canon, two filenames: Claude Code reads CLAUDE.md, other agents read AGENTS.md
        (root / "CLAUDE.md", root / "AGENTS.md"),
    ]
    for h in (root / "hooks").glob("*.sh"):
        pairs.append((h, root / "src" / "okl" / "scaffold" / "hooks" / h.name))
    assert pairs, "expected mirrored files to exist"
    for a, b in pairs:
        assert b.exists(), f"missing mirror: {b}"
        assert a.read_bytes() == b.read_bytes(), f"mirror drift: {a} != {b}"


def test_eval_harness_refuses_self_grading(tmp_path, monkeypatch):
    harness = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "evals" / "run_evals.py"
    monkeypatch.setenv("GENERATOR_MODEL", "m1")
    monkeypatch.setenv("JUDGE_MODEL", "m1")
    r = subprocess.run([sys.executable, str(harness)], capture_output=True, text=True)
    assert r.returncode == 3
    assert "REFUSING TO RUN" in r.stderr

def _git_repo(tmp_path):
    """Scaffold into a fresh git repo; the new gates read `git ls-files`, so the files
    must be tracked for the audit to see them (audits read the repo, not the tree)."""
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    if subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True).returncode != 0:
        pytest.skip("git init blocked in this environment")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    return tmp_path


def _run_gate(repo, gate):
    return subprocess.run(["bash", f"gates/{gate}"], cwd=repo, capture_output=True, text=True)


def test_links_gate_fails_on_broken_link(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "a.md").write_text("See [the handler](../src/gone.py) for details.\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    r = _run_gate(repo, "check-links.sh")
    assert r.returncode != 0, f"broken link should fail the gate: {r.stdout}"
    assert "gone.py" in r.stdout


def test_links_gate_passes_on_resolving_links(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "real.md").write_text("# real\n")
    (repo / "docs" / "a.md").write_text(
        "[sibling](real.md), [anchor](#section), [external](https://example.com), "
        "[with line](real.md#L2)\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    r = _run_gate(repo, "check-links.sh")
    assert r.returncode == 0, f"resolving links must pass: {r.stdout}"


def test_diagram_pair_gate_fails_on_unpaired_source(tmp_path):
    repo = _git_repo(tmp_path)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "arch.excalidraw").write_text("{}")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    r = _run_gate(repo, "check-diagram-pairs.sh")
    assert r.returncode != 0 and "arch.excalidraw" in r.stdout
    # pairing it makes the gate pass
    (repo / "docs" / "arch.svg").write_text("<svg/>")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    assert _run_gate(repo, "check-diagram-pairs.sh").returncode == 0
    # a hand-authored image with no editor source is reported, never failed
    (repo / "docs" / "handmade.svg").write_text("<svg/>")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    r2 = _run_gate(repo, "check-diagram-pairs.sh")
    assert r2.returncode == 0, "a hand-authored svg must not fail the gate"
    assert "handmade.svg" in r2.stdout and "note:" in r2.stdout


def test_diagram_gate_is_format_agnostic(tmp_path):
    """The defaults suit one workflow; the rule is general. A repo using another editor
    must be able to point the gate at its own extensions rather than be told it has
    nothing to check."""
    import os
    repo = _git_repo(tmp_path)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "flow.drawio").write_text("<mxfile/>")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    env = {**os.environ, "OKL_DIAGRAM_SRC_EXT": "drawio", "OKL_DIAGRAM_OUT_EXT": "png"}
    r = subprocess.run(["bash", "gates/check-diagram-pairs.sh"], cwd=repo,
                       capture_output=True, text=True, env=env)
    assert r.returncode != 0 and "flow.drawio" in r.stdout
    (repo / "docs" / "flow.png").write_bytes(b"\x89PNG")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    r2 = subprocess.run(["bash", "gates/check-diagram-pairs.sh"], cwd=repo,
                        capture_output=True, text=True, env=env)
    assert r2.returncode == 0, r2.stdout


def test_new_gates_noop_without_content(tmp_path):
    """A repo with no diagrams and no local links must not fail — a gate that cries
    wolf on an empty repo gets disabled, and then it catches nothing."""
    repo = _git_repo(tmp_path)
    for gate in ("check-links.sh", "check-diagram-pairs.sh"):
        r = _run_gate(repo, gate)
        assert r.returncode == 0, f"{gate} should no-op cleanly: {r.stdout}"

