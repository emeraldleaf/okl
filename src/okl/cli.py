"""okl CLI — init / connect / check / record / search / seed / metric / serve.

Stdlib argparse only, so the package installs with zero required deps for the
local + client path. `serve` and `mcp` import their extras lazily.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import core
from .client import Client, OKLUnreachableError, _find_config, load_config, save_config

if TYPE_CHECKING:
    from collections.abc import Sequence

    from .drift import DriftHit
    from .store import Node


def _print_json(obj: object) -> None:
    """Dump a result as indented JSON.

    The `--format json` path exists so other tools can consume a check without
    parsing the human briefing, which is markdown and free to change wording.
    """
    json.dump(obj, sys.stdout, indent=2)
    sys.stdout.write("\n")


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
    from . import ownership
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
    if dst.suffix == ".sh":
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
    from . import ownership
    scaffold = Path(__file__).parent / "scaffold"
    kept: list[str] = []
    for dst, src in [(Path(".claude/hooks/userpromptsubmit-okl-check.sh"),
                      scaffold / "hooks" / "userpromptsubmit-okl-check.sh"),
                     (Path(".claude/hooks/stop-okl-encode.sh"),
                      scaffold / "hooks" / "stop-okl-encode.sh"),
                     (Path(".github/workflows/okl-verify.yml"), scaffold / "ci" / "okl-verify.yml")]:
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

    from . import coexist
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


def _init_dry_run(args: argparse.Namespace) -> int:
    """`okl init --dry-run`: every path init would touch, and nothing written."""
    repo = args.repo or Path.cwd().name
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
    if Path(".git").exists() and not _ci_wanted(args, load_config()):
        print("  (no CI workflow: --no-ci, or an earlier init recorded it)")
    elif Path(".git").exists():
        print("  .github/workflows/okl-verify.yml        a CI workflow running the drift gate on PRs")
    else:
        print("  (not a git repository, so no CI workflow and no drift gate)")
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


def _ci_wanted(args: argparse.Namespace, cfg: dict) -> bool:
    """Whether init installs the CI workflow: --ci/--no-ci when given, else what an earlier
    init recorded (#111). Remembered because init restores missing files by design, so a
    deleted workflow came back on the next run."""
    flag = getattr(args, "ci", None)
    return cfg.get("ci", True) if flag is None else flag


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
    repo = args.repo or Path.cwd().name
    cfg = load_config()
    cfg["repo"] = repo
    if args.service:
        cfg["service_url"] = args.service
    _init_interests(cfg, args)
    # Pin how to invoke okl on THIS machine, for hooks running outside the dev shell
    # (agent harnesses don't inherit venv/pipx PATH entries). Machine-local by design —
    # .okl/ is gitignored; hooks fall back to PATH and `python3 -m okl` regardless.
    cfg["okl_bin"] = shutil.which("okl") or f"{sys.executable} -m okl"
    if getattr(args, "ci", None) is not None:
        cfg["ci"] = args.ci
    path = save_config(cfg)
    print(f"✓ wrote {path}  (repo={repo}, mode={'remote' if cfg.get('service_url') else 'local'}"
          + (f", interests={','.join(cfg['interests'])}" if cfg.get("interests") else "") + ")")

    _wire_claude_code(args)
    if _ci_wanted(args, cfg):
        _install_ci_verifier(force=getattr(args, "force", False))
    else:
        print("• no CI workflow (--no-ci, recorded in .okl/config.json); run `okl drift --gate` "
              "from your own CI or a hook")
    if not getattr(args, "no_seed", False):
        _seed_first_run(Client())
    for line in _empty_store_guidance(Client()):
        print(line)
    # Said at install time, the one moment someone is reading okl's output and deciding
    # what to wire. Informational here: init succeeded; `okl doctor` is the re-runnable check.
    from . import coexist
    found = coexist.detect(Path.cwd(), Path.home())
    if found:
        print("\n" + coexist.render(found))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    """Report agent-memory tools installed beside okl and how they collide (#40).

    Exit 1 when any is found, or when okl itself is wired twice (its plugin enabled AND
    its hooks registered in the project or user settings, so every prompt is briefed
    twice) -- findings,
    per the CLI contract -- and 0 when neither is. It reads settings files only and
    changes nothing.
    """
    from . import coexist
    cfg = _find_config()
    root = cfg.parent.parent if cfg else Path.cwd()
    found = coexist.detect(root, Path.home())
    print(coexist.render(found))
    twice = coexist.double_wiring(root, Path.home())
    if twice:
        print(f"\n! {twice}")
    # Informational: a choice, not a finding (#111). A diagnostic must not end in a
    # traceback, so an unreadable config simply does not report it (CodeRabbit on #112).
    try:
        ci_off = cfg is not None and json.loads(cfg.read_text()).get("ci") is False
    except (OSError, ValueError, AttributeError):
        ci_off = False
    if ci_off:
        print("\n• drift is not gated in CI here (okl init --no-ci); run `okl drift --gate` from "
              "another CI or a git hook")
    return 1 if (found or twice) else 0


def _install_claude_wiring(claude: Path, force: bool = False) -> None:
    """Install AND register the hooks: the UserPromptSubmit check (the enforced read) and the
    Stop encode reminder (the write-side catch). Scripts come from the packaged scaffold —
    one canonical source, no drift. Also registers the MCP server when the extra exists."""
    hooks = claude / "hooks"
    hooks.mkdir(exist_ok=True)
    scaffold_hooks = Path(__file__).parent / "scaffold" / "hooks"
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


def _install_ci_verifier(force: bool = False) -> None:
    """Install the CI verifier workflow instead of printing a copy instruction; warn
    loudly when git is absent, because the drift layer is dead without history."""
    if not Path(".git").exists():
        print("⚠ not a git repository — the drift verifier (okl drift) and the CI gate are DISABLED")
        print("  until `git init`: drift compares governed files against their last-verified commit.")
        return
    wf = Path(".github") / "workflows" / "okl-verify.yml"
    src = Path(__file__).parent / "scaffold" / "ci" / "okl-verify.yml"
    _place_owned(wf, src.read_text(), "CI verifier (drift gate + repo gates on every PR)", force)


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


def cmd_check(args: argparse.Namespace) -> int:
    """Print the lessons that apply to `--task`, in the shape `--format` names.

    Exit 0 when the check ran, even if nothing applies; 2 when it could not run (no
    config, an unreachable store, or a rejected request), so a hook never reads a
    failure as a clean check.
    """
    client = Client()
    if not client.configured:
        # FAIL CLOSED. Without a config there is no store to read; proceeding would
        # create an empty database here and then report a clean check against it —
        # "no rules apply" when the truth is "nothing was ever asked".
        print("OKL NOT CONFIGURED — refusing to report a clean check.\n"
              "No .okl/config.json in this directory or any parent, and no OKL_SERVICE_URL.\n"
              "Run `okl init` here, or `okl connect <url>` to point at a shared store.",
              file=sys.stderr)
        return 2
    # An explicit --interests overrides the repo's configured list for this one call.
    # `--interests ""` means "no filtering", which is distinct from omitting the flag
    # (use the config). The eval harness needs this: inheriting the host repo's interests
    # made one of its tasks silently measure the absence of the rule it tests.
    # getattr, not attribute access: tests and library callers construct a Namespace by
    # hand with only the fields they care about, and a command handler that assumes the
    # full argparse surface breaks for every caller that is not the parser.
    override = getattr(args, "interests", None)
    if override is not None:
        client.interests = [t.strip().lower() for t in override.split(",") if t.strip()]
    try:
        result = client.check(args.task, repo=args.repo, limit=args.limit)
    except OKLUnreachableError as e:
        # FAIL CLOSED — loud, non-zero, no reassuring empty result.
        print(f"OKL UNREACHABLE — refusing to report a clean check.\n{e}", file=sys.stderr)
        return 2
    except ValueError as e:
        # A 4xx (usually a 401 against a token-protected service) is a REFUSED check,
        # not a clean one, so it fails closed just the same. It gets its own message
        # because the fix is different: a credential, not connectivity. Before this,
        # an unauthorized check exited 0 with a raw urllib traceback.
        print(f"OKL REFUSED THE CHECK — refusing to report a clean check.\n{e}", file=sys.stderr)
        return 2
    if args.format == "hook":
        # What a Claude Code UserPromptSubmit hook prints: the briefing into the model's
        # context, and one line the person can see. OKL_QUIET=1 keeps the line out.
        out: dict[str, Any] = {"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": core.render_check_for_agent(result)}}
        notice = None if os.environ.get("OKL_QUIET") == "1" else core.briefing_notice(result)
        if notice:
            out["systemMessage"] = notice
        print(json.dumps(out))
        return 0
    if args.format == "json":
        _print_json(result)
    elif args.format == "actions":
        # compact: the imperative list only, for small-context callers (subagents, CI)
        print(core.render_actions_only(result, limit=args.limit))
    else:
        print(core.render_check_for_agent(result))
    # stdout is what the UserPromptSubmit hook hands the agent; setup advice is for the
    # person, so it goes to stderr and never enters the agent's context. Skipped for json,
    # whose consumers parse the output.
    if args.format != "json" and result.get("store_records") == 0:
        for line in _empty_store_guidance(client):
            print(line, file=sys.stderr)
    return 0


def cmd_record(args: argparse.Namespace) -> int:
    """Write one record to the store.

    Validation errors (an unknown tag, a malformed scope) are the caller's mistake and
    exit 2 with the message, which names the vocabulary. A traceback would bury the one
    line that tells them how to fix the call.
    """
    if args.verified:
        # A stamp the recorder awards itself is the step grading its own homework. The
        # README said live verification refused this; it accepted it, silently, and the
        # shipped encoding-loop skill told agents to pass it. Found checking a launch post
        # that claimed "never by assertion". Historical receipts still import via `okl seed`.
        print("okl record --verified is refused: a lesson is verified by running a check, not "
              "by saying so.\n  Record it without --verified, then run `okl verify <id>` to see the "
              "tests that touch its files, or ask your agent to prove it.\n  (Importing historical, "
              "already-verified records? Use okl seed.)", file=sys.stderr)
        return 2
    client = Client()
    kwargs = dict(type=args.type, title=args.title, scope=args.scope,
                  applies_to=getattr(args, "applies_to", None),
                  body=args.body, status=args.status, found_by=args.found_by,
                  ttl_days=args.ttl_days, owner=args.owner,
                  files=args.files, symptom=args.symptom, fix=args.fix, tags=args.tags,
                  id=args.id)
    if args.repo:
        kwargs["repo"] = args.repo
    try:
        node_id = client.record(**{k: v for k, v in kwargs.items() if v is not None})
    except ValueError as e:
        # An unknown tag or a malformed scope is the caller's mistake, and the exception
        # text names the vocabulary they need. A traceback buries that under a stack.
        print(f"NOT RECORDED — {e}", file=sys.stderr)
        return 2
    except OKLUnreachableError as e:
        print(f"NOT RECORDED — {e}", file=sys.stderr)
        return 2
    print(node_id)
    return 0


def cmd_link(args: argparse.Namespace) -> int:
    """Join two records with a typed edge (e.g. a Gate CATCHES a Defect).

    Edges are what let a briefing say WHY a gate is armed rather than just naming it.
    """
    Client().link(args.src, args.rel, args.dst)
    print(f"✓ {args.src} -[{args.rel}]-> {args.dst}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Run the named check, and stamp the node verified ONLY on an observed pass.

    The evidence trail (command, expect-match, timestamp) is stored on the node —
    the store-side mechanization of verify-before-claiming: no run, no stamp."""
    import subprocess
    from datetime import datetime, timezone
    if not args.run:
        return _suggest_check(args.node_id)
    try:
        r = subprocess.run(args.run, shell=True, capture_output=True, text=True,
                           timeout=args.timeout)
    except subprocess.TimeoutExpired:
        # Uncaught, one slow check ended `okl reverify` in a traceback and left every
        # later lesson unchecked (CodeRabbit on #79). A timeout is a failed check.
        print(f"✗ check TIMED OUT after {args.timeout}s — NOT stamping verification.",
              file=sys.stderr)
        return 1
    output = (r.stdout or "") + (r.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-5:])
    if r.returncode != 0:
        print(f"✗ check FAILED (exit {r.returncode}) — NOT stamping verification.\n{tail}",
              file=sys.stderr)
        return 1
    if args.expect and args.expect not in output:
        # exit 0 alone is a step grading itself — require the positive success signal
        # when the caller names one (the exit-0-zero-files lesson).
        print(f"✗ check exited 0 but expected signal {args.expect!r} NOT in output — NOT stamping.\n{tail}",
              file=sys.stderr)
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    # The commit the check passed at: drift diffs the governed files there against HEAD
    # instead of comparing clocks (#102). It goes into the evidence before the stamp, which
    # binds it in the committed snapshot and keeps older okl versions able to read it.
    root = _snapshot_path().parent
    commit = _head_commit(root)
    evidence = (f"`{args.run}` exit 0" + (f", matched {args.expect!r}" if args.expect else "")
                + (f" on commit {commit[:12]}" if commit else "") + f" @ {stamp}")
    try:
        node = Client().verify(args.node_id, evidence, commit=commit)
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — check passed but the stamp was NOT recorded.\n{e}", file=sys.stderr)
        return 2
    print(f"✓ verified {node['id']} — {node['title']}\n  evidence: {node['verified_by']}")
    dirty = _uncommitted(root, node.get("files")) if commit else []
    if dirty:
        # The check saw these edits, but the stamp is the commit without them, so the lesson
        # reads as changed the moment they are committed. Commit first, then verify.
        print(f"  ! uncommitted changes to {', '.join(dirty[:3])}{' …' if len(dirty) > 3 else ''}: "
              "commit them, then verify again, or this lesson will show as drifted",
              file=sys.stderr)
    # Keep CI's view in step. A snapshot that exists is one CI reads, and re-verifying
    # without re-exporting leaves CI red for a rule that is green here -- the safe
    # direction, but a step everyone would forget. The FIRST snapshot is created here too,
    # when the verified lesson governs files: it used to need a separate `okl export
    # --drift` that the getting-started guide had to teach as a trap. Never for a lesson
    # without files -- a snapshot of zero rules is one CI rightly reads as broken.
    snap = _snapshot_path()
    if snap.exists() or node.get("files"):
        try:
            existed = snap.exists()
            _write_snapshot(Client(), snap)
            print(f"  {'refreshed' if existed else 'created'} {snap.name} — commit it so CI sees this verification")
        except OKLUnreachableError as e:
            print(f"  ! {snap.name} NOT refreshed: {e}", file=sys.stderr)
    return 0


_GENERIC_STEMS = {"src", "lib", "app", "main", "index", "test", "tests", "pages", "utils", "util",
                  "init", "__init__", "core", "common", "components", "styles", "docs", "readme"}


def _tests_touching(root: Path, files: str | None, limit: int = 5) -> list[str]:
    """Tracked test files that mention a governed file by name: the likeliest checks."""
    import subprocess
    stems = set()
    for glob in (files or "").split(","):
        name = glob.strip().rstrip("/").rsplit("/", 1)[-1]
        stem = name.split(".")[0]
        if len(stem) >= 4 and not any(c in stem for c in "*?[") and stem.lower() not in _GENERIC_STEMS:
            stems.add(stem)
    if not stems:
        return []
    listed = subprocess.run(["git", "-C", str(root), "ls-files"], capture_output=True, text=True)
    tests = [p for p in listed.stdout.splitlines()
             if any(t in p.lower() for t in ("test", "spec"))][:2000]
    if not tests:
        return []
    args = ["git", "-C", str(root), "grep", "-l", "-I", "-F"]
    for s in sorted(stems):
        args += ["-e", s]
    found = subprocess.run([*args, "--", *tests], capture_output=True, text=True)
    return found.stdout.splitlines()[:limit]


def _suggest_check(node_id: str) -> int:
    """`okl verify <id>` with no --run: what the lesson says, the files it covers, and the
    tests that already mention them -- the parts a person has to supply, found for them.

    The three-part command was the step people could not fill in ("how am I supposed to
    know them?"); this answers it from the store and the repo. Exit 2: nothing was stamped.
    """
    client = Client()
    try:
        node = next((n for n in client.all_nodes() if n.id == node_id), None)
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot look the lesson up.\n{e}", file=sys.stderr)
        return 2
    if node is None:
        print(f"no lesson with id {node_id!r}. `okl drift` and the briefing show ids in brackets.",
              file=sys.stderr)
        return 2
    print(f"[{node.id}] {node.title}")
    if node.symptom:
        print(f"  when you see: {node.symptom}")
    if node.fix:
        print(f"  the lesson says: {node.fix}")
    root = _snapshot_path().parent
    if node.files:
        print(f"  covers: {node.files}")
        tests = _tests_touching(root, node.files)
        if tests:
            print("\nTests that mention those files, the likeliest checks:")
            for t in tests:
                print(f"  {t}")
            # Quoted, because the user pastes this and `okl verify --run` hands it to a shell:
            # a tracked test file named `a; rm -rf x.py` must arrive as one argument.
            run = (f"pytest -q {shlex.quote(tests[0])}" if tests[0].endswith(".py")
                   else "<the command that runs that test>")
            print(f"\nIf one of them fails when the lesson is broken, prove the lesson with it:\n"
                  f"  okl verify {shlex.quote(node.id)} --run {shlex.quote(run)} --expect passed")
        else:
            # A search miss, not proof: a test can cover a lesson by driving the command
            # without ever naming the file.
            print("\nNo test mentions those files by name. One may still cover the lesson by driving\n"
                  "the command instead, so look for it before writing a new check.")
    print("\nOr ask your agent to prove it: it reads the lesson, finds or writes a test that fails\n"
          "when the lesson is broken, runs it, and records the result. Nothing was stamped.")
    return 2


def _head_commit(root: Path) -> str | None:
    """HEAD's full commit name for the repository at `root`, or None outside git."""
    import subprocess
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--verify", "-q", "HEAD"],
                             capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    sha = out.stdout.strip()
    return sha if out.returncode == 0 and re.fullmatch(r"[0-9a-f]{40,64}", sha) else None


def _uncommitted(root: Path, files: str | None) -> list[str]:
    """Governed paths with uncommitted changes, as git reports them (empty when clean)."""
    import subprocess
    specs = [g.strip() for g in (files or "").split(",") if g.strip()]
    if not specs:
        return []
    try:
        out = subprocess.run(["git", "-C", str(root), "status", "--porcelain", "--", *specs],
                             capture_output=True, text=True, timeout=15)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    return [line[3:] for line in out.stdout.splitlines() if len(line) > 3] if out.returncode == 0 else []


def _stored_check(verified_by: str | None) -> tuple[str, str | None] | None:
    """The command and expected signal `okl verify` recorded, or None if there is none
    (never verified, or stamped by an import that carried no evidence)."""
    import ast
    if not verified_by or not verified_by.startswith("`"):
        return None
    end = verified_by.rfind("` exit 0")
    if end <= 0:
        return None
    run = verified_by[1:end]
    rest = verified_by[end + len("` exit 0"):]
    expect = None
    if rest.startswith(", matched "):
        lit = rest[len(", matched "):].rsplit(" @ ", 1)[0]
        lit = re.sub(r" on commit [0-9a-f]{7,64}$", "", lit)   # the commit #102 records
        try:
            expect = ast.literal_eval(lit)
        except (ValueError, SyntaxError):
            return None
    return run, expect


def _reverify_permitted(args: argparse.Namespace, planned: bool, manual: bool) -> int | None:
    """None to go ahead and run the listed commands, or the exit code to stop with."""
    if not planned or getattr(args, "dry_run", False):
        return 1 if (manual or planned) else 0
    if args.yes:
        return None
    if not sys.stdin.isatty():
        print("refusing to run stored commands unattended: review them above, then pass --yes",
              file=sys.stderr)
        return 2
    return None if input("Run them? [y/N] ").strip().lower() in ("y", "yes") else 2


def cmd_reverify(args: argparse.Namespace) -> int:
    """Re-run the stored check of every drifted lesson and re-stamp the ones that pass.

    `okl verify` already records the exact command and expected signal as evidence, so a
    drifted lesson's re-check is known. Retyping each one was the step that made drift
    upkeep a chore (issue #63). The commands come from the STORE, which on a shared
    service holds records other people wrote, so they are listed and run only after a
    confirmation or --yes: stored data reaching a shell unasked is how a shared store
    becomes remote code execution.
    """
    from . import drift
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — nothing to re-verify. Run `okl init` first.", file=sys.stderr)
        return 2
    try:
        nodes = client.all_nodes()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot re-verify.\n{e}", file=sys.stderr)
        return 2
    by_id = {n.id: n for n in nodes}
    hits, _ = drift.scan_drift(nodes, client.repo, repo_dir=str(_snapshot_path().parent))
    if not hits:
        print("okl reverify: nothing has drifted.")
        return 0
    plan, manual = [], []
    for h in hits:
        chk = _stored_check(by_id[h.node_id].verified_by)
        (plan.append((h, chk)) if chk else manual.append(h))
    for h in manual:
        print(f"• [{h.node_id}] {h.title}\n    no stored check yet: ask your agent to write one, or run "
              f"`okl verify {h.node_id}` to see the tests that touch its files")
    if plan:
        print(f"okl reverify will run {len(plan)} stored check(s), from the store:")
        for h, (run, _exp) in plan:
            print(f"  [{h.node_id}] {run}")
    stop = _reverify_permitted(args, bool(plan), bool(manual))
    if stop is not None:
        return stop
    failed = 0
    for h, (run, exp) in plan:
        rc = cmd_verify(argparse.Namespace(node_id=h.node_id, run=run, expect=exp, timeout=args.timeout))
        failed += rc != 0
    print(f"okl reverify: {len(plan) - failed} re-verified, {failed} failed, {len(manual)} need a first check.")
    return 1 if (failed or manual) else 0


def _snapshot_path() -> Path:
    """Where the committed drift snapshot lives: the project root, found the way the
    config is, so running from a subdirectory neither misses it nor writes a second one."""
    from . import drift
    cfg = _find_config()
    return (cfg.parent.parent if cfg else Path.cwd()) / drift.SNAPSHOT_FILE


def _write_snapshot(client: Client, path: Path) -> int:
    from . import drift
    snap = drift.snapshot(client.all_nodes(), client.repo)
    path.write_text(drift.dump_snapshot(snap))
    return len(snap["rules"])


def cmd_export(args: argparse.Namespace) -> int:
    """Write the committed drift snapshot CI reads when it has no store (issue #36)."""
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — nothing to export. Run `okl init`, `okl connect <url>`, "
              "or set OKL_DATABASE_URL.", file=sys.stderr)
        return 2
    path = Path(args.output) if args.output else _snapshot_path()
    try:
        n = _write_snapshot(client, path)
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — nothing exported.\n{e}", file=sys.stderr)
        return 2
    if n == 0:
        # An empty snapshot would make CI report NOTHING CHECKED, which is honest, but
        # committing one is almost certainly a mistake worth saying so about.
        print(f"wrote {path} with 0 rules — no rule in this store governs files "
              "(`okl record ... --files <globs>` enrolls one)", file=sys.stderr)
        return 2
    print(f"wrote {path}: {n} rule(s). Commit it — CI's drift gate reads the committed copy.")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    """Free-text search across the encoded body.

    Distinct from `check`: search answers "what do we know about X", check answers
    "what applies to the task I am about to start" and applies scope, interest and
    cutoff filtering on the way.
    """
    client = Client()
    # A wrong --scope used to return an empty list and exit 0, which reads as "this repo
    # has learned nothing" when it actually means "you typed the scope wrong". `--scope
    # repo` is the obvious guess and silently found nothing, because the stored form is
    # `repo:<name>`. Reporting an empty result and a misspelling identically is the
    # silence-as-safety failure `check` already refuses to make about an empty store.
    scope = args.scope
    if scope:
        if scope in ("repo", "local", "this"):
            scope = f"repo:{client.repo}"          # shorthand: the configured repo
        elif scope != "org" and not (scope.startswith("repo:") and scope[5:].strip()):
            print(f"REFUSING: --scope {scope!r} is not a scope. Use 'org', 'repo:<name>', "
                  f"or 'repo' for this repo ({client.repo}).", file=sys.stderr)
            return 2
    results = client.search(args.query, scope=scope,
                            node_types=args.type, limit=args.limit)
    # A well-formed scope naming a repo the store has never heard of is almost certainly a
    # typo, and returns the same empty list as a real repo that has recorded nothing yet.
    # Distinguish them the way `check` distinguishes "no rules apply" from "empty store" —
    # a warning, never a refusal, because a fresh repo legitimately has no records.
    if not results and scope and scope.startswith("repo:"):
        known = sorted({n["scope"] for n in client.search("", limit=10_000)
                        if n["scope"].startswith("repo:")})
        if known and scope not in known:
            print(f"note: no record anywhere carries scope {scope!r}. The store knows "
                  f"{', '.join(known)} — check for a typo.", file=sys.stderr)
    if args.format == "json":
        _print_json(results)
    else:
        for r in results:
            tag = " (STALE)" if r.get("stale") else ""
            print(f"[{r['type']:10}] {r['scope']:16} {r['title']}{tag}")
    return 0


def cmd_metric(args: argparse.Namespace) -> int:
    """Recurrence, with the coverage that makes the number readable (issue #31)."""
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — refusing to report a metric about a store that is not "
              "there. Run `okl init` or `okl connect <url>`.", file=sys.stderr)
        return 2
    try:
        report = client.recurrence_report()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot compute metric.\n{e}", file=sys.stderr)
        return 2
    if report is None:
        print("OKL: the connected service predates the coverage report, so this metric's "
              "coverage is unknown. Upgrade the service before reading it.", file=sys.stderr)
        return 2
    if args.format == "json":
        _print_json(report)
        return 0
    armed, unarmed = report["armed"], report["unarmed"]
    total, gated = report["defects"], report["defects_with_gate"]
    pct = f" ({100 * gated // total}%)" if total else ""
    # No tick. "0" here speaks only for defects that have a gate; the line says how many
    # that is, so a low-coverage zero cannot read as a result.
    print(f"recurrence-after-arming: {len(armed)} — among the {gated} of {total} "
          f"defects that have a gate{pct}")
    for r in armed:
        print(f"  {r['defect_class']}  recurred in {r['recurred_in']}  "
              f"(gate: {', '.join(r['gates'])})")
    print(f"recurrence without a gate: {len(unarmed)}"
          + (" — lessons that were written down and came back anyway:" if unarmed else ""))
    for r in unarmed:
        print(f"  {r['defect_class']}  recurred in {r['recurred_in']}")
    return 0


def cmd_drift(args: argparse.Namespace) -> int:
    """Source-vs-spec drift: rules whose governed code changed after last verification."""
    from . import drift
    client = Client()
    if args.snapshot:
        return _drift_from_snapshot(args, client)
    # Refused before any store is opened. Reading an unconfigured directory created an
    # empty okl.db as a side effect, found nothing in it, and printed OK -- which is what
    # CI saw on every run, because `okl init` gitignores the store (issue #21). `check`
    # has refused an unconfigured directory for the same reason since v0.2.
    if not client.configured:
        print("OKL NOT CONFIGURED — refusing to report drift. No store is named here: run "
              "`okl init`, `okl connect <url>`, or set OKL_DATABASE_URL.", file=sys.stderr)
        return 2
    try:
        nodes = client.all_nodes()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot check drift.\n{e}", file=sys.stderr)
        return 2
    repo = args.repo or client.repo
    return _report_drift(args, drift.scan_drift(nodes, repo, repo_dir=args.repo_dir),
                         drift.governs_nothing(nodes, repo, args.repo_dir))


def _drift_from_snapshot(args: argparse.Namespace, client: Client) -> int:
    """Drift against a committed snapshot instead of a store (issue #36).

    The snapshot is the store for a job that has none: CI without a service, and every
    fork PR. It names the store, so it answers `configured` on its own. An entry whose
    timestamp does not match its evidence refuses the whole run -- one hand-cleared rule
    would otherwise pass the gate while the rest of the report looked honest.
    """
    from . import drift
    try:
        snap = drift.read_committed_snapshot(args.snapshot, args.repo_dir)
    except ValueError as e:
        print(f"OKL SNAPSHOT REFUSED — {e}", file=sys.stderr)
        return 2
    nodes, problems = drift.nodes_from_snapshot(snap)
    if problems:
        print(f"OKL SNAPSHOT REFUSED — {len(problems)} entr(y/ies) cannot be trusted; re-run "
              "`okl verify` for each and re-export:\n  " + "\n  ".join(problems), file=sys.stderr)
        return 2
    repo = args.repo or snap.get("repo") or client.repo
    return _report_drift(args, drift.scan_drift(nodes, repo, repo_dir=args.repo_dir),
                         drift.governs_nothing(nodes, repo, args.repo_dir))


def _report_drift(args: argparse.Namespace, scan: tuple[list[DriftHit], int],
                  missing: Sequence[Node] = ()) -> int:
    from . import drift
    hits, checked = scan
    # Lessons watching files that are gone are reported beside the drift, never as drift:
    # the exit code is unchanged, because what to do with them is a decision (#109).
    if args.format == "json":
        _print_json({"drift": [h.as_dict() for h in hits], "count": len(hits),
                     "checked": checked,
                     "governs_nothing": [{"node_id": n.id, "title": n.title, "files": n.files}
                                         for n in missing]})
    else:
        print(drift.render_drift(hits, checked) + drift.render_governs_nothing(list(missing)))
    if not args.gate:
        return 0
    # Under --gate the exit code is the verdict, and it follows the CLI's contract:
    # 1 = ran and found drift, 2 = did not run. A gate that checked no rule did not run,
    # however clean its output looks.
    if hits:
        return 1
    return 2 if checked == 0 else 0


def cmd_dedup(args: argparse.Namespace) -> int:
    """Report records that look like near-duplicates of each other.

    A review aid, never an auto-merge. Whether two similar records are "the same" is a
    judgment about intent, and the measured score bands for true paraphrases and for
    genuinely-distinct-but-related records overlap (see core.DEDUP_THRESHOLD). Deciding
    that automatically would delete real records.

    Duplicates are not merely untidy now that `check` applies a top-k cutoff: two records
    saying the same thing both get injected, spend the budget twice, and can push a third
    relevant record out of the briefing entirely.

    Exit 1 when it finds candidate pairs, 0 when it finds none, 2 when okl is not
    configured here.
    """
    client = Client()
    if not client.configured:
        print("OKL NOT CONFIGURED — run `okl init` here, or `okl connect <url>`.", file=sys.stderr)
        return 2
    nodes = list(client.all_nodes())
    store = client._local_store() if client.mode == "local" else None
    idf = core._idf(store) if store is not None else {}

    seen: set[tuple[str, ...]] = set()
    pairs = []
    for i, a in enumerate(nodes):
        for b in nodes[i + 1:]:
            score = core.duplicate_score(a, b, idf)
            if score >= args.threshold:
                key = tuple(sorted((a.id, b.id)))
                if key not in seen:
                    seen.add(key)
                    pairs.append((score, a, b))
    pairs.sort(key=lambda p: -p[0])

    if not pairs:
        print(f"OKL dedup: OK — no pair of the {len(nodes)} records scores at or above "
              f"{args.threshold}.")
        return 0

    print(f"OKL dedup: {len(pairs)} candidate pair(s) at or above {args.threshold}, "
          f"out of {len(nodes)} records.\n"
          "These are candidates for a human to rule on, not confirmed duplicates.\n")
    for score, a, b in pairs[: args.limit]:
        print(f"  {score:.2f}")
        for n in (a, b):
            print(f"    [{n.id}] {n.type} · {n.scope}")
            print(f"       {n.title}")
            if n.symptom:
                print(f"       symptom: {n.symptom[:88]}")
        print()
    if len(pairs) > args.limit:
        print(f"  ... {len(pairs) - args.limit} more (raise --limit)")
    print("Resolve by deciding which record is the one to keep, then RETRACT or link the\n"
          "other with SUPERSEDES — deleting loses the record that it was once believed.")
    return 1


def cmd_coverage(args: argparse.Namespace) -> int:
    """Knowledge-to-code ratio — a health signal, not a target (Codified Context §4.2)."""
    import subprocess
    client = Client()
    try:
        nodes = client.all_nodes()
    except OKLUnreachableError as e:
        print(f"OKL UNREACHABLE — cannot compute coverage.\n{e}", file=sys.stderr)
        return 2
    repo = args.repo or client.repo
    in_scope = [n for n in nodes if n.scope == "org" or n.scope == f"repo:{repo}"]
    knowledge_lines = sum(len((n.body or "").splitlines()) + 1 for n in in_scope)
    # code lines: git ls-files line count, or None if not a repo
    code_lines = None
    try:
        files = subprocess.run(["git", "-C", args.repo_dir, "ls-files"],
                               capture_output=True, text=True, timeout=15)
        if files.returncode == 0:
            code_lines = 0
            for f in files.stdout.splitlines():
                fp = Path(args.repo_dir) / f
                if fp.suffix.lower() in {".py",".cs",".ts",".tsx",".js",".jsx",".go",".rs",".java",".rb"}:
                    with contextlib.suppress(OSError):
                        code_lines += sum(1 for _ in fp.open("rb"))
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    ratio = (knowledge_lines / code_lines) if code_lines else None
    out = {"nodes_in_scope": len(in_scope), "knowledge_lines": knowledge_lines,
           "code_lines": code_lines,
           "knowledge_to_code": round(ratio, 4) if ratio is not None else None}
    if args.format == "json":
        _print_json(out); return 0
    print(f"OKL coverage for {repo}:")
    print(f"  encoded nodes in scope : {out['nodes_in_scope']}")
    print(f"  knowledge lines        : {out['knowledge_lines']}")
    print(f"  code lines             : {out['code_lines'] if out['code_lines'] is not None else '(not a git repo)'}")
    if ratio is not None:
        print(f"  knowledge-to-code      : {ratio:.1%}  (health signal — a sudden spike in agent confusion "
              "means a relevant node is missing or stale, not that this number is wrong)")
    return 0


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Propose starter nodes from repo signals into a reviewable okl-bootstrap.json."""
    from . import bootstrap
    repo = args.repo or Client().repo
    proposal = bootstrap.propose_nodes(repo, repo_dir=args.repo_dir)
    out = Path(args.out)
    out.write_text(json.dumps(proposal, indent=1))
    n = len(proposal["nodes"])
    print(f"✓ proposed {n} starter record(s) → {out}")
    if n == 0:
        print("  Nothing found. This command reads only git history and file names, so it")
        print("  comes up empty on young repos and on ones whose history is uninformative.")
    print("  Review + edit (set scope, add symptom/cause/fix, delete noise), then:")
    print(f"    okl seed {out}")
    print("\n  Better: ask your coding agent to run /seed-from-codebase (stamped by")
    print("  `okl scaffold`). It reads the code itself — the guard rails, the CI config,")
    print("  the fix commits — and proposes records with a file:line citation each.")
    return 0


def _bundled_seed_dir() -> Path:
    """Where the shipped seed packs live: the repo's seed/ in a checkout, or inside the
    installed package. Checked in that order so a clone exercises its own files."""
    repo_seed = Path(__file__).parent.parent.parent / "seed"
    return repo_seed if repo_seed.exists() else Path(__file__).parent / "seed"


def _pack_fits(pack_tags: set[str], interests: set[str]) -> bool:
    """Does a bundled pack fit a repo with these interests?

    A pack that names a stack fits only a repo that declared that stack; a pack with no
    stack fits on any shared subject. One shared subject is not enough on its own: the
    .NET packs carry `security` on a handful of records, so any-tag matching recommended
    109 .NET records to a repo that had declared `react, security`. That is REPORT §4d's
    mistake — reading a label on some records as a verdict on the whole — made at the
    point of import, where it is worse, because a pack imports every record at once.
    """
    tags = {t.lower() for t in pack_tags}
    stacks = tags & core.STACK_TAGS
    if stacks:
        return bool(stacks & interests)
    return bool(tags & interests)


def _empty_store_guidance(client: Client) -> list[str]:
    """What to do about an empty store, tailored to this repo. Empty list if not needed.

    Issue #27. Tailored rather than generic, because a list of commands is homework and
    the repo already knows enough to be specific: the bundled packs describe what they
    are about, and the repo declared its interests at init, so the packs that fit can be
    named with their sizes. It still imports nothing — cmd_seed explains why that must
    stay a deliberate choice.

    Only for a LOCAL store. A connected repo shares a service's store, which is neither
    "yours" to fill nor cheap to inspect from here.

    Emptiness is asked as "is there at least one record?" — a search capped at one row —
    rather than by loading every record to count them.
    """
    if client.mode == "remote":
        return []
    try:
        if client.search("", limit=1):
            return []
    except (OSError, OKLUnreachableError, ValueError, RuntimeError):
        return []

    lines = ["• this store is empty, so every check will say it proves nothing. To fill it:"]
    interests = {t.lower() for t in (client.interests or [])}
    packs = []
    for f in sorted(_bundled_seed_dir().glob("*.json")):
        count, tags = _describe_pack(f)
        if _pack_fits(tags, interests):
            packs.append((f, count))
    if packs:
        lines.append(f"    bundled packs that match your interests ({', '.join(sorted(interests))}):")
        # Quoted: the bundled dir is a checkout or an install path, and either can contain
        # a space, which splits a copied command into two arguments.
        lines += [f"      okl seed {shlex.quote(str(f))}    ({count} records)" for f, count in packs]
    elif interests:
        lines.append("    no bundled pack matches your interests; `okl seed` lists all of them")
    else:
        lines.append("    `okl seed` lists the bundled packs (declare interests with"
                     " `okl init --interests` and they are matched for you)")
    # Name the agent-driven route only where it exists. The seeding commands are stamped by
    # `okl scaffold`, possibly under a renamed .claude dir, and pointing at one that is not
    # installed sends the reader to a command their agent will not recognise.
    #
    # Resolved from the PROJECT ROOT, not the current directory. okl finds its config by
    # walking up, so `check` runs fine from a subdirectory — where a cwd-relative lookup
    # both missed a command installed at the root and advised `okl scaffold .`, which
    # would have stamped the whole kit into that subdirectory.
    cfg = _find_config()
    root = cfg.parent.parent if cfg else Path.cwd()
    if any(root.glob("*/commands/seed-from-codebase.md")):
        lines.append("    ask your agent to run /seed-from-codebase: it proposes cited records"
                     " from this repo's own code")
    else:
        rel = os.path.relpath(root, Path.cwd())
        lines.append(f"    `okl scaffold {shlex.quote(rel)}` adds /seed-from-codebase, which has"
                     " your agent propose cited records from this repo's own code")
    lines.append("    or write one yourself: okl record --type Rule --scope repo --title \"...\"")
    return lines


def _seed_first_run(client: Client) -> None:
    """Give an EMPTY local store something to brief: the starter lessons, plus the bundled
    packs that fit this repo's interests. Never a store that already has records — seeding
    goes through record(), which would re-stamp their verification times — and never a
    shared service's store, which is not this repo's to fill."""
    from .seed import seed_from_file, seed_starter
    if client.mode == "remote":
        return
    try:
        if client.search("", limit=1):
            return
    except (OSError, OKLUnreachableError, ValueError, RuntimeError):
        return
    seed_dir = _bundled_seed_dir()
    n = seed_starter(client, seed_dir)
    interests = {t.lower() for t in (client.interests or [])}
    packs = []
    for f in sorted(seed_dir.glob("*.json")):
        _, tags = _describe_pack(f)
        # Stack packs only: a pack with no stack tag fits on any shared subject, which is
        # the starter's job, not a reason to import a whole pack.
        if tags & core.STACK_TAGS and _pack_fits(tags, interests):
            packs.append((f.stem, seed_from_file(client, str(f))))
    print(f"✓ seeded {n} starter lessons (portable: web security, CI, docs, verification)"
          + ("; packs for your stack: " + ", ".join(f"{p} ({c})" for p, c in packs) if packs else ""))
    print("  your own rules matter most: okl record ... (see docs/GETTING-STARTED.md). --no-seed skips this")


def _describe_pack(path: Path) -> tuple[int, set[str]]:
    """Count a pack's records and collect its subject tags, so the listing can say what
    a pack is ABOUT before anyone imports it."""
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return 0, set()
    tags: set[str] = set()
    for node in data.get("nodes", []):
        tags |= {t.strip() for t in (node.get("tags") or "").split(",") if t.strip()}
    return len(data.get("nodes", [])), tags


def _list_seed_packs(seed_dir: Path, interests: set[str]) -> int:
    """Print the bundled packs, marking those that fit this repo's interests; import nothing.

    Exits 1 when there are no packs to list, which means a broken install.
    """
    packs = sorted(str(f) for f in seed_dir.glob("*.json"))
    if not packs:
        print(f"no seed packs found under {seed_dir}")
        return 1
    print("Seed packs available (nothing has been imported):\n")
    for pk in packs:
        f = Path(pk)
        count, tags = _describe_pack(f)
        hit = " <- matches your interests" if _pack_fits(tags, interests) else ""
        print(f"  {f.name:38} {count:3} records  [{', '.join(sorted(tags)) or 'untagged'}]{hit}")
    print("\nThese hold real rules from specific stacks. Import the ones that match")
    print("your project rather than all of them:\n")
    print("  okl seed <pack>                       one pack, by name (e.g. okl seed dotnet-defects)")
    print("  okl seed --all                        every pack above")
    if interests:
        print(f"\nThis repo declares: {', '.join(sorted(interests))}. Records tagged outside")
        print("those subjects stay filtered out of briefings even once imported.")
    else:
        print("\nTip: `okl init --interests \"<subjects>\"` filters what reaches a briefing.")
    return 0


def cmd_seed(args: argparse.Namespace) -> int:
    """Import seed packs — deliberately a choice, not a default.

    The bundled packs carry real rules from specific stacks. Importing all of them into
    an unrelated project fills its briefings with noise about frameworks it does not use,
    and because they are org-scoped that noise then reaches every connected repo. So a
    bare `okl seed` lists what is available and imports nothing; `--all` is the explicit
    opt-in.
    """

    from .seed import seed_from_file
    seed_dir = _bundled_seed_dir()
    interests = {t.lower() for t in (Client().interests or [])}

    if not args.path and not args.all:
        return _list_seed_packs(seed_dir, interests)

    if args.all:
        targets = sorted(str(f) for f in seed_dir.glob("*.json"))
    else:
        path = Path(args.path)
        # A bundled pack by name -- `okl seed dotnet-defects` -- when no such path exists.
        # `init` used to print the pack's absolute path inside site-packages for the user
        # to paste; a name is what the listing shows and what a README can say.
        if not path.exists():
            bundled = seed_dir / (args.path if args.path.endswith(".json") else f"{args.path}.json")
            if bundled.is_file():
                path = bundled
            else:
                names = ", ".join(sorted(f.stem for f in seed_dir.glob("*.json")))
                print(f"no seed file at {args.path!r}, and no bundled pack of that name. "
                      f"Bundled packs: {names}", file=sys.stderr)
                return 2
        targets = sorted(str(f) for f in path.glob("*.json")) if path.is_dir() else [str(path)]
    if not targets:
        print(f"no seed files found at {args.path or seed_dir}")
        return 1

    client, total = Client(), 0
    for t in targets:
        n = seed_from_file(client, t)
        total += n
        print(f"  ✓ {n} record(s) from {Path(t).name}")
    print(f"✓ seeded {total} record(s) from {len(targets)} file(s)")
    if not interests:
        print("  Note: no interests declared, so any imported record can surface in any")
        print('  briefing here. `okl init --interests "<subjects>"` narrows that.')
    return 0


def cmd_scaffold(args: argparse.Namespace) -> int:
    """Stamp the portable method kit (canon, skills, agent, commands, gates, evals, hook) into a repo."""
    from .scaffold_cmd import scaffold
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


def cmd_serve(args: argparse.Namespace) -> int:
    """Run the shared HTTP service.

    The 0.0.0.0 default is so the service is reachable from outside its container,
    which is the only way a shared instance is useful. OKL_TOKEN gates every route
    except /health; see docs/DEPLOY.md before exposing it.
    """
    from .service import run
    run(host=args.host, port=args.port)
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    """Serve the MCP tool surface over stdio, for a coding agent to call.

    Same operations as the CLI through the same Client, so remote/local mode and the
    fail-closed behaviour are identical whichever surface the agent uses.
    """
    from .mcp_server import run_stdio
    run_stdio()
    return 0


def build_parser() -> argparse.ArgumentParser:  # noqa: PLR0915 - one declarative table, see below
    """Build the argparse tree for every subcommand.

    One long declarative function on purpose: the parser IS the CLI's contract, and a
    reader answering "what flags does verify take" should find the whole answer in one
    place rather than following a chain of registration helpers.
    """
    p = argparse.ArgumentParser(prog="okl", description="Observed Knowledge Ledger — lessons your coding agents can trust, proven by checks.")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="wire the current repo (config + hook + CI pointer)")
    pi.add_argument("--repo"); pi.add_argument("--service")
    pi.add_argument("--interests", help="comma-sep subject tags this repo cares about "
                    "(filters org-scope lessons in `check`; see store.KNOWN_TAGS)")
    pi.add_argument("--claude", action=argparse.BooleanOptionalAction, default=None,
                    help="--claude wires Claude Code (hooks, settings, MCP) even with no .claude/ "
                         "and no `claude` on PATH; --no-claude skips it. Default: wire when "
                         ".claude/ exists or `claude` is on PATH")
    pi.add_argument("--ci", action=argparse.BooleanOptionalAction, default=None,
                    help="--no-ci skips the GitHub Actions drift workflow (a private repo pays for its "
                         "minutes; another CI or a hook can run `okl drift --gate`) and records that in "
                         ".okl/config.json so later runs skip it too; --ci turns it back on")
    pi.add_argument("--no-seed", dest="no_seed", action="store_true",
                    help="leave the store empty (by default init imports the starter lessons and "
                         "the bundled packs that match this repo's stack)")
    pi.add_argument("--dry-run", dest="dry_run", action="store_true",
                    help="list every file init would write or modify, and write nothing")
    pi.add_argument("--force", action="store_true",
                    help="replace okl files you have edited with okl's version")
    pi.add_argument("--uninstall", action="store_true",
                    help="remove okl's hooks, registrations and CI workflow (never .okl/); "
                         "edited files are kept. Combine with --dry-run to preview")
    pi.set_defaults(func=cmd_init)

    pc = sub.add_parser("connect", help="point this repo at a shared OKL service URL")
    pc.add_argument("url"); pc.add_argument("--token")
    pc.set_defaults(func=cmd_connect)

    pk = sub.add_parser("check", help="pre-task read: relevant lessons for a task")
    pk.add_argument("--task", required=True); pk.add_argument("--repo")
    pk.add_argument("--format", choices=["agent", "actions", "json", "hook"], default="agent",
                    help="agent: the full briefing. actions: the routed action list only, "
                         "for callers on a small context budget. json: the raw result. hook: what a "
                         "Claude Code UserPromptSubmit hook prints (briefing + a line for the user).")
    pk.add_argument("--limit", type=int, default=None,
                    help="cap how many records the briefing draws on (and how many actions "
                         "'--format actions' prints). Use with subagents on a token budget.")
    pk.add_argument("--interests", default=None,
                    help="override this repo's configured subject tags for this call. Pass "
                         "an empty string to disable interest filtering entirely — the eval "
                         "harness does, because inheriting a host repo's interests made one "
                         "of its tasks measure the absence of the rule it tests.")
    pk.set_defaults(func=cmd_check)

    pr = sub.add_parser("record", help="record a node (defect/gate/claim/...)")
    pr.add_argument("--type", required=True); pr.add_argument("--title", required=True)
    pr.add_argument("--scope", required=True, help="'org' or 'repo:<name>' or 'repo'")
    pr.add_argument("--repo"); pr.add_argument("--body"); pr.add_argument("--status")
    pr.add_argument("--found-by", dest="found_by")
    pr.add_argument("--ttl-days", dest="ttl_days", type=int); pr.add_argument("--owner")
    pr.add_argument("--files", help="comma-sep path globs this node governs (enrolls it in drift detection)")
    pr.add_argument("--symptom", help="Symptom→Cause→Fix: the observable symptom (cause goes in --body)")
    pr.add_argument("--fix", help="Symptom→Cause→Fix: the fix to apply")
    pr.add_argument("--applies-to", dest="applies_to", default=None,
                    help="stacks this lesson is VALID for (comma-sep), or 'any'. Leave unset "
                         "for a portable lesson — that is the default and the common case. "
                         "Use it only when the lesson genuinely does not transfer, e.g. a "
                         "framework's middleware ordering. Distinct from --tags, which "
                         "records subject and where the lesson was found.")
    pr.add_argument("--tags", help="comma-sep subject tags from the controlled vocabulary "
                    "(store.KNOWN_TAGS), e.g. 'react,security'")
    pr.add_argument("--id", help="explicit stable id (makes the write idempotent — re-records replace)")
    pr.add_argument("--verified", action="store_true",
                    help="refused: verify with `okl verify <id> --run ... --expect ...` instead")
    pr.set_defaults(func=cmd_record)

    pl = sub.add_parser("link", help="add an edge between two nodes")
    pl.add_argument("src"); pl.add_argument("rel"); pl.add_argument("dst")
    pl.set_defaults(func=cmd_link)

    pvf = sub.add_parser("verify", help="run a check and stamp a node verified only on an observed pass")
    pvf.add_argument("node_id")
    pvf.add_argument("--run", help="the check command; exit 0 required to stamp. Without it, "
                     "okl verify shows the lesson and the tests that touch its files, and stamps nothing")
    pvf.add_argument("--expect", help="substring that must appear in the output — a positive success "
                     "signal, so exit 0 alone can't self-certify (the exit-0-zero-files lesson)")
    pvf.add_argument("--timeout", type=int, default=600, help="seconds before the check is killed (default 600)")
    pvf.set_defaults(func=cmd_verify)

    prv = sub.add_parser("reverify", help="re-run the stored check of every drifted lesson and re-stamp the passes")
    prv.add_argument("--yes", action="store_true",
                     help="run the listed stored commands without asking (they come from the store)")
    prv.add_argument("--dry-run", dest="dry_run", action="store_true",
                     help="list what would be re-run, run nothing")
    prv.add_argument("--timeout", type=int, default=600)
    prv.set_defaults(func=cmd_reverify)

    ps = sub.add_parser("search", help="full-text search over the encoded body")
    ps.add_argument("query")
    ps.add_argument("--scope", help="'org', 'repo:<name>', or 'repo' for this repo "
                                    "(anything else is refused, not silently empty)")
    ps.add_argument("--type", nargs="*"); ps.add_argument("--limit", type=int, default=25)
    ps.add_argument("--format", choices=["text", "json"], default="text")
    ps.set_defaults(func=cmd_search)

    pm = sub.add_parser("metric", help="recurrence-after-arming metric")
    pm.add_argument("--format", choices=["text", "json"], default="text")
    pm.set_defaults(func=cmd_metric)

    pdr = sub.add_parser("drift", help="source-vs-spec drift: rules whose governed code changed after verification")
    pdr.add_argument("--repo"); pdr.add_argument("--repo-dir", dest="repo_dir", default=".")
    pdr.add_argument("--gate", action="store_true", help="exit 1 if drift found (for CI)")
    pdr.add_argument("--format", choices=["text", "json"], default="text")
    pdr.add_argument("--snapshot", metavar="FILE",
                     help="read rules from a committed snapshot (okl export --drift) "
                          "instead of a store — for CI with no store")
    pdr.set_defaults(func=cmd_drift)

    pex = sub.add_parser("export", help="write the committed drift snapshot CI reads (okl-drift.json)")
    pex.add_argument("--drift", action="store_true", required=True,
                     help="the drift snapshot (the only export today; named so others can follow)")
    pex.add_argument("-o", "--output", help="path (default: okl-drift.json at the project root)")
    pex.set_defaults(func=cmd_export)

    pdoc = sub.add_parser("doctor", help="report other agent-memory tools installed beside okl, "
                                         "and how they collide (changes nothing)")
    pdoc.set_defaults(func=cmd_doctor)

    pdd = sub.add_parser("dedup", help="report near-duplicate records for review (never auto-merges)")
    pdd.add_argument("--threshold", type=float, default=core.DEDUP_THRESHOLD,
                     help=f"similarity 0-1 to report at (default {core.DEDUP_THRESHOLD}, "
                          "calibrated to over-report)")
    pdd.add_argument("--limit", type=int, default=20, help="pairs to print")
    pdd.set_defaults(func=cmd_dedup)
    pcv = sub.add_parser("coverage", help="knowledge-to-code ratio (health signal)")
    pcv.add_argument("--repo"); pcv.add_argument("--repo-dir", dest="repo_dir", default=".")
    pcv.add_argument("--format", choices=["text", "json"], default="text")
    pcv.set_defaults(func=cmd_coverage)

    pb = sub.add_parser("bootstrap", help="propose starter nodes from repo signals (git log, docs)")
    pb.add_argument("--repo"); pb.add_argument("--repo-dir", dest="repo_dir", default=".")
    pb.add_argument("--out", default="okl-bootstrap.json")
    pb.set_defaults(func=cmd_bootstrap)

    pd = sub.add_parser("seed", help="ingest seed file(s) as nodes (a *-defects.json, or a dir of them)")
    pd.add_argument("path", nargs="?", default=None,
                    help="a seed JSON file, or a directory of them. With no path, lists the "
                         "bundled packs and imports nothing.")
    pd.add_argument("--all", action="store_true",
                    help="import every bundled pack. Explicit on purpose: the packs carry "
                         "stack-specific rules, and importing all of them into an unrelated "
                         "project fills its briefings with noise.")
    pd.set_defaults(func=cmd_seed)

    psc = sub.add_parser("scaffold", help="stamp the portable method kit into a repo")
    psc.add_argument("target", nargs="?", default=".", help="target repo dir (default: cwd)")
    psc.add_argument("--repo", help="repo name (default: dir name)")
    psc.add_argument("--plugin", action="store_true", help="also write .claude-plugin/plugin.json (Claude Code plugin)")
    from .scaffold_cmd import list_profiles
    psc.add_argument("--profile", action="append", choices=list_profiles(), metavar="PROFILE",
                     help="drop a stack's verbatim canon into .claude/rules/; repeatable and composable, "
                          f"e.g. --profile dotnet --profile react (available: {', '.join(list_profiles())})")
    psc.add_argument("--force", action="store_true", help="overwrite existing files")
    psc.add_argument("--verbose", "-v", action="store_true")
    psc.set_defaults(func=cmd_scaffold)

    pv = sub.add_parser("serve", help="run the shared FastAPI service")
    pv.add_argument("--host", default="0.0.0.0"); pv.add_argument("--port", type=int, default=8080)
    pv.set_defaults(func=cmd_serve)

    pmcp = sub.add_parser("mcp", help="run the MCP server (stdio) for agent tools")
    pmcp.set_defaults(func=cmd_mcp)
    return p


def main(argv: list[str] | None = None) -> int:
    """Parse argv and dispatch, converting store errors into exit codes.

    The backstop matters more than it looks: this CLI runs inside other people's hooks
    and CI, where the exit code is the only thing read. No command may answer a
    rejected or unreachable store with a traceback and a zero exit.
    """
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (ValueError, OKLUnreachableError) as e:
        # The backstop, so no command can ever answer a rejected or unreachable service
        # with a Python traceback. Commands that can say something more specific catch
        # these themselves and never reach here; this exists so the ones that do not —
        # and the ones added later — still exit non-zero with a line a human can act on.
        print(f"OKL: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
