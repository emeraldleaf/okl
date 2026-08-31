"""`okl scaffold` — stamp the portable method kit into a repo.

Copies the template tree shipped inside the package (src/okl/scaffold/) into the target repo,
renaming `claude/` -> `.claude/` (the package can't ship a dotfile dir on some filesystems), and
substituting `{{REPO}}`. Never overwrites an existing file unless --force; prints a FILL worklist.
"""
from __future__ import annotations

import shutil
from pathlib import Path

SCAFFOLD_ROOT = Path(__file__).parent / "scaffold"

# (src relative to scaffold/, dst relative to repo root). `{c}` is the claude dir name
# (".claude" in real use; overridable only so the logic is testable inside sandboxes that
# forbid creating a literal ".claude" path).
def _layout(c: str = ".claude"):
    return [
        ("root/CLAUDE.md", "CLAUDE.md"),
        ("root/METHOD.md", "METHOD.md"),
        ("claude", c),              # dir: skills/agents/commands/rules
        ("gates", "gates"),
        ("registries", "registries"),
        ("evals", "evals"),
        ("ci/method-gates.yml", ".github/workflows/method-gates.yml"),
        ("ci/okl-verify.yml", ".github/workflows/okl-verify.yml"),
        ("hooks/userpromptsubmit-okl-check.sh", f"{c}/hooks/userpromptsubmit-okl-check.sh"),
        ("hooks/stop-okl-encode.sh", f"{c}/hooks/stop-okl-encode.sh"),
        ("hooks/hooks.json", f"{c}/hooks/hooks.json"),
        ("MANIFEST.md", "docs/method-kit-manifest.md"),
    ]

PLUGIN_LAYOUT = [
    ("plugin/plugin.json", "plugin.json"),
]


def _copy(src: Path, dst: Path, repo: str, force: bool, written: list, skipped: list):
    if src.is_dir():
        for child in src.rglob("*"):
            if child.is_file():
                rel = child.relative_to(src)
                _copy_file(child, dst / rel, repo, force, written, skipped)
    else:
        _copy_file(src, dst, repo, force, written, skipped)


def _copy_file(src: Path, dst: Path, repo: str, force: bool, written: list, skipped: list):
    if dst.exists() and not force:
        skipped.append(dst)
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    text = None
    try:
        text = src.read_text()
    except (UnicodeDecodeError, ValueError):
        shutil.copy2(src, dst)  # binary
        written.append(dst)
        return
    dst.write_text(text.replace("{{REPO}}", repo))
    if dst.suffix == ".sh":
        dst.chmod(0o755)
    written.append(dst)


def list_profiles() -> list[str]:
    d = SCAFFOLD_ROOT / "profiles"
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.is_dir() else []


def scaffold(target: str = ".", repo: str | None = None, force: bool = False,
             plugin: bool = False, claude_dir: str = ".claude",
             profile: str | list[str] | None = None) -> dict:
    root = Path(target).resolve()
    root.mkdir(parents=True, exist_ok=True)
    repo = repo or root.name
    written: list[Path] = []
    skipped: list[Path] = []

    # Profiles are composable — stack a backend profile with react, etc.
    profiles = [profile] if isinstance(profile, str) else list(profile or [])
    if profiles:
        avail = list_profiles()
        for p in profiles:
            if p not in avail:
                raise ValueError(f"unknown profile {p!r}; available: {', '.join(avail) or '(none)'}")

    layout = _layout(claude_dir) + (PLUGIN_LAYOUT if plugin else [])
    for src_rel, dst_rel in layout:
        _copy(SCAFFOLD_ROOT / src_rel, root / dst_rel, repo, force, written, skipped)

    # Each profile drops its stack's verbatim canon into .claude/rules/ (+ a README).
    for p in profiles:
        prof_root = SCAFFOLD_ROOT / "profiles" / p
        _copy(prof_root / "rules", root / claude_dir / "rules", repo, force, written, skipped)
        _copy(prof_root / "README.md", root / claude_dir / "rules" / f"_PROFILE_{p}.md",
              repo, force, written, skipped)

    # find FILL slots across everything just written
    fills = []
    for p in written:
        try:
            for i, line in enumerate(p.read_text().splitlines(), 1):
                if "<<FILL" in line:
                    fills.append(f"{p.relative_to(root)}:{i}")
        except (UnicodeDecodeError, ValueError):
            pass
    return {"repo": repo, "root": str(root), "written": [str(p.relative_to(root)) for p in written],
            "skipped": [str(p.relative_to(root)) for p in skipped], "fills": fills, "plugin": plugin}
