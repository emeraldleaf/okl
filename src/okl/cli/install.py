"""`okl init`, `okl connect` and `okl scaffold`: wiring okl into a repo, and taking it out.

Everything here writes into somebody else's repository, so every write is idempotent
and non-clobbering: an edited file is kept, a symlinked destination is refused, and
`okl init --uninstall` removes only what okl installed.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

from ..client import Client, _find_config, load_config, save_config
from .packs import _empty_store_guidance, _seed_first_run


def _merge_hook_settings(claude: Path) -> bool:
    """Register both okl hooks in .claude/settings.json. Idempotent: existing settings and
    unrelated hooks are preserved; an already-registered okl hook is left alone. A hook
    that is installed but unregistered is a surface nobody runs."""
    settings_path = claude / "settings.json"
    if _refuse_symlink(settings_path):
        return False
    try:
        settings = json.loads(settings_path.read_text()) if settings_path.exists() else {}
    except json.JSONDecodeError:
        print(f"! {settings_path} is not valid JSON — not touching it; register the hooks manually.")
        return False
    hooks_cfg = settings.setdefault("hooks", {})
    changed = False
    # UserPromptSubmit, not PreToolUse: only UserPromptSubmit/SessionStart stdout reaches the
    # model's context. A PreToolUse briefing fires but is never read (found by E2E test).
    for event, command in HOOK_COMMANDS.items():
        entries = hooks_cfg.setdefault(event, [])
        if any(h.get("command", "").endswith(Path(command).name)
               for e in entries for h in e.get("hooks", [])):
            continue
        entries.append({"hooks": [{"type": "command", "command": command}]})
        changed = True
    if changed:
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return changed


HOOK_COMMANDS = {
    # okl registers exactly these commands; uninstall removes exactly these and nothing else.
    "UserPromptSubmit": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/userpromptsubmit-okl-check.sh',
    "Stop": '"$CLAUDE_PROJECT_DIR"/.claude/hooks/stop-okl-encode.sh',
}


MCP_ENTRY = {"command": "okl", "args": ["mcp"]}


def _symlinked(path: Path) -> Path | None:
    """The first symlink on the way to `path` inside this repo, or None.

    okl writes into repositories it did not create. A cloned repo can hold a symlink
    (dangling or not) where okl writes -- a hook, settings.json, a symlinked .claude/ --
    and following it writes okl's file wherever the link points, outside the repo
    (CWE-59, found in review of #50). okl writes only real files under real directories.
    """
    root = Path.cwd().resolve()
    p = Path(path)
    for part in [p, *p.parents]:
        if str(part) in ("", "."):
            break
        if part.is_symlink():
            return part
        try:
            if part.resolve() == root:
                break
        except OSError:
            return part
    return None


def _refuse_symlink(path: Path) -> bool:
    link = _symlinked(path)
    if link is not None:
        print(f"! refused {path}: {link} is a symlink, and okl only writes real files inside "
              f"this repo. Replace the link with a real file or directory, then re-run.")
    return link is not None


def _place_owned(dst: Path, shipped: str, label: str, force: bool) -> None:
    """Install or upgrade one okl-owned file without clobbering an edit (#49).

    `okl init` used to overwrite the hooks on every run, silently discarding a local edit.
    A file is replaced only when its fingerprint says it is an unmodified okl file (any
    version), or with --force; an edited one is kept and reported.
    """
    from .. import ownership
    if _refuse_symlink(dst):
        return
    state = ownership.status(dst, shipped)
    if state == ownership.MISSING or (state == ownership.OKL and dst.read_text() != shipped):
        verb = "installed" if state == ownership.MISSING else "upgraded"
    elif state == ownership.OKL:
        print(f"• {label} already current → {dst}")
        return
    elif force:
        verb = "replaced (--force)"
    else:
        why = ("edited since okl installed it" if state == ownership.MODIFIED
               else "not recognisably okl's (no fingerprint, and not this version)")
        print(f"! kept {dst}: {why}. Your version stays; `okl init --force` replaces it "
              f"with okl's.")
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    # Exact bytes: text mode would turn \n into \r\n on Windows, and bash cannot run a
    # script whose shebang line ends in \r.
    dst.write_bytes(shipped.encode("utf-8"))
    if shipped.startswith("#!"):   # git runs its hooks by name: pre-push has no .sh
        dst.chmod(0o755)
    print(f"✓ {verb} {label} → {dst}")


def _uninstall(dry_run: bool) -> int:
    """Remove what okl owns and nothing else (#49). The store (.okl/) is user data and is
    never touched; an edited okl file is kept and named, never deleted."""
    act = "would remove" if dry_run else "removed"
    kept = (_uninstall_files(act, dry_run) + _uninstall_hook_registrations(act, dry_run)
            + _uninstall_mcp(act, dry_run))
    for k in kept:
        print(f"! kept {k}")
    print("• .okl/ (your store and config) is never removed by uninstall; delete it yourself "
          "if you mean to.")
    return 0


def _uninstall_files(act: str, dry_run: bool) -> list[str]:
    from .. import ownership
    scaffold = Path(__file__).parent.parent / "scaffold"
    kept: list[str] = []
    owned = [(Path(".claude/hooks/userpromptsubmit-okl-check.sh"),
              scaffold / "hooks" / "userpromptsubmit-okl-check.sh"),
             (Path(".claude/hooks/stop-okl-encode.sh"), scaffold / "hooks" / "stop-okl-encode.sh"),
             (Path(".github/workflows/okl-verify.yml"), scaffold / "ci" / "okl-verify.yml")]
    hooks, _ = _git_hooks_dir()
    if hooks is not None:
        owned.append((hooks / "pre-push", GIT_HOOK_SRC))
    for dst, src in owned:
        if _symlinked(dst) is not None:
            kept.append(f"{dst} (a symlink, or under one — okl does not follow links)")
            continue
        state = ownership.status(dst, src.read_text())
        if state == ownership.OKL:
            if not dry_run:
                dst.unlink()
            print(f"✓ {act} {dst}")
        elif state != ownership.MISSING:
            why = "edited" if state == ownership.MODIFIED else "not recognisably okl's"
            kept.append(f"{dst} ({why})")
    return kept


def _uninstall_hook_registrations(act: str, dry_run: bool) -> list[str]:
    """Remove okl's exact hook commands, then any group or event that is left empty.
    Another tool's hook in the same group or event is never touched."""
    path = Path(".claude/settings.json")
    if not path.exists():
        return []
    if _symlinked(path) is not None:
        return [f"{path} (a symlink — okl's hook entries not removed)"]
    try:
        settings = json.loads(path.read_text())
    except json.JSONDecodeError:
        return [f"{path} (not valid JSON — okl's hook entries not removed)"]
    hooks_cfg = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks_cfg, dict):
        return []
    removed = _drop_okl_hooks(hooks_cfg)
    if not hooks_cfg:
        del settings["hooks"]
    if removed:
        if not dry_run:
            path.write_text(json.dumps(settings, indent=2) + "\n")
        print(f"✓ {act} {removed} okl hook registration(s) from {path}")
    return []


def _drop_okl_hooks(hooks_cfg: dict) -> int:
    """Remove okl's exact commands from `hooks_cfg` in place; return how many went."""
    removed = 0
    for event, command in HOOK_COMMANDS.items():
        groups = hooks_cfg.get(event)
        if not isinstance(groups, list):
            continue
        for g in groups:
            if isinstance(g, dict) and isinstance(g.get("hooks"), list):
                before = len(g["hooks"])
                g["hooks"] = [h for h in g["hooks"] if not (isinstance(h, dict)
                                                            and h.get("command") == command)]
                removed += before - len(g["hooks"])
        hooks_cfg[event] = [g for g in groups if not (isinstance(g, dict) and g.get("hooks") == [])]
        if not hooks_cfg[event]:
            del hooks_cfg[event]
    return removed


def _uninstall_mcp(act: str, dry_run: bool) -> list[str]:
    path = Path(".mcp.json")
    if not path.exists():
        return []
    if _symlinked(path) is not None:
        return [f"{path} (a symlink — the okl server entry not removed)"]
    try:
        cfg = json.loads(path.read_text())
    except json.JSONDecodeError:
        return [f"{path} (not valid JSON — the okl server entry, if any, not removed)"]
    servers = cfg.get("mcpServers") if isinstance(cfg, dict) else None
    if not (isinstance(servers, dict) and "okl" in servers):
        return []
    if servers["okl"] != MCP_ENTRY:
        return [f"{path} okl server (changed from what okl wrote)"]
    del servers["okl"]
    if not dry_run:
        path.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"✓ {act} the okl MCP server from {path}")
    return []


_BY_PLUGIN = "okl's Claude Code plugin is enabled and provides the hooks"


_OPTED_OUT = "--no-claude"


# What a repo is built with, read from files every stack keeps at a known place. Nothing is
# executed and nothing is installed; a miss just means fewer packs are suggested.
_RAG_DEPS = ("langchain", "llama-index", "llama_index", "chromadb", "qdrant", "faiss",
             "sentence-transformers", "pgvector", "weaviate", "pinecone")


_GEO_DEPS = ("rasterio", "geopandas", "gdal", "rslearn", "shapely", "xarray")


def _detect_stacks(root: Path) -> list[tuple[str, str]]:
    """[(stack tag, the file that showed it)], strongest evidence first."""
    found: list[tuple[str, str]] = []

    def first(patterns: tuple[str, ...]) -> Path | None:
        for pat in patterns:
            for hit in root.glob(pat):
                if not any(part in (".git", "node_modules", ".venv", "venv", "bin", "obj")
                           for part in hit.relative_to(root).parts):
                    return hit
        return None

    dn = first(("*.sln", "*.slnx", "*.csproj", "*/*.csproj", "*/*/*.csproj"))
    if dn:
        found.append(("dotnet", dn.relative_to(root).as_posix()))
    pkg = root / "package.json"
    if pkg.is_file():
        text = pkg.read_text(errors="ignore").lower()
        found.append(("react" if '"react"' in text else "frontend", "package.json"))
    py = next((root / f for f in ("pyproject.toml", "requirements.txt", "setup.py")
               if (root / f).is_file()), None)
    if py:
        text = py.read_text(errors="ignore").lower()
        found.append(("python", py.name))
        if any(d in text for d in _RAG_DEPS):
            found.append(("python-rag", py.name))
        if any(d in text for d in _GEO_DEPS):
            found.append(("geospatial", py.name))
    return found


def _should_wire_claude(args: argparse.Namespace) -> tuple[bool, str]:
    """Whether init should install Claude Code hooks here, and why.

    It required an existing .claude/ directory, and many repos have none: Claude Code
    creates it only once project settings exist. A fresh-install walkthrough of the
    README hit exactly that -- init succeeded, installed no hooks, and the enforced
    pre-task read never ran. Now init also wires when Claude Code is installed on this
    machine, or when asked to with --claude. --no-claude opts out, and okl's own plugin
    (which carries the hooks itself) always wins, so nothing is wired twice.
    """
    import shutil

    from .. import coexist
    if coexist.okl_plugin_enabled(Path.cwd(), Path.home()):
        return False, _BY_PLUGIN
    choice = getattr(args, "claude", None)
    if choice is False:
        return False, _OPTED_OUT
    if choice:
        return True, "--claude"
    if Path(".claude").exists():
        return True, ".claude/ exists"
    if shutil.which("claude"):
        return True, "Claude Code is installed (`claude` is on PATH)"
    return False, ""


def _wire_claude_code(args: argparse.Namespace) -> None:
    """init's Claude Code step: defer to okl's plugin, wire the project, or say how to."""
    claude = Path(".claude")
    wire = _should_wire_claude(args)
    if wire[1] == _BY_PLUGIN:
        # The plugin carries both hooks and the MCP server; registering them here too
        # would brief every prompt twice and ask the Stop question twice (#45).
        print("• okl's Claude Code plugin is enabled here, so it provides the hooks and the MCP "
              "server: none are installed into .claude/ or registered in settings.")
    elif wire[1] == _OPTED_OUT:
        print("• --no-claude: no Claude Code hooks installed.")
    elif wire[0]:
        if _refuse_symlink(claude):
            pass  # a (dangling) link at .claude: said so, and wrote nothing through it
        else:
            if not claude.exists():
                claude.mkdir()
                print(f"✓ created .claude/ ({wire[1]})")
            _install_claude_wiring(claude, force=getattr(args, "force", False))
    else:
        print("• no .claude/ dir here and Claude Code was not found, so no hooks were installed.")
        print("  `okl init --claude` installs them anyway. The store still works:")
        print("    - retrieval: `okl check --task \"...\"`, or the MCP server (`okl mcp`)")
        print("    - canon for any agent: `okl scaffold .` writes CLAUDE.md and AGENTS.md")
        print("    - the enforced pre-task read needs a hook, and okl auto-wires Claude Code only.")
        print("      The scripts in src/okl/scaffold/hooks/ are plain bash on stdin/stdout; if your")
        print("      agent has a pre-prompt hook, point it at them. Registration formats differ.")


def _own_repo_name() -> str | None:
    """The repo name in THIS directory's own .okl/config.json, or None.

    Only this directory's config counts: load_config walks up, and a new repo nested
    inside another okl repo must not inherit, or appear to rename, its parent's name.
    """
    found = _find_config()
    if found is None or found.parent.parent != Path.cwd().resolve():
        return None
    with contextlib.suppress(OSError, ValueError):
        name = json.loads(found.read_text()).get("repo")
        return str(name) if name else None
    return None


def _repo_name(args: argparse.Namespace) -> str:
    """The repo name init writes: --repo, else the name this directory is already
    configured with, else the folder's name.

    Re-running init is how hook copies are upgraded, and it used to fall straight back to
    the folder name, so a repo configured as "quartzose" in a folder named "Quartzose"
    was renamed on every upgrade, detaching its repo-scoped lessons.
    """
    return str(args.repo) if args.repo else (_own_repo_name() or Path.cwd().name)


def _init_dry_run(args: argparse.Namespace) -> int:
    """`okl init --dry-run`: every path init would touch, and nothing written."""
    repo = _repo_name(args)
    print(f"DRY RUN — nothing will be written. `okl init --repo {repo}` would:\n")
    print("  .okl/config.json                        repo name, interests, and the path to this okl")
    wire, why = _should_wire_claude(args)
    link = _symlinked(Path(".claude")) if wire else None
    if link is not None:
        print(f"  (no Claude Code hooks: {link} is a symlink, which init refuses to write through)")
    elif wire:
        print(f"  (wiring Claude Code: {why})")
        print("  .claude/hooks/userpromptsubmit-okl-check.sh   executable; runs when you submit a task")
        print("  .claude/hooks/stop-okl-encode.sh             executable; runs when a session ends")
        print("  .claude/settings.json                   registers those two hooks (merged, existing keys kept)")
        print("  .mcp.json                               registers the okl MCP server (only if the [mcp] extra is installed)")
    elif why:
        print(f"  (no Claude Code hooks: {why})")
    else:
        print("  (no .claude/ here and Claude Code not found, so no hooks; `--claude` installs them anyway)")
    _dry_run_drift_gates(args)
    if args.interests:
        print(f"  (interests: {args.interests})")
    else:
        stacks = _detect_stacks(Path.cwd())
        print("  (detected: " + (", ".join(f"{t} from {f}" for t, f in stacks) or "no known stack")
              + " — interests would be set from it; --interests overrides)")
    if not getattr(args, "no_seed", False):
        print("  .okl/okl.db                             seeded with the starter lessons and matching stack packs"
              " (if empty; --no-seed skips)")
    print("\nNothing is written outside this directory. Read the hooks before you register them:")
    print("  https://github.com/emeraldleaf/okl/blob/main/src/okl/scaffold/hooks/")
    return 0


def _dry_run_drift_gates(args: argparse.Namespace) -> None:
    """The dry run's lines for the two places drift can be gated: CI and a pre-push hook."""
    if not Path(".git").exists():
        print("  (not a git repository, so no CI workflow and no drift gate)")
        return
    cfg = load_config()
    if _ci_wanted(args, cfg):
        print("  .github/workflows/okl-verify.yml        a CI workflow running the drift gate on PRs")
    else:
        print("  (no CI workflow: opt-in with --ci, or an earlier init recorded --no-ci)")
    if not _git_hook_wanted(args, cfg):
        print("  (no pre-push hook: --no-git-hook, or an earlier init recorded it)")
        return
    hooks, why = _git_hooks_dir()
    if hooks is None:
        print(f"  (no pre-push hook: {why})")
    else:
        print(f"  {hooks / 'pre-push'!s:<40}a git pre-push hook running the drift gate "
              "(never over another tool's hook)")


def _ci_wanted(args: argparse.Namespace, cfg: dict) -> bool:
    """Whether init installs the GitHub Actions workflow: --ci/--no-ci when given, else what
    an earlier init recorded (#111), else only where okl's workflow is already installed.

    Opt-in, because the workflow spends a private repo's Actions minutes and does nothing on
    another CI; drift is gated locally by default instead (_git_hook_wanted). A repo an older
    init gave the workflow keeps it, so upgrading okl never removes a gate."""
    flag = getattr(args, "ci", None)
    if flag is not None:
        return bool(flag)
    if "ci" in cfg:
        return bool(cfg["ci"])
    return (Path(".github") / "workflows" / "okl-verify.yml").exists()


def _git_hook_wanted(args: argparse.Namespace, cfg: dict) -> bool:
    """Whether init installs the pre-push drift gate: --git-hook/--no-git-hook when given,
    else what an earlier init recorded, else wherever there is no CI gate -- so that, by
    default, drift is gated somewhere."""
    flag = getattr(args, "git_hook", None)
    if flag is not None:
        return bool(flag)
    if "git_hook" in cfg:
        return bool(cfg["git_hook"])
    return not _ci_wanted(args, cfg)


def _init_interests(cfg: dict, args: argparse.Namespace) -> None:
    """Explicit --interests win; otherwise detect them, once, for a repo that has none."""
    if args.interests:
        cfg["interests"] = [t.strip().lower() for t in args.interests.split(",") if t.strip()]
    elif not cfg.get("interests"):
        # Detected, not demanded: the interest list gated what a first briefing could show,
        # and a new user had to know a closed vocabulary to fill it in. security and method
        # are added because the portable lessons are filed under them.
        stacks = _detect_stacks(Path.cwd())
        if stacks:
            cfg["interests"] = sorted({t for t, _ in stacks} | {"security", "method"})
            print("• detected " + ", ".join(f"{t} ({f})" for t, f in stacks)
                  + " — interests set; pass --interests to choose your own")


def cmd_init(args: argparse.Namespace) -> int:
    """Wire the current repo so the loop runs without manual follow-up steps:
    config, hooks (installed AND registered), CI verifier, MCP registration.

    `--dry-run` prints every path it would touch and writes nothing. This command
    installs executable hooks and a CI workflow into your repo; you should be able
    to see that list before it happens."""
    import shutil
    if getattr(args, "uninstall", False):
        return _uninstall(getattr(args, "dry_run", False))
    if getattr(args, "dry_run", False):
        return _init_dry_run(args)
    repo = _repo_name(args)
    previous = _own_repo_name()
    if previous and previous != repo:
        # Only an explicit --repo gets here. Say what it costs: lessons recorded as
        # repo:<old> stop briefing in this repo.
        print(f"• repo renamed {previous} → {repo}: lessons scoped repo:{previous} "
              "no longer brief here")
    cfg = load_config()
    cfg["repo"] = repo
    if args.service:
        cfg["service_url"] = args.service
    _init_interests(cfg, args)
    # Pin how to invoke okl on THIS machine, for hooks running outside the dev shell
    # (agent harnesses don't inherit venv/pipx PATH entries). Machine-local by design —
    # .okl/ is gitignored; hooks fall back to PATH and `python3 -m okl` regardless.
    cfg["okl_bin"] = shutil.which("okl") or f"{sys.executable} -m okl"
    # Recorded, defaults included, so a later run does not change its answer because the
    # workflow file came or went in between.
    cfg["ci"] = _ci_wanted(args, cfg)
    cfg["git_hook"] = _git_hook_wanted(args, cfg)
    path = save_config(cfg)
    print(f"✓ wrote {path}  (repo={repo}, mode={'remote' if cfg.get('service_url') else 'local'}"
          + (f", interests={','.join(cfg['interests'])}" if cfg.get("interests") else "") + ")")

    _wire_claude_code(args)
    _wire_drift_gates(cfg, force=getattr(args, "force", False))
    if not getattr(args, "no_seed", False):
        _seed_first_run(Client())
    for line in _empty_store_guidance(Client()):
        print(line)
    # Said at install time, the one moment someone is reading okl's output and deciding
    # what to wire. Informational here: init succeeded; `okl doctor` is the re-runnable check.
    from .. import coexist
    found = coexist.detect(Path.cwd(), Path.home())
    if found:
        print("\n" + coexist.render(found))
    return 0


def _install_claude_wiring(claude: Path, force: bool = False) -> None:
    """Install AND register the hooks: the UserPromptSubmit check (the enforced read) and the
    Stop encode reminder (the write-side catch). Scripts come from the packaged scaffold —
    one canonical source, no drift. Also registers the MCP server when the extra exists."""
    hooks = claude / "hooks"
    hooks.mkdir(exist_ok=True)
    scaffold_hooks = Path(__file__).parent.parent / "scaffold" / "hooks"
    for name, label in [("userpromptsubmit-okl-check.sh", "pre-task check hook (UserPromptSubmit)"),
                        ("stop-okl-encode.sh", "encode reminder (Stop hook)")]:
        _place_owned(hooks / name, (scaffold_hooks / name).read_text(), label, force)
    if _merge_hook_settings(claude):
        print("✓ registered both hooks in .claude/settings.json (UserPromptSubmit + Stop)")
    else:
        print("• hooks already registered in .claude/settings.json")
    # MCP: register the okl server only if the extra is importable (a registration whose
    # dependency is missing would be a broken tool, worse than none).
    try:
        import mcp  # noqa: F401
    except ImportError:
        print("• MCP extra not installed — `pip install 'observed-knowledge-ledger[mcp]'` then re-run init")
        print("  to register the agent tools. (The distribution is not named `okl`; PyPI refuses that.)")
        return
    mcp_path = Path(".mcp.json")
    if _refuse_symlink(mcp_path):
        return
    mcp_cfg = json.loads(mcp_path.read_text()) if mcp_path.exists() else {}
    servers = mcp_cfg.setdefault("mcpServers", {})
    if "okl" not in servers:
        servers["okl"] = dict(MCP_ENTRY)
        mcp_path.write_text(json.dumps(mcp_cfg, indent=2) + "\n")
        print("✓ registered okl MCP server → .mcp.json (okl_check / okl_record / okl_search)")


def _wire_drift_gates(cfg: dict, force: bool) -> None:
    """init's drift gates, as `cfg` records them: the GitHub workflow, the pre-push hook."""
    if not Path(".git").exists():
        # Loud, because the drift layer is dead without history: drift compares governed
        # files against their last-verified commit.
        print("⚠ not a git repository — the drift verifier (okl drift) and its gates are DISABLED")
        print("  until `git init`: drift compares governed files against their last-verified commit.")
        return
    if cfg["ci"]:
        _install_ci_verifier(force=force)
    else:
        print("• no GitHub Actions workflow (`okl init --ci` adds one). A local hook is skippable "
              "and per-clone; on a team, gate drift in CI too")
    if cfg["git_hook"]:
        _install_git_hook(force=force)
    elif not cfg["ci"]:
        print("! drift is gated nowhere here (--no-git-hook and no CI): `okl init --git-hook` "
              "or `okl init --ci` adds a gate")


def _install_ci_verifier(force: bool = False) -> None:
    """Install the CI verifier workflow instead of printing a copy instruction."""
    wf = Path(".github") / "workflows" / "okl-verify.yml"
    src = Path(__file__).parent.parent / "scaffold" / "ci" / "okl-verify.yml"
    _place_owned(wf, src.read_text(), "CI verifier (drift gate + repo gates on every PR)", force)


GIT_HOOK_SRC = Path(__file__).parent.parent / "scaffold" / "git-hooks" / "pre-push"

# What to add to a pre-push hook okl did not write. `|| [ $? -ne 1 ]` lets exit 2 (did not
# run) through, and stays correct in a hook running under `set -e`.
_GATE_LINE = "okl drift --gate || [ $? -ne 1 ] || exit 1"


def _git_hooks_dir(root: Path | None = None) -> tuple[Path | None, str]:
    """Where git runs this repo's hooks, relative to `root` (default: here), or None and why.

    Git is asked, so core.hooksPath (Husky and similar) is honoured. A hooks directory
    outside `root` -- a global core.hooksPath, or the shared .git of a linked worktree --
    is refused: okl writes only inside the repo it was run in.
    """
    import os
    import subprocess
    root = root or Path.cwd()
    try:
        r = subprocess.run(["git", "-C", str(root), "rev-parse", "--git-path", "hooks"],
                           capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None, "git could not be run"
    if r.returncode != 0:
        return None, "not a git repository"
    # Lexical, not resolve(): a symlink on the way is _place_owned's to refuse, by name.
    hooks = Path(os.path.normpath(root / r.stdout.strip()))
    if not hooks.is_relative_to(root):
        return None, (f"git runs this repo's hooks from {hooks}, outside this directory "
                      "(a global core.hooksPath, or a linked worktree), and okl writes only "
                      "inside the repo")
    return hooks.relative_to(root), ""


def _install_git_hook(force: bool = False) -> None:
    """Install the pre-push drift gate (#90) where git will run it, never over another
    tool's hook: a pre-push hook okl did not write is kept even with --force, and the line
    that runs the gate from it is printed instead."""
    from .. import ownership
    hooks, why = _git_hooks_dir()
    if hooks is None:
        print(f"! no pre-push hook installed: {why}.")
        return
    dst = hooks / "pre-push"
    shipped = GIT_HOOK_SRC.read_text()
    if _symlinked(dst) is None and ownership.status(dst, shipped) == ownership.UNKNOWN:
        print(f"! kept {dst}: another pre-push hook is there, and okl does not replace a hook "
              f"it did not write. To gate drift from it (with Husky, in .husky/pre-push), add:"
              f"\n    {_GATE_LINE}")
        return
    _place_owned(dst, shipped, "pre-push drift gate (git hook)", force)


def cmd_connect(args: argparse.Namespace) -> int:
    """Point this repo at a shared service, and optionally store its token.

    Writing the token into .okl/config.json is a convenience for a laptop; CI and
    shared machines should pass OKL_TOKEN instead. save_config drops a .gitignore
    beside it so the secret cannot be committed either way.
    """
    cfg = load_config()
    cfg["service_url"] = args.url
    if args.token:
        cfg["token"] = args.token
    path = save_config(cfg)
    print(f"✓ connected → {args.url}  ({path})")
    return 0


def cmd_scaffold(args: argparse.Namespace) -> int:
    """Stamp the portable method kit (canon, skills, agent, commands, gates, evals, hook) into a repo."""
    from ..scaffold_cmd import scaffold
    res = scaffold(target=args.target, repo=args.repo, force=args.force, plugin=args.plugin,
                   profile=args.profile)
    print(f"✓ scaffolded method kit into {res['root']}  (repo={res['repo']}"
          + (f", profiles={'+'.join(args.profile)}" if args.profile else "")
          + (", as Claude Code plugin" if res['plugin'] else "") + ")")
    print(f"  {len(res['written'])} file(s) written, {len(res['skipped'])} skipped (already existed).")
    if args.verbose:
        for f in res["written"]:
            print(f"    + {f}")
    if res["skipped"] and not args.force:
        print(f"  skipped (use --force to overwrite): {', '.join(res['skipped'][:8])}"
              + (" …" if len(res['skipped']) > 8 else ""))
    if res["fills"]:
        print(f"\n  {len(res['fills'])} <<FILL>> slot(s) to complete (stack-specific rules):")
        for f in res["fills"]:
            print(f"    • {f}")
        print("  grep -rn '<<FILL' . to find them all later.")
    print("\nNext: `okl init` to wire the knowledge layer, then `/feature-spec` before your first change.")
    return 0
