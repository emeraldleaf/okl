"""`okl seed` and the bundled seed packs: listing them, judging which fit a repo, and the
starter lessons `okl init` imports into an empty store."""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from pathlib import Path

from .. import core
from ..client import Client, OKLUnreachableError, _find_config


def _bundled_seed_dir() -> Path:
    """Where the shipped seed packs live (core.bundled_seed_dir, which core needs too)."""
    return core.bundled_seed_dir()


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
    from ..seed import seed_from_file, seed_starter
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

    Exits 2 when there are no packs to list: a broken install, so it could not run.
    """
    packs = sorted(str(f) for f in seed_dir.glob("*.json"))
    if not packs:
        print(f"no seed packs found under {seed_dir}", file=sys.stderr)
        return 2
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
    opt-in. `--refresh` re-imports only the records this store already holds, from the
    packs they came from, so a store that took a starter subset picks up a pack's newer
    symptoms and aliases without taking the rest of the pack.
    """
    from ..seed import pack_node_count, seed_from_file
    seed_dir = _bundled_seed_dir()
    client = Client()
    interests = {t.lower() for t in (client.interests or [])}
    refresh = bool(getattr(args, "refresh", False))
    present: set[str] = set()
    if refresh:
        present = {n.id for n in client.all_nodes()}
        if not present:
            print("okl seed --refresh: this store holds no records to refresh.", file=sys.stderr)
            return 2
    if not args.path and not args.all and not refresh:
        return _list_seed_packs(seed_dir, interests)
    targets = _seed_targets(args, seed_dir, present)
    if targets is None:
        return 2
    if _hygiene_refuses(client, targets, args):
        return 2
    total = 0
    for t in targets:
        if refresh:
            n = seed_from_file(client, t, only=present)
            print(f"  ✓ refreshed {n} of {pack_node_count(t)} record(s) from {Path(t).name}"
                  + ("" if n else " (none of its records are held here)"))
        else:
            n = seed_from_file(client, t)
            print(f"  ✓ {n} record(s) from {Path(t).name}")
        total += n
    print(f"✓ {'refreshed' if refresh else 'seeded'} {total} record(s) from {len(targets)} file(s)")
    if not interests and not refresh:
        print("  Note: no interests declared, so any imported record can surface in any")
        print('  briefing here. `okl init --interests "<subjects>"` narrows that.')
    return 0


def _seed_targets(args: argparse.Namespace, seed_dir: Path, present: set[str]) -> list[str] | None:
    """The pack files a seed run reads, or None after printing why there are none.

    `--all` is every bundled pack; a path is a file, a directory of files, or a bundled
    pack's name; `--refresh` with no path finds the bundled packs from the store's own
    `seed:<pack>:<key>` ids and names the packs it was seeded from that are not bundled
    (a repo's own file), which the caller has to pass by path.
    """
    if args.all:
        targets = sorted(str(f) for f in seed_dir.glob("*.json"))
    elif args.path:
        path = Path(args.path)
        # A bundled pack by name -- `okl seed dotnet-defects` -- when no such path exists.
        # `init` used to print the pack's absolute path inside site-packages for the user
        # to paste; a name is what the listing shows and what a README can say.
        if not path.exists():
            bundled = seed_dir / (args.path if args.path.endswith(".json") else f"{args.path}.json")
            if not bundled.is_file():
                names = ", ".join(sorted(f.stem for f in seed_dir.glob("*.json")))
                print(f"no seed file at {args.path!r}, and no bundled pack of that name. "
                      f"Bundled packs: {names}", file=sys.stderr)
                return None
            path = bundled
        targets = sorted(str(f) for f in path.glob("*.json")) if path.is_dir() else [str(path)]
    else:
        # A seed id names its pack by file stem, not by path, so a repo's own file that
        # shares a bundled pack's name would be indistinguishable here and the bundled text
        # would overwrite the repo's (review on #276). A same-named file in the repo's
        # conventional places wins by being skipped: the user names the source they mean.
        stems = {i.split(":")[1] for i in present if i.startswith("seed:") and i.count(":") >= 2}
        # In okl's own checkout the bundled dir IS ./seed, which is no collision (review on #276).
        local = {s: p for s in stems for p in (Path("seed") / f"{s}.json", Path(f"{s}.json"))
                 if p.is_file() and p.resolve() != (seed_dir / f"{s}.json").resolve()}
        bundled_stems = {s for s in stems if (seed_dir / f"{s}.json").is_file()}
        targets = sorted(str(seed_dir / f"{s}.json") for s in bundled_stems - set(local))
        for _s, p in sorted(local.items()):
            print(f"  note: {p} shares the bundled pack's name; refresh from it by path "
                  f"(okl seed --refresh {p}), or from the bundled pack by name.", file=sys.stderr)
        foreign = sorted(s for s in stems - bundled_stems - set(local))
        if foreign:
            print(f"  note: {len(foreign)} pack(s) this store was seeded from are not bundled "
                  f"({', '.join(foreign)}); pass each one's file to refresh its records.", file=sys.stderr)
        if not targets:
            print("okl seed --refresh: nothing to refresh from the bundled packs here.", file=sys.stderr)
            return None
    if not targets:
        print(f"no seed files found at {args.path or seed_dir}", file=sys.stderr)
        return None
    return targets


def _hygiene_refuses(client: Client, targets: list[str], args: argparse.Namespace) -> bool:
    """Print every file's hygiene warnings before any import (#255): a trace-shaped or
    over-scoped org record is warned about, never refused, unless --strict asks CI on a
    ledger repo to fail the pull request that adds one. True when --strict refuses."""
    from ..seed import hygiene_findings_for_file
    known = sorted({n.scope[len("repo:"):] for n in client.all_nodes() if n.scope.startswith("repo:")}
                   | {n.repo for n in client.all_nodes() if n.repo})
    flagged = 0
    for t in targets:
        lines, count = hygiene_findings_for_file(t, known)
        for line in lines:
            print(f"  ! {Path(t).name}: {line}", file=sys.stderr)
        flagged += count
    if flagged and getattr(args, "strict", False):
        print(f"okl seed --strict: {flagged} record(s) flagged above; nothing imported.", file=sys.stderr)
        return True
    return False
