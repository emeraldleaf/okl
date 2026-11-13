"""`okl init`, `okl connect` and `okl scaffold`: wiring okl into a repo, and taking it out.

Everything here writes into somebody else's repository, so every write is idempotent
and non-clobbering: an edited file is kept, a symlinked destination is refused, and
`okl init --uninstall` removes only what okl installed.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import sys
from pathlib import Path

from .. import core
from ..client import Client, _find_config, load_config, save_config
from .on_edit import HOOK_TIMEOUT
from .packs import _empty_store_guidance, _seed_first_run


def _merge_hook_settings(claude: Path) -> bool:
    """Register okl's hooks (HOOKS) in .claude/settings.json. Idempotent: existing settings and
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
    # The task briefing is UserPromptSubmit, not PreToolUse: plain stdout reaches the model only
    # from UserPromptSubmit and SessionStart, and a PreToolUse briefing printed that way fired
    # unread (REPORT §8). The read hook returns JSON `additionalContext`, which does reach it from
    # PostToolUse, next to the read's result: measured, 5 of 5 (REPORT §4aj).
    for event, matcher, command, timeout in HOOKS:
        entries = hooks_cfg.setdefault(event, [])
        mine = [h for e in entries for h in e.get("hooks", [])
                if h.get("command", "").endswith(Path(command).name)]
        if mine:
            # Registered already: keep it, and give it okl's timeout only where it has none or one
            # okl wrote, so a change to HOOK_TIMEOUT reaches an older settings file while a value
            # the person chose stays theirs (lesson n_967ef9825472: never clobber).
            for h in mine:
                if timeout and h.get("timeout") != timeout and h.get("timeout") in (None, *OKL_WROTE_TIMEOUTS):
                    h["timeout"] = timeout
                    changed = True
            continue
        hook: dict = {"type": "command", "command": command}
        if timeout:
            hook["timeout"] = timeout
        entry: dict = {"hooks": [hook]}
        if matcher:
            entry = {"matcher": matcher, **entry}
        entries.append(entry)
        changed = True
    if changed:
        settings_path.write_text(json.dumps(settings, indent=2) + "\n")
    return changed


# The usual forms of what would undo the owner's approval from inside a Claude Code session
# (#329): editing branch protection or rulesets through the REST or GraphQL API (matching is
# case-sensitive, so both spellings), and merging past the rules, as an admin or through the API.
# They advise the agent; GitHub enforces. A Bash rule does not match `sh -c '...'`, gh called by
# its full path or `git push` (Claude Code's permissions docs), so they never stand in for the
# branch rule. `*protection*` also stops reading protection through the agent's shell; `okl
# doctor` reads it itself. Uninstall removes these exact strings, an identical one you wrote too.
OWNER_DENY = ("Bash(gh api *protection*)", "Bash(gh api *Protection*)", "Bash(gh api *rulesets*)",
              "Bash(gh api *Ruleset*)", "Bash(gh api *pulls/*/merge*)", "Bash(gh pr merge *--admin*)")


# okl registers exactly these commands; uninstall removes exactly these and nothing else. Each is
# (event, the tools it answers for events Claude Code filters by tool, command, seconds Claude
# Code may run it, or None for its default). The read hook briefs the lessons governing a file
# when it is read, which comes before an edit (#94); the edit hook runs the approved checks of the
# lessons governing a file after an edit (#435), under a timeout of okl's own: Claude Code's
# default for a PostToolUse hook is ten minutes, not the minute okl's budget was written for.
HOOKS: tuple[tuple[str, str | None, str, int | None], ...] = (
    ("UserPromptSubmit", None, '"$CLAUDE_PROJECT_DIR"/.claude/hooks/userpromptsubmit-okl-check.sh', None),
    ("Stop", None, '"$CLAUDE_PROJECT_DIR"/.claude/hooks/stop-okl-encode.sh', None),
    ("PostToolUse", "Read", '"$CLAUDE_PROJECT_DIR"/.claude/hooks/posttooluse-okl-read.sh', None),
    ("PostToolUse", "Edit|Write|MultiEdit|NotebookEdit",
     '"$CLAUDE_PROJECT_DIR"/.claude/hooks/posttooluse-okl-edit.sh', HOOK_TIMEOUT),
)
# Every timeout okl has written for a hook. Init replaces one of these, or a missing one, with
# the current value; any other is the person's and is kept. Changing HOOK_TIMEOUT? Add the old
# value here, or repos set up before the change keep it.
OKL_WROTE_TIMEOUTS = frozenset({60})


# The MCP server starts through .claude/hooks/okl-mcp.sh, which finds okl in the hooks'
# layers (#206): a bare "okl" failed with ENOENT in a session launched without the shell's
# PATH. Claude Code sets CLAUDE_PROJECT_DIR in the server's environment, not its own, so the
# shell reads it at start; `$VAR` without braces, because .mcp.json expands `${VAR}` itself,
# when loading, where it is unset.
MCP_ENTRY = {"command": "/bin/sh",
             "args": ["-c", 'd=$CLAUDE_PROJECT_DIR; [ -n "$d" ] || d=.; exec "$d/.claude/hooks/okl-mcp.sh"']}
# What okl wrote before: init upgrades it, uninstall still recognises it.
LEGACY_MCP_ENTRIES = ({"command": "okl", "args": ["mcp"]},)
MCP_LAUNCHER = Path(".claude/hooks/okl-mcp.sh")

# The GitHub Actions drift workflow: where init installs it, and the copy okl ships.
WORKFLOW = Path(".github") / "workflows" / "okl-verify.yml"
WORKFLOW_SRC = Path(__file__).parent.parent / "scaffold" / "ci" / "okl-verify.yml"
# The okl release a repo's CI installs, so CI runs what the local hooks run. It sits beside the
# workflow rather than inside it: a workflow Dependabot has bumped counts as edited and is never
# replaced, which would freeze a pin written into it (review of the 0.11.0 release prep).
OKL_VERSION_FILE = Path(".github") / "okl-version"
# A version PyPI publishes (PEP 440, public): releases, pre-releases and post-releases. A dev or
# local build has no release to pin. The groups are what _version_key orders by.
PUBLIC_VERSION = re.compile(r"(\d+(?:\.\d+)*)(?:(a|b|rc)(\d+))?(?:\.post(\d+))?")


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
            + _uninstall_mcp(act, dry_run) + _uninstall_owner_paths(act, dry_run)
            + _uninstall_owner_denies(act, dry_run))
    for k in kept:
        print(f"! kept {k}")
    print("• .okl/ (your store and config) is never removed by uninstall; delete it yourself "
          "if you mean to.")
    return 0


def _uninstall_files(act: str, dry_run: bool) -> list[str]:
    from .. import ownership
    scaffold = Path(__file__).parent.parent / "scaffold"
    kept: list[str] = []
    workflow_removed = False
    owned = [(Path(".claude/hooks/userpromptsubmit-okl-check.sh"),
              scaffold / "hooks" / "userpromptsubmit-okl-check.sh"),
             (Path(".claude/hooks/stop-okl-encode.sh"), scaffold / "hooks" / "stop-okl-encode.sh"),
             (Path(".claude/hooks/posttooluse-okl-read.sh"), scaffold / "hooks" / "posttooluse-okl-read.sh"),
             (Path(".claude/hooks/posttooluse-okl-edit.sh"), scaffold / "hooks" / "posttooluse-okl-edit.sh"),
             (MCP_LAUNCHER, scaffold / "hooks" / "okl-mcp.sh"),
             (WORKFLOW, WORKFLOW_SRC)]
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
            workflow_removed = workflow_removed or dst == WORKFLOW
        elif state != ownership.MISSING:
            why = "edited" if state == ownership.MODIFIED else "not recognisably okl's"
            kept.append(f"{dst} ({why})")
    return kept + _uninstall_pin(act, dry_run, workflow_removed)


def _uninstall_pin(act: str, dry_run: bool, workflow_removed: bool) -> list[str]:
    """The CI pin goes only with okl's workflow. Beside a kept workflow it stays, so that workflow
    goes on installing the same okl; with no okl workflow beside it, nothing says it is okl's."""
    if not OKL_VERSION_FILE.is_file() or _symlinked(OKL_VERSION_FILE) is not None:
        return []
    if workflow_removed:
        if not dry_run:
            OKL_VERSION_FILE.unlink()
        print(f"✓ {act} {OKL_VERSION_FILE}")
        return []
    if WORKFLOW.exists():
        return [f"{OKL_VERSION_FILE} (the pin of the kept workflow)"]
    return [f"{OKL_VERSION_FILE} (no okl workflow beside it; delete it if it is okl's)"]


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


def _uninstall_owner_paths(act: str, dry_run: bool) -> list[str]:
    """okl's CODEOWNERS block (#329): every other byte of the file as it was, and a file that
    held only okl's block goes with it. Unpaired markers keep the file, named."""
    from .. import codeowners
    kept: list[str] = []
    # Every location, not only the one GitHub reads now: init may have written the block into a
    # file that a CODEOWNERS added since, earlier in GitHub's order, has replaced.
    for path in codeowners.LOCATIONS:
        if not path.is_file() and not path.is_symlink():
            continue
        if _symlinked(path) is not None:
            kept.append(f"{path} (a symlink — okl's owner-approved paths not removed)")
            continue
        try:
            text = path.read_bytes().decode("utf-8")
            rest = codeowners.remove(text)
        except (UnicodeDecodeError, codeowners.MalformedBlockError) as e:
            kept.append(f"{path} ({e}; okl's owner-approved paths not removed)")
            continue
        if rest != text:
            if not dry_run:
                if rest:
                    path.write_bytes(rest.encode("utf-8"))   # exact bytes: no newline translation
                else:
                    path.unlink()
            print(f"✓ {act} okl's owner-approved paths from {path}" + ("" if rest else " (the file held nothing else)"))
    return kept


def _uninstall_owner_denies(act: str, dry_run: bool) -> list[str]:
    """okl's Claude Code deny rules (OWNER_DENY), and nothing else: a list they leave empty stays,
    since okl cannot tell whether it was there before init."""
    kept: list[str] = []
    settings = Path(".claude/settings.json")
    if not settings.is_file() or _symlinked(settings) is not None:
        return kept
    try:
        data = json.loads(settings.read_text())
    except json.JSONDecodeError:
        return kept
    perms = data.get("permissions") if isinstance(data, dict) else None
    if not isinstance(perms, dict) or not isinstance(perms.get("deny"), list):
        return kept
    deny = perms["deny"]
    if any(rule in deny for rule in OWNER_DENY):
        perms["deny"] = [rule for rule in deny if rule not in OWNER_DENY]
        if not dry_run:
            settings.write_text(json.dumps(data, indent=2) + "\n")
        print(f"✓ {act} okl's deny rules from {settings}")
    return kept


def _drop_okl_hooks(hooks_cfg: dict) -> int:
    """Remove okl's exact commands from `hooks_cfg` in place; return how many went."""
    removed = 0
    for event, _matcher, command, _timeout in HOOKS:
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
    if servers["okl"] not in (MCP_ENTRY, *LEGACY_MCP_ENTRIES):
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


_SKIP_DIRS = (".git", "node_modules", ".venv", "venv", "bin", "obj")
# The root, then one and two folders down: a monorepo keeps its UI or its service a level or two
# in (app/frontend-react/package.json), and reading the root alone never saw it (#375).
_MAX_DEPTH = 2


def _kept(root: Path, hit: Path) -> bool:
    """Whether `hit` lies outside dependency folders and build output."""
    return not any(part in _SKIP_DIRS for part in hit.relative_to(root).parts)


def _manifests(root: Path, *names: str) -> list[Path]:
    """Every file by one of `names`, the root's first, then one and two folders down, each depth
    in path order. A skipped folder is never listed: globbing `*/*/package.json` walked every
    package under node_modules/ only to drop it (CodeRabbit on #386)."""
    found: list[Path] = []
    level = [root]
    for depth in range(_MAX_DEPTH + 1):
        # All names together, so a/requirements.txt comes before z/pyproject.toml.
        found += sorted(d / n for d in level for n in names if _readable(d / n))
        if depth < _MAX_DEPTH:
            level = sorted(c for d in level for c in _subfolders(d))
    return found


def _readable(p: Path) -> bool:
    """Whether `p` is a file detection can read. In a folder it cannot open, is_file() raises
    PermissionError (Python 3.11 ignores only "no such file"), and one bind-mounted database
    folder (`data/postgres`, owned by the container's user) failed `okl init` outright; a
    manifest it cannot read shows no stack."""
    try:
        return p.is_file() and os.access(p, os.R_OK)
    except OSError:
        return False


def _subfolders(d: Path) -> list[Path]:
    """The folders directly in `d` that detection reads, none of _SKIP_DIRS; none if unreadable."""
    try:
        return [c for c in d.iterdir() if c.is_dir() and c.name not in _SKIP_DIRS]
    except OSError:
        return []


def _mentions(p: Path, deps: tuple[str, ...]) -> bool:
    """Whether manifest `p` names any of `deps`, ignoring case; False if it cannot be read."""
    try:
        text = p.read_text(errors="ignore").lower()
    except OSError:
        return False
    return any(d in text for d in deps)


def _detect_stacks(root: Path) -> list[tuple[str, str]]:
    """[(stack tag, the file that showed it)], strongest evidence first. Manifests are read at
    the root and up to two folders down, the root first, so a root manifest is the one named
    whenever it shows the stack; dependency folders and build output are skipped."""
    found: list[tuple[str, str]] = []
    dn = next((hit for pat in ("*.sln", "*.slnx", "*.csproj", "*/*.csproj", "*/*/*.csproj")
               for hit in sorted(root.glob(pat)) if _kept(root, hit)), None)
    if dn:
        found.append(("dotnet", dn.relative_to(root).as_posix()))
    js = _manifests(root, "package.json")
    if js:
        react = next((p for p in js if _mentions(p, ('"react"',))), None)
        found.append(("react", react.relative_to(root).as_posix()) if react
                     else ("frontend", js[0].relative_to(root).as_posix()))
    py = _manifests(root, "pyproject.toml", "requirements.txt", "setup.py")
    if py:
        found.append(("python", py[0].relative_to(root).as_posix()))
        for tag, deps in (("python-rag", _RAG_DEPS), ("geospatial", _GEO_DEPS)):
            hit = next((p for p in py if _mentions(p, deps)), None)
            if hit:
                found.append((tag, hit.relative_to(root).as_posix()))
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
        # The plugin carries the hooks and the MCP server; registering them here too
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
        print("  .claude/hooks/posttooluse-okl-read.sh        executable; runs after the agent reads a file")
        print("  .claude/hooks/posttooluse-okl-edit.sh        executable; runs approved lesson checks after an edit")
        print("  .claude/settings.json                   registers those four hooks (merged, existing keys kept)")
        print("  .claude/hooks/okl-mcp.sh                     executable; starts the okl MCP server the way the hooks do")
        print("  .mcp.json                               registers the okl MCP server (both only if the [mcp] extra is installed)")
    elif why:
        print(f"  (no Claude Code hooks: {why})")
    else:
        print("  (no .claude/ here and Claude Code not found, so no hooks; `--claude` installs them anyway)")
    _dry_run_drift_gates(args)
    if not _dry_run_owner(args, (wire or why == _BY_PLUGIN) and why != _OPTED_OUT and link is None):
        return 2
    recorded = load_config().get("interests")
    if args.interests:
        print(f"  (interests: {args.interests})")
    elif recorded:
        # As _init_interests decides: detection only fills a config that has none (#340).
        print(f"  (interests kept: {', '.join(recorded)}; --interests replaces them)")
    else:
        stacks = _detect_stacks(Path.cwd())
        print("  (detected: " + (", ".join(f"{t} from {f}" for t, f in stacks) or "no known stack")
              + " — interests would be set from it; --interests overrides)")
    if not getattr(args, "no_seed", False):
        print("  .okl/okl.db                             seeded with the starter lessons and matching stack packs"
              " (if empty; --no-seed skips)")
    print("\nNothing is written outside this directory. Read the hooks before you register them:")
    print("  https://github.com/emeraldleaf/okl/blob/main/src/okl/scaffold/hooks/")
    print("  https://github.com/emeraldleaf/okl/blob/main/src/okl/scaffold/git-hooks/pre-push")
    return 0


def _dry_run_owner(args: argparse.Namespace, wiring_claude: bool) -> bool:
    """The dry run's lines for the owner step; False for an owner CODEOWNERS would reject."""
    from .. import codeowners
    cfg = load_config()
    if not _init_owner(cfg, args):
        return False
    owner = cfg.get("owner")
    if owner and _symlinked(path := codeowners.location(Path())) is not None:
        print(f"  (no owner-approved paths: {path} is a symlink, which init refuses to write through)")
    elif owner:
        print(f"  {path!s:<40}names {owner} code owner of "
              f"{', '.join(codeowners.owner_paths(cfg.get('owned', [])))} (okl's block only)")
        if wiring_claude:
            print("  .claude/settings.json                   deny rules for editing branch protection and "
                  "merging as an admin")
    return True


def _dry_run_drift_gates(args: argparse.Namespace) -> None:
    """The dry run's lines for the two places drift can be gated: CI and a pre-push hook."""
    if not Path(".git").exists():
        print("  (not a git repository, so no CI workflow and no drift gate)")
        return
    cfg = load_config()
    ci = _ci_wanted(args, cfg)
    if ci:
        print("  .github/workflows/okl-verify.yml        a CI workflow running the drift gate on PRs")
        print(_dry_run_pin(args))
    else:
        print("  (no CI workflow: opt-in with --ci, or an earlier init recorded --no-ci)")
    if not _git_hook_wanted(args, cfg):
        # Name the real reason: with --ci and no hook choice, the hook is skipped because
        # CI gates drift, and the old line blamed a --no-git-hook nobody had passed.
        chose = getattr(args, "git_hook", None) is not None or "git_hook" in cfg
        print("  (no pre-push hook: " + ("--no-git-hook, or an earlier init recorded it)" if chose or not ci
                                         else "okl's CI workflow gates drift here; --git-hook adds the hook too)"))
        return
    hooks, why = _git_hooks_dir()
    if hooks is None:
        print(f"  (no pre-push hook: {why})")
    else:
        print(f"  {hooks / 'pre-push'!s:<40}a git pre-push hook running the drift gate "
              "(never over another tool's hook)")


def _dry_run_pin(args: argparse.Namespace) -> str:
    """The dry run's line for the CI pin, decided as the real run decides it: another tool's
    file at the workflow's path stays unless --force, a symlink always, and neither gets a pin."""
    from .. import ownership
    force = getattr(args, "force", False)
    state = _workflow_state()
    foreign = _symlinked(WORKFLOW) is not None or (state == ownership.UNKNOWN and not force)
    if Path("src/okl/__init__.py").is_file():
        return "  (no CI pin: okl's own CI installs its checkout)"
    if foreign:
        return f"  (no CI pin: {WORKFLOW} is not okl's workflow, and is kept)"
    if state == ownership.MODIFIED and not force and not _workflow_reads_pin():
        return f"  (no CI pin: the kept, edited {WORKFLOW} does not read {OKL_VERSION_FILE.as_posix()})"
    version = _pinnable_version()
    if version is None:
        return "  (no CI pin: this okl is a dev or source build, so CI installs the newest release)"
    return (f"  {OKL_VERSION_FILE!s:<40}the okl release CI installs ({version}, or a newer pin "
            "it finds there)")


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
    from .. import ownership
    return _workflow_state() in (ownership.OKL, ownership.MODIFIED)


def _workflow_state() -> str:
    """ownership.status of .github/workflows/okl-verify.yml. Only okl's own workflow (edited
    or not) is a drift gate: another file at that path is kept, never replaced, and checks
    nothing okl knows of."""
    from .. import ownership
    return ownership.status(WORKFLOW, WORKFLOW_SRC.read_text())


def _git_hook_wanted(args: argparse.Namespace, cfg: dict) -> bool:
    """Whether init installs the pre-push drift gate: --git-hook/--no-git-hook when given,
    else what an earlier init recorded, else wherever CI will not gate drift -- no workflow
    wanted, or one wanted where another tool's file holds its path -- so that, by default,
    drift is gated somewhere."""
    flag = getattr(args, "git_hook", None)
    if flag is not None:
        return bool(flag)
    if "git_hook" in cfg:
        return bool(cfg["git_hook"])
    from .. import ownership
    return not _ci_wanted(args, cfg) or _workflow_state() == ownership.UNKNOWN


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
            cfg["interests"] = sorted({t for t, _ in stacks} | core.DEFAULT_INTERESTS)
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
    if not _init_owner(cfg, args):
        return 2
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
    if getattr(args, "review_after_writing", None) is not None:
        cfg["review_after_writing"] = args.review_after_writing
    path = save_config(cfg)
    print(f"✓ wrote {path}  (repo={repo}, mode={'remote' if cfg.get('service_url') else 'local'}"
          + (f", interests={','.join(cfg['interests'])}" if cfg.get("interests") else "") + ")")

    _wire_claude_code(args)
    _say_review_after_writing(cfg)
    _wire_drift_gates(cfg, force=getattr(args, "force", False))
    _wire_owner_paths(cfg, args)
    if not getattr(args, "no_seed", False):
        _seed_first_run(Client())
    for line in _empty_store_guidance(Client()):
        print(line)
    # A kept interest list (#340) never gains a later default, so say what it hides (#374).
    # Local only, as the steps above: a remote store is a download, and doctor reports it.
    from .health import _interest_lines
    if Client().mode != "remote":
        for line in _interest_lines(Client(), say_unread=False):
            print(line)
    # Said at install time, the one moment someone is reading okl's output and deciding
    # what to wire. Informational here: init succeeded; `okl doctor` is the re-runnable check.
    from .. import coexist
    found = coexist.detect(Path.cwd(), Path.home())
    if found:
        print("\n" + coexist.render(found))
    return 0


def _init_owner(cfg: dict, args: argparse.Namespace) -> bool:
    """Record --owner and --owned in `cfg`; False, having said why, for an owner CODEOWNERS would
    reject, before anything is written."""
    from .. import codeowners
    given = getattr(args, "owner", None)
    if given is not None:
        owner = codeowners.normalise_owner(given)
        if owner is None:
            print(f"! --owner {given!r} is not an owner CODEOWNERS accepts: @user, @org/team or an email")
            return False
        cfg["owner"] = owner
    given_paths = getattr(args, "owned", None) or []
    owned = [p.lstrip("/") for p in given_paths]   # validated as written: `/` alone strips to nothing
    bad = [g for g, p in zip(given_paths, owned, strict=True) if not codeowners.valid_path(p)]
    if bad:
        print(f"! --owned {bad[0]!r} is not one CODEOWNERS pattern (no spaces, '#', '!' or line breaks, "
              "and not the root alone)")
        return False
    if owned:
        cfg["owned"] = sorted({*cfg.get("owned", []), *owned})
        if not cfg.get("owner"):
            print("• --owned is recorded, and takes effect once --owner names who approves it")
    return True


def _wire_owner_paths(cfg: dict, args: argparse.Namespace) -> None:
    """init's owner step (#329): okl's CODEOWNERS block, and the Claude Code rules that keep an
    agent from undoing the branch rule behind it. Nothing without a recorded --owner."""
    from .. import codeowners
    owner = cfg.get("owner")
    if not owner:
        return
    path = codeowners.location(Path())
    if _refuse_symlink(path):
        return
    try:
        current = path.read_bytes().decode("utf-8") if path.is_file() else ""
        text, notes = codeowners.merge(current, owner, codeowners.owner_paths(cfg.get("owned", [])))
    except (UnicodeDecodeError, codeowners.MalformedBlockError) as e:
        print(f"! kept {path}: {e}. Fix or remove okl's lines in it, then re-run `okl init`.")
        return
    for note in notes:
        print(f"• {note}")
    if text == current:
        print(f"• owner-approved paths already current → {path}")
    else:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))       # exact bytes: the file's own line endings stay
        print(f"✓ named {owner} code owner of {', '.join(codeowners.owned(text))} → {path} (commit it; "
              "GitHub enforces it only where a branch rule requires code-owner review: `okl doctor` "
              "says whether it does here)")
    wire = _should_wire_claude(args)
    if wire[1] != _OPTED_OUT and (wire[0] or wire[1] == _BY_PLUGIN) and _merge_owner_denies(Path(".claude")):
        print("✓ added Claude Code deny rules for editing branch protection and merging as an admin "
              "→ .claude/settings.json (they advise the agent; the branch rule is what enforces)")


def _merge_owner_denies(claude: Path) -> bool:
    """Add OWNER_DENY to permissions.deny in .claude/settings.json, keeping every other entry."""
    path = claude / "settings.json"
    if _refuse_symlink(path):
        return False
    try:
        settings = json.loads(path.read_text()) if path.exists() else {}
    except json.JSONDecodeError:
        print(f"! {path} is not valid JSON — not adding okl's deny rules; add them by hand: {list(OWNER_DENY)}")
        return False
    # `permissions: null` and a missing `deny` are filled in; any other shape is the user's to fix.
    perms = settings.get("permissions") if isinstance(settings, dict) else None
    if isinstance(settings, dict) and perms is None:
        perms = settings["permissions"] = {}
    if isinstance(perms, dict) and perms.get("deny") is None:
        perms["deny"] = []
    deny = perms.get("deny") if isinstance(perms, dict) else None
    if not isinstance(deny, list):
        print(f"! {path}'s permissions are not in the shape Claude Code reads — not adding okl's deny "
              f"rules; add them by hand: {list(OWNER_DENY)}")
        return False
    missing = [rule for rule in OWNER_DENY if rule not in deny]
    if not missing:
        return False
    deny.extend(missing)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return True


def _install_claude_wiring(claude: Path, force: bool = False) -> None:
    """Install AND register the hooks: the UserPromptSubmit check (the enforced read), the
    Stop encode reminder (the write-side catch), the read briefing after a file is read
    (PostToolUse on Read, #94), and the edit checks (PostToolUse on edits, #435). Scripts come
    from the packaged scaffold — one canonical source, no drift. Also registers the MCP server
    when the extra exists."""
    hooks = claude / "hooks"
    hooks.mkdir(exist_ok=True)
    scaffold_hooks = Path(__file__).parent.parent / "scaffold" / "hooks"
    for name, label in [("userpromptsubmit-okl-check.sh", "pre-task check hook (UserPromptSubmit)"),
                        ("stop-okl-encode.sh", "encode reminder (Stop hook)"),
                        ("posttooluse-okl-read.sh", "read briefing (PostToolUse on Read)"),
                        ("posttooluse-okl-edit.sh", "edit checks (PostToolUse on edits; runs only checks "
                                                    "approved with okl on-edit add)")]:
        _place_owned(hooks / name, (scaffold_hooks / name).read_text(), label, force)
    if _merge_hook_settings(claude):
        print("✓ registered the hooks in .claude/settings.json (UserPromptSubmit, Stop, PostToolUse on Read "
              "and on edits)")
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
    _place_owned(claude / "hooks" / MCP_LAUNCHER.name, (scaffold_hooks / MCP_LAUNCHER.name).read_text(),
                 "MCP server launcher", force)
    if "okl" not in servers:
        servers["okl"] = dict(MCP_ENTRY)
        mcp_path.write_text(json.dumps(mcp_cfg, indent=2) + "\n")
        print("✓ registered okl MCP server → .mcp.json (okl_check, okl_search, okl_get, okl_record, okl_update, okl_retire)")
    elif servers["okl"] in LEGACY_MCP_ENTRIES:
        servers["okl"] = dict(MCP_ENTRY)
        mcp_path.write_text(json.dumps(mcp_cfg, indent=2) + "\n")
        print("✓ upgraded the okl MCP server in .mcp.json: it starts okl the way the hooks do, so a "
              "session without your shell's PATH still has the okl tools")


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
    from .. import ownership
    if cfg["git_hook"]:
        _install_git_hook(force=force)
    elif not cfg["ci"] or _workflow_state() == ownership.UNKNOWN:
        print("! drift is gated nowhere here (no pre-push hook, and no okl CI workflow): "
              "`okl init --git-hook` or `okl init --ci` adds a gate")


def _pinnable_version() -> str | None:
    """This okl's version when it is a release installed from an index, the only kind CI can
    install by version; None for an editable, local-path or VCS install (PEP 610 records a
    `direct_url.json` for those: the 0.11.0 review found an editable install reporting a
    version PyPI did not yet hold), for no installed metadata, and for a dev or local build."""
    from importlib import metadata

    from .. import __version__
    try:
        if metadata.distribution("observed-knowledge-ledger").read_text("direct_url.json") is not None:
            return None
    except (metadata.PackageNotFoundError, OSError, ValueError):
        # Unreadable install metadata cannot show an index install: pin nothing, as for a dev build.
        return None
    return __version__ if PUBLIC_VERSION.fullmatch(__version__) else None


def _version_key(version: str) -> tuple:
    """A public version's PEP 440 order; for anything else, a key that orders before every version.

    0.11.0a1 < 0.11.0rc1 < 0.11.0 < 0.11.0.post1, and 0.11 == 0.11.0. Ordering the release
    numbers alone put a release candidate level with its final, so init replaced a final pin
    with the candidate (the 0.11.0 review)."""
    m = PUBLIC_VERSION.fullmatch(version)
    if m is None:
        return ((), -1, 0, -1)          # below every pre-release rank, so below "0a0" too
    release, pre, pre_n, post = m.groups()
    numbers = [int(x) for x in release.split(".")]
    while numbers and numbers[-1] == 0:
        numbers.pop()
    pre_rank = {"a": 0, "b": 1, "rc": 2, None: 3}[pre]
    return (tuple(numbers), pre_rank, int(pre_n or 0), int(post) if post else -1)


def _pin_okl_version() -> None:
    """Write the okl release CI installs (OKL_VERSION_FILE), never moving it backwards.

    A teammate on an older okl, or on a dev build, keeps the pin as it is: rewriting it would
    roll CI back, and two okl versions would flip it on every init. okl's own repo pins nothing,
    since its workflow installs the checkout.
    """
    if Path("src/okl/__init__.py").is_file() or _refuse_symlink(OKL_VERSION_FILE):
        return
    ours = _pinnable_version()
    try:
        current = OKL_VERSION_FILE.read_text().strip() if OKL_VERSION_FILE.is_file() else ""
    except (OSError, ValueError) as e:
        # Not overwritten: a file okl cannot read is not one it can tell is its own.
        print(f"! kept {OKL_VERSION_FILE}: unreadable ({type(e).__name__}). Fix or delete it, "
              f"then re-run; CI's install step fails on it until then.")
        return
    if ours is None:
        stays = f"stays on okl {current}" if current else "installs the newest okl release"
        print(f"• CI {stays}: this okl is a dev or source build, so it moves no pin")
    elif _version_key(current) > _version_key(ours):
        print(f"• CI stays on okl {current} ({OKL_VERSION_FILE}), newer than this okl ({ours})")
    elif _version_key(current) == _version_key(ours):
        print(f"• CI already pinned to okl {current} → {OKL_VERSION_FILE}")
    else:
        # Missing, older, or not a version at all (CI refuses that one): this okl's release.
        OKL_VERSION_FILE.parent.mkdir(parents=True, exist_ok=True)
        OKL_VERSION_FILE.write_text(ours + "\n")
        print(f"✓ CI pinned to okl {ours} → {OKL_VERSION_FILE} (commit it; `okl init` after an "
              f"upgrade moves it)")


def _install_ci_verifier(force: bool = False) -> None:
    """Install the CI verifier workflow instead of printing a copy instruction, and pin the okl
    release it installs."""
    from .. import ownership
    _place_owned(WORKFLOW, WORKFLOW_SRC.read_text(), "CI verifier (drift gate + repo gates on every PR)",
                 force)
    # Only okl's workflow (edited or not) reads the pin: beside another tool's file, or a refused
    # symlink, a pin would be a file nothing uses.
    if _symlinked(WORKFLOW) is not None or _workflow_state() not in (ownership.OKL, ownership.MODIFIED):
        print(f"• no CI pin written: {WORKFLOW} is not okl's workflow")
    elif not _workflow_reads_pin():
        print(f"! no CI pin written: {WORKFLOW} is kept as edited, and its install step does not "
              f"read {OKL_VERSION_FILE.as_posix()} (it predates 0.11.0, or the step was changed), so "
              "CI installs the newest okl. `okl init --force` replaces it with okl's workflow.")
    else:
        _pin_okl_version()


def _say_review_after_writing(cfg: dict) -> None:
    """With the review after writing on, say so, and say when this project's Stop hook cannot
    ask for it: an edited copy from before it, which init keeps unless --force. Read from the
    copy on disk, comments ignored, as _workflow_reads_pin reads the workflow. A hook okl's
    plugin provides lives outside the project and is not read."""
    if not cfg.get("review_after_writing"):
        return
    print("• review after writing: on. Before the agent finishes, the Stop hook asks it to check its "
          "code against the lessons (`okl check --change`)")
    try:
        text = STOP_HOOK.read_text(errors="replace")
    except OSError:
        return
    if not any("check --change" in line for line in text.splitlines() if not line.lstrip().startswith("#")):
        print(f"! {STOP_HOOK} is an edited copy that does not ask for it, so the review will not run. "
              "`okl init --force` replaces it with okl's.")


STOP_HOOK = Path(".claude/hooks/stop-okl-encode.sh")


def _workflow_reads_pin() -> bool:
    """Whether the workflow at WORKFLOW reads the pin. One okl wrote before 0.11.0, edited since
    (Dependabot bumps it) and so kept, installs the newest okl whatever the pin says: writing it
    there reported a pin CI never used (the 0.11.0 release sweep)."""
    try:
        text = WORKFLOW.read_text(errors="replace")
    except OSError:
        return False
    # The `Install okl` step's own commands: a comment, or another step, naming the file reads
    # nothing (review of the 0.11.0 release).
    step = re.split(r"\n\s*- name:", text.split("- name: Install okl", 1)[1], maxsplit=1)[0] \
        if "- name: Install okl" in text else ""
    return any(OKL_VERSION_FILE.as_posix() in line for line in step.splitlines()
               if not line.lstrip().startswith("#"))


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
