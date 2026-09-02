"""Tests for the method-kit scaffold: the files `okl scaffold` stamps into a repo, and
the gates it ships.

The governing idea here is **verify-by-making-it-fail**. A gate that has only ever been
seen passing is untested: it might pass because the repo is clean, or because the gate is
broken and can no longer detect anything. So every gate test deliberately breaks the rule
the gate exists to catch, proves it goes red, and (where useful) proves it goes green
again once the breakage is repaired.

Tests follow ARRANGE / ACT / ASSERT with a story per phase, so the contract is readable
without opening the gate scripts.
"""
import subprocess
import sys
from pathlib import Path

import pytest

from okl.scaffold_cmd import scaffold


def test_scaffold_writes_tree(tmp_path):
    """Scaffolding a repo lands the whole method kit, with the repo's name substituted in.

    `claude_dir="dotclaude"` is a test-only override: some sandboxes refuse to create a
    literal `.claude` directory, so the tests exercise the same code path under a normal
    name. Real use always writes `.claude`.
    """
    # ARRANGE / ACT — stamp the kit into an empty directory
    res = scaffold(target=str(tmp_path), repo="myrepo", plugin=True, claude_dir="dotclaude")
    written = set(res["written"])

    # ASSERT (1) — the canon, the method doc, and the plugin manifest all landed
    assert "CLAUDE.md" in written
    assert "AGENTS.md" in written, "same canon must ship under both filenames"
    assert (tmp_path / "CLAUDE.md").read_bytes() == (tmp_path / "AGENTS.md").read_bytes()
    assert "METHOD.md" in written
    assert "plugin.json" in written

    # ASSERT (2) — and the enforcement surfaces: a skill, a review agent, the gate runner
    assert any("skills/encoding-loop/SKILL.md" in w for w in written)
    assert any("agents/architecture-reviewer.md" in w for w in written)
    assert any("gates/run-gates.sh" in w for w in written)

    # ASSERT (3) — the {{REPO}} placeholder was replaced, and none survives. A leftover
    # placeholder in a canon file is worse than an empty one: it reads as real config.
    assert "myrepo" in (tmp_path / "CLAUDE.md").read_text()
    assert "{{REPO}}" not in (tmp_path / "CLAUDE.md").read_text()

    # ASSERT (4) — stack-specific blanks are REPORTED, not silently left behind, so the
    # user gets a worklist instead of discovering <<FILL>> markers months later
    assert res["fills"], "should report FILL slots to complete"


def test_scaffold_no_clobber(tmp_path):
    """Scaffolding never overwrites your work unless you ask it to.

    People run `okl scaffold` on repos that already have a CLAUDE.md they care about.
    Silently replacing it would destroy hand-written canon, so existing files are skipped
    and reported; `--force` is the explicit opt-in to overwrite.
    """
    # ARRANGE — a repo that already has its own canon file
    (tmp_path / "CLAUDE.md").write_text("MINE — keep this")
    # ACT (1) / ASSERT (1) — a normal run reports the file as skipped and leaves it alone
    res = scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    assert "CLAUDE.md" in res["skipped"]
    assert (tmp_path / "CLAUDE.md").read_text() == "MINE — keep this", "must not clobber"

    # ACT (2) / ASSERT (2) — --force is the deliberate override, and it does overwrite
    res2 = scaffold(target=str(tmp_path), repo="r", force=True, claude_dir="dotclaude")
    assert "CLAUDE.md" in res2["written"]


def test_tombstone_gate_fails_on_resurrection(tmp_path):
    """The tombstone gate catches a retired identifier reappearing in prose.

    The compiler catches a dead identifier in code; nothing catches it in documentation,
    comments, or config. That is how a doc keeps teaching a removed system as current
    long after the code is gone. This test proves the gate actually detects it, by
    planting the exact violation it exists to find.
    """
    # ARRANGE — a scaffolded repo, plus a tombstone declaring an identifier retired
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    ts = tmp_path / "registries" / "tombstones.txt"
    ts.write_text(ts.read_text() + "\ndead_id_v1\tstray\t2026-07\n")
    (tmp_path / "docs").mkdir(exist_ok=True)
    # ...and a doc that still refers to it, which is the drift being hunted
    (tmp_path / "docs" / "bad.md").write_text("we still import dead_id_v1 here\n")

    # ACT — run the gate
    r = subprocess.run(["bash", "gates/check-tombstones.sh"], cwd=tmp_path,
                       capture_output=True, text=True)

    # ASSERT (1) — non-zero exit, so CI fails the build rather than merely warning
    assert r.returncode != 0
    # ASSERT (2) — and it names the offender, so the fix is obvious without hunting
    assert "dead_id_v1" in r.stdout


def test_retractions_gate_fails_on_restatement(tmp_path):
    """A claim you formally withdrew must not quietly reappear as fact somewhere else.

    Retracting something in one document does not un-write it everywhere else it was
    repeated. This gate greps for the exact withdrawn sentence outside the retraction
    registry, so a stale copy cannot keep teaching a claim you no longer stand behind.
    """
    # ARRANGE — a registry entry retracting one specific quoted claim
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    reg = tmp_path / "registries" / "RETRACTIONS.md"
    reg.write_text(reg.read_text() + '\n### R1\n- **Retracted:** "the widget is threadsafe"\n')
    (tmp_path / "docs").mkdir(exist_ok=True)
    # ...and another doc still asserting it, and reasoning from it ("so we skip locks"),
    # which is exactly why a withdrawn claim is dangerous rather than merely untidy
    (tmp_path / "docs" / "claim.md").write_text('Note: "the widget is threadsafe" so we skip locks.\n')

    # ACT — run the gate
    r = subprocess.run(["bash", "gates/check-retractions.sh"], cwd=tmp_path,
                       capture_output=True, text=True)

    # ASSERT — it fails the build; the restatement has to be removed or itself retracted
    assert r.returncode != 0


def test_clean_repo_gates_pass(tmp_path):
    """The other half of verify-by-making-it-fail: the gates must also go GREEN.

    A gate that fails on everything is as useless as one that fails on nothing — people
    switch it off, and then it catches nothing forever. Proving a clean repo passes is
    what makes a red result meaningful.
    """
    # ARRANGE — a scaffolded repo with empty registries: nothing retired, nothing retracted
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    (tmp_path / "registries" / "tombstones.txt").write_text("# none yet\n")
    (tmp_path / "registries" / "RETRACTIONS.md").write_text("# Retractions\n\nNone yet.\n")
    for g in ["check-tombstones.sh", "check-retractions.sh", "check-canon-size.sh"]:
        r = subprocess.run(["bash", f"gates/{g}"], cwd=tmp_path, capture_output=True, text=True)
        assert r.returncode == 0, f"{g} should pass on clean repo: {r.stdout}\n{r.stderr}"


def test_scaffold_stamps_both_hooks(tmp_path):
    """Both hooks ship, and they are registered under the right events.

    The event name is load-bearing, not cosmetic. An earlier version used PreToolUse,
    whose output never reaches the model: the hook fired, produced correct text, and
    changed nothing. UserPromptSubmit output does reach the model. The final assertion
    guards against that regression returning.
    """
    res = scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    written = set(res["written"])
    assert any("hooks/userpromptsubmit-okl-check.sh" in w for w in written)
    assert any("hooks/stop-okl-encode.sh" in w for w in written)
    import json
    hooks_cfg = json.loads((tmp_path / "dotclaude" / "hooks" / "hooks.json").read_text())
    # UserPromptSubmit, never PreToolUse: only the former's stdout reaches the model's context
    assert "UserPromptSubmit" in hooks_cfg and "Stop" in hooks_cfg and "PreToolUse" not in hooks_cfg


def test_encode_hook_loop_guard_and_fires_once(tmp_path, monkeypatch):
    """The session-end hook asks "did we learn anything?" once, and cannot trap you.

    Three properties, and every one exists because getting it wrong is painful:
      1. `stop_hook_active` guard — when the agent is already stopping because the hook
         blocked it, blocking again would loop forever.
      2. fires once per session — a marker file. Asking twice trains people to dismiss it.
      3. a NEW session gets its own reminder — the marker must be per session, not global,
         or the hook goes quiet forever after its first use.

    Exit 2 is the convention for "block"; exit 0 means "let the session end".
    """
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
    """The hook finds the `okl` binary even when PATH does not contain it.

    Hooks run in whatever process the agent spawns, which routinely lacks the venv or
    pipx directory your shell has. A hook that works only on the author's machine is the
    "surface nobody runs" bug wearing an environment-variable costume, so resolution is
    layered: an explicit env override, then a path pinned into config at install time,
    then PATH, then any interpreter that can import the package.

    `bare_path` below is the trick that makes this test real: /usr/bin:/bin has a system
    python3 (so JSON parsing still works) but no okl, simulating the stripped environment
    a hook actually runs in.
    """
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
    """Files that exist in more than one place must stay byte-identical.

    Some files live twice on purpose: the version this repo runs on itself (`ci/`,
    `hooks/`) and the version shipped to users (`src/okl/scaffold/...`). Fixing a bug in
    one copy and not the other means the project tests behaviour it does not ship, or
    ships behaviour it never tested. This test caught exactly that divergence the day it
    was written, so it is not hypothetical.

    Edit one copy, copy it to the others in the same change.
    """
    root = Path(__file__).resolve().parents[1]
    pairs = [
        (root / "ci" / "okl-verify.yml", root / "src" / "okl" / "scaffold" / "ci" / "okl-verify.yml"),
        (root / "ci" / "okl-verify.yml", root / ".github" / "workflows" / "okl-verify.yml"),
        # one canon, two filenames: Claude Code reads CLAUDE.md, other agents read AGENTS.md
        (root / "CLAUDE.md", root / "AGENTS.md"),
    ]
    pairs.extend((h, root / "src" / "okl" / "scaffold" / "hooks" / h.name)
                 for h in (root / "hooks").glob("*.sh"))
    assert pairs, "expected mirrored files to exist"
    for a, b in pairs:
        assert b.exists(), f"missing mirror: {b}"
        assert a.read_bytes() == b.read_bytes(), f"mirror drift: {a} != {b}"


def test_eval_harness_refuses_self_grading(tmp_path, monkeypatch):
    """The eval harness refuses to run when the judge is the same model as the generator.

    A model grading its own output shares its own blind spots, so it reliably approves
    the mistakes it just made. This is enforced as a hard refusal (exit 3) rather than a
    warning, because a warning in a test harness is a warning nobody reads.
    """
    harness = Path(__file__).resolve().parents[1] / "src" / "okl" / "scaffold" / "evals" / "run_evals.py"
    monkeypatch.setenv("GENERATOR_MODEL", "m1")
    monkeypatch.setenv("JUDGE_MODEL", "m1")
    r = subprocess.run([sys.executable, str(harness)], capture_output=True, text=True)
    assert r.returncode == 3
    assert "REFUSING TO RUN" in r.stderr

def _git_repo(tmp_path):
    """Build a scaffolded repo whose files are TRACKED by git, and hand it back.

    Why the `git add` matters: the link and diagram gates iterate `git ls-files` rather
    than walking the directory. That is deliberate — an audit should answer the question
    "is main correct?", not "is this developer's messy working copy correct?". A file that
    is not committed is invisible to those gates, so a test that skipped `git add` would
    pass for the wrong reason.
    """
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    if subprocess.run(["git", "-C", str(tmp_path), "init"], capture_output=True).returncode != 0:
        pytest.skip("git init blocked in this environment")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], capture_output=True)
    return tmp_path


def _run_gate(repo, gate):
    return subprocess.run(["bash", f"gates/{gate}"], cwd=repo, capture_output=True, text=True)


def test_links_gate_fails_on_broken_link(tmp_path):
    """A markdown link pointing at a file that does not exist fails the build.

    This is drift the compiler cannot see: the prose still reads as true, while the file
    it cites was renamed or deleted. Nothing else in a normal toolchain checks it.
    """
    # ARRANGE — a tracked doc citing a path that was never there
    repo = _git_repo(tmp_path)
    (repo / "docs").mkdir(exist_ok=True)
    (repo / "docs" / "a.md").write_text("See [the handler](../src/gone.py) for details.\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], capture_output=True)
    r = _run_gate(repo, "check-links.sh")
    assert r.returncode != 0, f"broken link should fail the gate: {r.stdout}"
    assert "gone.py" in r.stdout


def test_links_gate_passes_on_resolving_links(tmp_path):
    """The gate must not cry wolf. Four link shapes that are all legitimate:

    a sibling file that exists, an in-page anchor (`#section`), an external URL, and a
    path carrying a line anchor (`file.md#L2`). A gate that flagged any of these would be
    switched off within a week, and then it would catch nothing at all.
    """
    # ARRANGE — one doc containing all four shapes, plus the sibling it points at
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
    """A diagram source with no rendered export fails; a hand-drawn image alone does not.

    The asymmetry is the point. Reviewers read the rendered image on the forge, so a
    source with no export means they see nothing — that is a failure. The reverse, an
    image with no editor source, usually means somebody authored the picture directly,
    which is legitimate, so it is reported and allowed. An earlier draft of this gate
    failed that case and flagged this project's own hand-authored chart.
    """
    # ARRANGE — a diagram source with no sibling export
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
    """Defaults are excalidraw + svg, but the RULE is about sources and renders, not
    about one editor. A team on draw.io and PNGs must be able to point the same gate at
    their own extensions rather than be told they have nothing to check."""
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
    """Gates stay silent in a repo that has nothing for them to check.

    A gate that fails an empty repo trains people to ignore it, and an ignored gate
    enforces nothing. Silence here is correct behaviour, not a missing feature.
    """
    """A repo with no diagrams and no local links must not fail — a gate that cries
    wolf on an empty repo gets disabled, and then it catches nothing."""
    repo = _git_repo(tmp_path)
    for gate in ("check-links.sh", "check-diagram-pairs.sh"):
        r = _run_gate(repo, gate)
        assert r.returncode == 0, f"{gate} should no-op cleanly: {r.stdout}"

def test_seed_from_codebase_command_ships_with_its_guard_rails(tmp_path):
    """The agent-driven bootstrap command ships, and states the rules that keep it honest.

    Asking a model to read a codebase and write down its rules invites confident
    invention: a plausible rule that no file supports is worse than an empty store,
    because it gets injected into every future task and believed. Three constraints
    prevent that, and all three must survive future edits to the file, so they are
    asserted here rather than left to a reviewer's memory.
    """
    # ARRANGE / ACT — stamp the kit into an empty repo
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    cmd = tmp_path / "dotclaude" / "commands" / "seed-from-codebase.md"

    # ASSERT (1) — the command actually ships; a documented-but-absent command is the
    # "surface nobody runs" failure in its purest form
    assert cmd.exists(), "the agent-driven bootstrap command must ship with the kit"
    text = cmd.read_text()

    # ASSERT (2) — evidence is mandatory: no citation, no record
    assert "cites evidence, or it does not exist" in text
    assert "found_by" in text, "must tell the agent where to put the citation"

    # ASSERT (3) — proposals stay repo-scoped. Claiming org scope would assert a rule is
    # true for every project, which is a human judgment about the world, not an inference
    # available from reading one codebase.
    assert '"scope": "repo:' in text

    # ASSERT (4) — nothing arrives pre-verified, because reading code is not running a
    # check. A stamp has to be earned with `okl verify`.
    assert "Nothing is `verified`" in text

    # ASSERT (5) — it proposes; it does not import. Importing is the human's decision.
    assert "Do **not** run `okl seed` yourself" in text



def test_seed_from_docs_command_ships_with_its_guard_rails(tmp_path):
    """The docs-to-records command ships, and states the rule that keeps it honest.

    Specs and plans are the highest-confidence material a team has, because a human
    already decided each line was true. They are also the easiest to mine badly: prose
    invites confident paraphrase, and a plan is mostly work items that expire the moment
    the ticket closes. A store full of expired tasks is worse than an empty one, because
    it gets injected into future tasks and believed.
    """
    # ARRANGE / ACT — stamp the kit into an empty repo
    scaffold(target=str(tmp_path), repo="r", claude_dir="dotclaude")
    cmd = tmp_path / "dotclaude" / "commands" / "seed-from-docs.md"

    # ASSERT (1) — it ships; a documented-but-absent command is the surface nobody runs
    assert cmd.exists(), "the docs-to-records command must ship with the kit"
    text = cmd.read_text()

    # ASSERT (2) — the durable/expiring distinction is the whole job, so it must survive
    # any future edit to this file
    assert "outlives the work item" in text

    # ASSERT (3) — citations are mandatory and the agent is told where to put them
    assert "found_by" in text
    assert "path:line" in text

    # ASSERT (4) — it proposes, it does not import. Importing is the human's decision,
    # made after reading what was proposed.
    assert "Do **not** run `okl seed` yourself" in text

    # ASSERT (5) — the marker that makes the citation rule mechanical rather than
    # remembered is present in the template it tells the agent to emit
    assert "_proposed_by" in text
