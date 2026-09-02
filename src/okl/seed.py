"""Seed the layer from a JSON file of nodes and edges.

The canonical first seed is the geospatial pipeline's defect table + the gates
that catch each defect — so a brand-new repo's very first `okl check` can return
a real, earned lesson (e.g. error #14's class-path gate) rather than an empty set.

File format:
{
  "nodes": [ {"key": "d14", "type": "Defect", "title": "...", "scope": "org", ...}, ... ],
  "edges": [ {"src": "g_classpath", "rel": "CATCHES", "dst": "d14"}, ... ]
}
`key` is a local alias used only to wire edges within the file; the store
assigns the real id. Edges reference keys, which are resolved to ids on load.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from . import core
from .client import Client


def seed_from_file(client: Client, path: str) -> int:
    """Ingest a *-defects.json file. Idempotent: re-seeding the same file REPLACES
    its own nodes instead of duplicating them.

    Each node's stable id is derived from the seed file's stem + the node's local
    `key` (e.g. `seed:geospatial-defects:d14`). `key` remains the in-file alias used
    to wire edges; here it does double duty as the persistent identity so a second
    `okl seed` run upserts the same rows. A node without a `key` falls back to a
    fresh random id (non-idempotent) — every bundled seed node has a key.
    """
    p = Path(path)
    data = json.loads(p.read_text())

    # A pack that declares itself agent-proposed is held to its citation rule here, not
    # by the reviewer remembering to check. The commands that write these files tell the
    # agent "no citation, no record" — but an instruction with no mechanical trigger is
    # the surface nobody runs, and an uncited record is the worst thing this store can
    # hold: a plausible sentence nobody can trace, injected into every future task and
    # believed. Curated packs carry provenance in other ways and are not affected.
    if data.get("_proposed_by"):
        uncited = [n.get("key") or n.get("title", "?")
                   for n in data.get("nodes", []) if not (n.get("found_by") or "").strip()]
        if uncited:
            raise ValueError(
                f"{p.name} declares _proposed_by={data['_proposed_by']!r}, so every node "
                f"must carry a found_by citation. {len(uncited)} do not:\n  - "
                + "\n  - ".join(uncited[:10])
                + ("\n  ..." if len(uncited) > 10 else "")
                + "\nAdd the path:line each came from, or delete the record.")

    # Near-duplicate advisory for proposal packs. Unlike the citation rule above this
    # only reports: the similarity score cannot separate a paraphrase from a
    # genuinely-distinct record that shares a subject (see core.DEDUP_THRESHOLD), and a
    # blocking check on a signal that noisy would refuse good imports. An uncited record
    # is unambiguously wrong; a similar one is a question for a person.
    if data.get("_proposed_by") and getattr(client, "mode", "local") == "local":
        store = client._local_store()
        if store.all_nodes():
            idf = core._idf(store)
            flagged = []
            for node in data.get("nodes", []):
                for score, existing in core.find_duplicates(store, node, idf=idf, limit=1):
                    flagged.append((score, node.get("title", "?"), existing))
            if flagged:
                print(f"  ? {len(flagged)} incoming record(s) resemble records already in "
                      "the store. Importing anyway — review these:", file=sys.stderr)
                for score, title, existing in sorted(flagged, key=lambda f: -f[0])[:10]:
                    print(f"      {score:.2f}  incoming: {title[:64]}", file=sys.stderr)
                    print(f"            existing: [{existing.id}] {existing.title[:56]}",
                          file=sys.stderr)

    ns = f"seed:{p.stem}"
    keymap: dict[str, str] = {}
    for node in data.get("nodes", []):
        key = node.pop("key", None)
        # Seed nodes carry provenance from ANOTHER repo. Client.record defaults a
        # missing `repo` to the CURRENT repo, which would mislabel it — pass None
        # explicitly ("unknown") and warn, rather than inherit that default.
        if "repo" not in node:
            node["repo"] = None
            print(f"  ! {key or node.get('title', '?')}: seed node has no 'repo' — "
                  "recording provenance as unknown, not this repo", file=sys.stderr)
        stable_id = f"{ns}:{key}" if key else None
        node_id = client.record(id=stable_id, **node) if stable_id else client.record(**node)
        if key:
            keymap[key] = node_id
    for edge in data.get("edges", []):
        src = keymap.get(edge["src"], edge["src"])
        dst = keymap.get(edge["dst"], edge["dst"])
        client.link(src, edge["rel"], dst)
    return len(data.get("nodes", []))
