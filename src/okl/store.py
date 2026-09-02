"""Storage layer for the Org Knowledge Layer (OKL).

Swappable backend: SQLite by default (a file, or :memory:), Postgres when
``OKL_DATABASE_URL`` starts with ``postgres``.  Both speak the same node/edge
schema from the design doc (``the-sixth-surface.md`` Appendix A).

The store is the ONLY thing that touches the database.  The service and the
client reach it through this class, never through raw SQL of their own — so
promoting SQLite -> Postgres is a one-env-var change, no call-site edits.
"""
from __future__ import annotations

import contextlib
import os
import time
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from typing import Any, Protocol, runtime_checkable

# Node types and edge relations are closed vocabularies (design doc §3.2).
NODE_TYPES = {
    "Defect", "Gate", "Rule", "Claim", "Retraction", "Tombstone",
    "Decision", "PriorArt", "Vocabulary", "Entity",
}
EDGE_RELS = {
    "CATCHES", "ENCODES", "REFUTES", "RETRACTS", "SUPERSEDES",
    "VERIFIED_ON", "RECURS_IN", "CONTRADICTS", "DEFINED_IN",
}
VALID_STATUS = {
    None, "live", "narrowed", "retracted", "open", "resolved", "stale",
}
# Subject tags are a controlled vocabulary like NODE_TYPES: grow it by editing this
# set (a deliberate curation act), not ad hoc — freeform tags sprawl and stop filtering.
# Stacks mirror the scaffold profiles; the rest are cross-cutting subjects.
KNOWN_TAGS = {
    "dotnet", "react", "python-rag", "geospatial",            # stacks (= scaffold profiles)
    "eval-integrity", "agent-safety", "security",             # cross-cutting subjects
    "retrieval-design", "data-quality", "method",
    "messaging",   # added 2026-07-21 for the .NET platform canon import (broker/queue/event-driven design)
    "python",      # added 2026-09-02 for okl's own language canon. Distinct from
                   # `python-rag`, which is a STACK tag for one service's RAG pipeline:
                   # a review found this repo had 75 dotnet-tagged records governing a
                   # Python codebase and no tag under which to file its own conventions.
}


# The stack half of the vocabulary — "what technology is this about". Distinguished from
# subject tags because the two filter differently: a repo that does not do .NET wants no
# .NET records, however cross-cutting their subject. Kept beside KNOWN_TAGS so adding a
# stack cannot silently land in the wrong half.
STACK_TAGS = {"dotnet", "react", "python-rag", "geospatial", "python"}


def split_tags(tags: str | None) -> set[str]:
    """Normalize a comma-separated tag string to a set of lowercase labels."""
    return {t.strip().lower() for t in (tags or "").split(",") if t.strip()}


def _now_ms() -> int:
    """Epoch milliseconds. Milliseconds because git commit times are compared against
    verification stamps, and second resolution loses ordering within a busy minute."""
    return int(time.time() * 1000)


def new_id(prefix: str = "n") -> str:
    """A short prefixed id (n_ for nodes).

    Random rather than sequential: ids from different machines land in one shared
    store, so a counter would collide.
    """
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


@dataclass
class Node:
    type: str
    title: str
    scope: str = "repo:unknown"          # 'org' or 'repo:<name>'
    repo: str | None = None
    body: str | None = None
    status: str | None = None
    found_by: str | None = None
    verified_at: int | None = None       # epoch ms; None = never verified
    ttl_days: int | None = None
    owner: str | None = None
    files: str | None = None             # comma-sep path globs this node governs (drift detector)
    symptom: str | None = None           # Symptom→Cause→Fix schema (cause lives in body)
    fix: str | None = None
    tags: str | None = None              # comma-sep subject labels ("react,security"); orthogonal to scope
    verified_by: str | None = None       # evidence trail: the observed check that last stamped verified_at
    id: str = field(default_factory=lambda: new_id("n"))
    created_at: int = field(default_factory=_now_ms)

    def validate(self) -> None:
        if self.type not in NODE_TYPES:
            raise ValueError(f"unknown node type {self.type!r}; valid: {sorted(NODE_TYPES)}")
        if self.status not in VALID_STATUS:
            raise ValueError(f"unknown status {self.status!r}; valid: {sorted(s for s in VALID_STATUS if s)}")
        if not (self.scope == "org" or self.scope.startswith("repo:")):
            raise ValueError(f"scope must be 'org' or 'repo:<name>', got {self.scope!r}")
        unknown = split_tags(self.tags) - KNOWN_TAGS
        if unknown:
            raise ValueError(f"unknown tag(s) {sorted(unknown)}; the controlled vocabulary is "
                             f"{sorted(KNOWN_TAGS)} — extend KNOWN_TAGS deliberately to grow it")

    def is_stale(self, now_ms: int | None = None) -> bool:
        """A node past its TTL is stale (design doc §3.6 — demote, don't delete)."""
        if self.ttl_days is None:
            return False
        base = self.verified_at if self.verified_at is not None else self.created_at
        now_ms = now_ms if now_ms is not None else _now_ms()
        return now_ms - base > self.ttl_days * 86_400_000


@dataclass
class Edge:
    src: str
    rel: str
    dst: str
    created_at: int = field(default_factory=_now_ms)

    def validate(self) -> None:
        if self.rel not in EDGE_RELS:
            raise ValueError(f"unknown edge relation {self.rel!r}; valid: {sorted(EDGE_RELS)}")


# ---------------------------------------------------------------------------
# Backend selection
# ---------------------------------------------------------------------------
class Store:
    """Facade over whichever backend the environment selects."""

    def __init__(self, url: str | None = None):
        url = url or os.environ.get("OKL_DATABASE_URL") or "sqlite:///okl.db"
        self.url = url
        if url.startswith("postgres"):
            self._impl: _Backend = _PostgresBackend(url)
        elif url.startswith("sqlite"):
            path = url[len("sqlite:///"):] if url.startswith("sqlite:///") else ":memory:"
            self._impl = _SQLiteBackend(path)
        else:
            raise ValueError(f"unsupported OKL_DATABASE_URL scheme: {url!r}")
        self._impl.init_schema()

    # -- writes -------------------------------------------------------------
    def add_node(self, node: Node) -> str:
        node.validate()
        self._impl.upsert_node(node)
        return node.id

    def add_edge(self, edge: Edge) -> None:
        edge.validate()
        self._impl.upsert_edge(edge)

    # -- reads --------------------------------------------------------------
    def get_node(self, node_id: str) -> Node | None:
        return self._impl.get_node(node_id)

    def search(self, query: str, scope: str | None = None,
               node_types: Iterable[str] | None = None, limit: int = 25) -> list[Node]:
        return self._impl.search(query, scope, list(node_types) if node_types else None, limit)

    def neighbors(self, node_id: str, rels: Iterable[str] | None = None) -> list[tuple[Edge, Node]]:
        return self._impl.neighbors(node_id, list(rels) if rels else None)

    def recurrence_after_arming(self) -> list[dict[str, str]]:
        """The metric the method says it lacks (design doc §3.5 / Appendix A)."""
        return self._impl.recurrence_after_arming()

    def all_nodes(self) -> list[Node]:
        return self._impl.all_nodes()

    def close(self) -> None:
        self._impl.close()


@runtime_checkable
class _Backend(Protocol):
    """What a storage backend must provide.

    A Protocol rather than a base class: the backends are independent implementations
    over different drivers, not variations on shared behaviour, and there is nothing to
    inherit. `runtime_checkable` lets the conformance test assert a backend satisfies
    this without importing a driver it may not have.

    THE SIGNATURES ARE NOT THE CONTRACT. This interface was satisfied in full while the
    Postgres backend ran an unranked substring match against SQLite's BM25 — same method
    names, same types, silently worse retrieval for anyone who promoted their store
    (recorded as "a swappable backend must match on quality, not just interface"). The
    behavioural half of the contract is stated here and enforced by the parity tests:

      search(q, scope, node_types, limit)
        - RANKED, best first. Not insertion order, not arbitrary.
        - Matches title, body, symptom and fix — every field the design treats as
          matchable — with title weighted highest.
        - OR-permissive across terms: a two-term query returns records matching either.
          (Postgres's websearch_to_tsquery ANDs by default, which silently tightens
          recall relative to SQLite.)
        - `limit` caps the rows returned; `scope` and `node_types` filter exactly.

      upsert_node / upsert_edge
        - Idempotent on the primary key: writing the same id twice replaces, never
          duplicates, and leaves any derived index consistent with the row.
    """

    def init_schema(self) -> None: ...
    def upsert_node(self, node: Node) -> None: ...
    def upsert_edge(self, edge: Edge) -> None: ...
    def get_node(self, node_id: str) -> Node | None: ...
    def search(self, q: str, scope: str | None, node_types: list[str] | None,
               limit: int) -> list[Node]: ...
    def neighbors(self, node_id: str, rels: list[str] | None) -> list[tuple[Edge, Node]]: ...
    def recurrence_after_arming(self) -> list[dict[str, str]]: ...
    def all_nodes(self) -> list[Node]: ...
    def close(self) -> None: ...


_NODE_COLS = ["id", "type", "scope", "repo", "title", "body", "status",
              "found_by", "verified_at", "ttl_days", "owner", "files",
              "symptom", "fix", "tags", "verified_by", "created_at"]


def _row_to_node(row: dict[str, Any]) -> Node:
    """Build a Node from a database row, ignoring columns it does not declare.

    Tolerating extra columns is what lets an older client read a database written by
    a newer one instead of crashing on an unknown field.
    """
    return Node(**{k: row[k] for k in _NODE_COLS if k in row})


# ---------------------------------------------------------------------------
# SQLite backend (default) — FTS5 full-text search
# ---------------------------------------------------------------------------
class _SQLiteBackend(_Backend):
    def __init__(self, path: str):
        import sqlite3
        import threading
        self._sqlite3 = sqlite3
        # check_same_thread=False so the FastAPI threadpool can share the conn;
        # a lock serializes access since sqlite3 connections aren't thread-safe.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()  # reentrant: neighbors() calls get_node()
        # :memory: and some filesystems do not support WAL; the store works without it.
        with contextlib.suppress(sqlite3.OperationalError):
            self.conn.execute("PRAGMA journal_mode=WAL")
        self._has_fts = True

    def init_schema(self) -> None:
        c = self.conn
        c.execute("""CREATE TABLE IF NOT EXISTS node(
            id TEXT PRIMARY KEY, type TEXT NOT NULL, scope TEXT NOT NULL, repo TEXT,
            title TEXT NOT NULL, body TEXT, status TEXT, found_by TEXT,
            verified_at INTEGER, ttl_days INTEGER, owner TEXT,
            files TEXT, symptom TEXT, fix TEXT, tags TEXT, verified_by TEXT, created_at INTEGER NOT NULL)""")
        # Idempotent migration: add columns introduced after v0.1 to pre-existing DBs.
        existing = {r[1] for r in c.execute("PRAGMA table_info(node)").fetchall()}
        for col in ("files", "symptom", "fix", "tags", "verified_by"):
            if col not in existing:
                c.execute(f"ALTER TABLE node ADD COLUMN {col} TEXT")
        c.execute("""CREATE TABLE IF NOT EXISTS edge(
            src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, created_at INTEGER NOT NULL,
            PRIMARY KEY (src, rel, dst))""")
        try:
            # symptom and fix are indexed, not just title and body. `symptom` is the
            # field every command and doc calls "what a reader matches against" — the
            # observable that tells you the record applies — and it was the one field
            # search could not see. A record following the guidance (short title, the
            # distinguishing words in symptom/fix) was unretrievable unless those words
            # happened to repeat in the title. Found by seeding a record from a spec and
            # watching `check` return nothing for a task quoting its symptom verbatim.
            c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS node_fts
                         USING fts5(id UNINDEXED, title, body, symptom, fix)""")
            # FTS5 cannot ALTER in new columns, so a store built before this rebuilds its
            # index once. The node table is the source of truth; the index is derived.
            fts_cols = {r[1] for r in c.execute("PRAGMA table_info(node_fts)").fetchall()}
            if "symptom" not in fts_cols:
                c.execute("DROP TABLE node_fts")
                c.execute("""CREATE VIRTUAL TABLE node_fts
                             USING fts5(id UNINDEXED, title, body, symptom, fix)""")
                c.execute("""INSERT INTO node_fts(id, title, body, symptom, fix)
                             SELECT id, coalesce(title,''), coalesce(body,''),
                                    coalesce(symptom,''), coalesce(fix,'') FROM node""")
        except self._sqlite3.OperationalError:
            self._has_fts = False   # FTS5 not compiled in — fall back to LIKE
        c.commit()

    def upsert_node(self, node: Node) -> None:
        with self._lock:
            vals = asdict(node)
            cols = ",".join(_NODE_COLS)
            ph = ",".join("?" for _ in _NODE_COLS)
            self.conn.execute(
                f"INSERT OR REPLACE INTO node({cols}) VALUES({ph})",
                [vals[k] for k in _NODE_COLS],
            )
            if self._has_fts:
                self.conn.execute("DELETE FROM node_fts WHERE id=?", (node.id,))
                self.conn.execute(
                    "INSERT INTO node_fts(id,title,body,symptom,fix) VALUES(?,?,?,?,?)",
                    (node.id, node.title or "", node.body or "",
                     node.symptom or "", node.fix or ""))
            self.conn.commit()

    def upsert_edge(self, edge: Edge) -> None:
        with self._lock:
            self.conn.execute("INSERT OR REPLACE INTO edge(src,rel,dst,created_at) VALUES(?,?,?,?)",
                              (edge.src, edge.rel, edge.dst, edge.created_at))
            self.conn.commit()

    def get_node(self, node_id: str) -> Node | None:
        with self._lock:
            r = self.conn.execute("SELECT * FROM node WHERE id=?", (node_id,)).fetchone()
            return _row_to_node(dict(r)) if r else None

    def search(self, q, scope, node_types, limit):
        with self._lock:
            params: list[Any] = []
            if self._has_fts and q.strip():
                sql = ("SELECT n.* FROM node_fts f JOIN node n ON n.id=f.id "
                       "WHERE node_fts MATCH ?")
                params.append(_fts_query(q))
            else:
                sql = ("SELECT * FROM node n WHERE (title LIKE ? OR body LIKE ? "
                       "OR symptom LIKE ? OR fix LIKE ?)")
                params += [f"%{q}%"] * 4
            if scope:
                sql += " AND n.scope=?" if "node_fts" in sql else " AND scope=?"
                params.append(scope)
            if node_types:
                marks = ",".join("?" for _ in node_types)
                sql += f" AND {'n.' if 'node_fts' in sql else ''}type IN ({marks})"
                params += list(node_types)
            # FTS path: order by FTS5 relevance (rank) so the most task-relevant nodes come first,
            # not insertion order. LIKE fallback has no relevance signal — leave unordered.
            if "node_fts" in sql:
                # Explicit column weights rather than bare `rank`, which weights every
                # column equally: a term in the title should still beat the same term
                # buried in a fix. One weight per FTS column, id first. The ratios track
                # the Postgres tsvector weights so the two backends rank alike.
                sql += " ORDER BY bm25(node_fts, 0.0, 8.0, 4.0, 4.0, 2.0)"
            sql += " LIMIT ?"
            params.append(limit)
            rows = self.conn.execute(sql, params).fetchall()
            return [_row_to_node(dict(r)) for r in rows]

    def neighbors(self, node_id, rels):
        with self._lock:
            sql = ("SELECT e.src,e.rel,e.dst,e.created_at FROM edge e "
                   "WHERE e.src=? OR e.dst=?")
            params: list[Any] = [node_id, node_id]
            if rels:
                marks = ",".join("?" for _ in rels)
                sql += f" AND e.rel IN ({marks})"
                params += list(rels)
            out = []
            for r in self.conn.execute(sql, params).fetchall():
                e = Edge(src=r["src"], rel=r["rel"], dst=r["dst"], created_at=r["created_at"])
                other = e.dst if e.src == node_id else e.src
                n = self.get_node(other)
                if n:
                    out.append((e, n))
            return out

    def recurrence_after_arming(self):
        with self._lock:
            sql = """
            SELECT d2.repo AS recurred_in, d1.title AS defect_class, g.title AS gate
            FROM edge rec JOIN node d2 ON rec.src=d2.id AND rec.rel='RECURS_IN'
            JOIN node d1 ON rec.dst=d1.id
            JOIN edge c ON c.rel='CATCHES' AND c.dst=d1.id
            JOIN node g ON c.src=g.id"""
            return [dict(r) for r in self.conn.execute(sql).fetchall()]

    def all_nodes(self):
        with self._lock:
            return [_row_to_node(dict(r)) for r in self.conn.execute("SELECT * FROM node").fetchall()]

    def close(self):
        self.conn.close()


def _fts_query(q: str) -> str:
    """Turn free text into a safe FTS5 OR-query of quoted terms."""
    terms = [t for t in "".join(ch if ch.isalnum() else " " for ch in q).split() if t]
    return " OR ".join(f'"{t}"' for t in terms) or '""'


# ---------------------------------------------------------------------------
# Postgres backend — same schema; ranked full-text search mirroring the FTS5 path
# ---------------------------------------------------------------------------

# Weighted tsvector: title (A) outranks body and symptom (B), which outrank fix (C).
# symptom is indexed because it is the field the whole design calls "what a reader matches
# against"; leaving it out made a record whose distinguishing words lived there
# unretrievable. The GIN index in init_schema uses the EXACT same expression — Postgres
# only uses an expression index when the query matches it character for character.
_PG_TSV = ("setweight(to_tsvector('english', coalesce(title,'')), 'A') || "
           "setweight(to_tsvector('english', coalesce(body,'')), 'B') || "
           "setweight(to_tsvector('english', coalesce(symptom,'')), 'B') || "
           "setweight(to_tsvector('english', coalesce(fix,'')), 'C')")


def _pg_ts_query(q: str) -> str:
    """Free text -> an OR websearch query, mirroring _fts_query's permissive-OR semantics
    (websearch_to_tsquery ANDs terms by default, which would silently tighten recall vs
    the SQLite backend)."""
    terms = [t for t in "".join(ch if ch.isalnum() else " " for ch in q).split() if t]
    return " OR ".join(terms)


class _PostgresBackend(_Backend):
    def __init__(self, url: str):
        try:
            import psycopg
        except ImportError as e:  # pragma: no cover - only when pg selected
            raise RuntimeError(
                "Postgres backend needs 'psycopg' — install okl[postgres]"
            ) from e
        self.psycopg = psycopg
        self.conn = psycopg.connect(url, autocommit=True)

    def init_schema(self):
        with self.conn.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS node(
                id TEXT PRIMARY KEY, type TEXT NOT NULL, scope TEXT NOT NULL, repo TEXT,
                title TEXT NOT NULL, body TEXT, status TEXT, found_by TEXT,
                verified_at BIGINT, ttl_days INTEGER, owner TEXT,
                files TEXT, symptom TEXT, fix TEXT, tags TEXT, verified_by TEXT, created_at BIGINT NOT NULL)""")
            # Idempotent migration for pre-existing tables.
            for col in ("files", "symptom", "fix", "tags", "verified_by"):
                cur.execute(f"ALTER TABLE node ADD COLUMN IF NOT EXISTS {col} TEXT")
            cur.execute("""CREATE TABLE IF NOT EXISTS edge(
                src TEXT NOT NULL, rel TEXT NOT NULL, dst TEXT NOT NULL, created_at BIGINT NOT NULL,
                PRIMARY KEY (src, rel, dst))""")
            # IF NOT EXISTS is keyed on the NAME, not the expression, so a store created
            # before symptom/fix joined the tsvector would keep an index Postgres can no
            # longer use for the new query — silently degrading every search to a
            # sequential scan. Drop it when its definition no longer matches.
            cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname='node_tsv_idx'")
            row = cur.fetchone()
            if row and "symptom" not in row[0]:
                cur.execute("DROP INDEX node_tsv_idx")
            cur.execute(f"CREATE INDEX IF NOT EXISTS node_tsv_idx ON node USING GIN (({_PG_TSV}))")

    def upsert_node(self, node: Node):
        vals = asdict(node)
        cols = ",".join(_NODE_COLS)
        ph = ",".join(f"%({k})s" for k in _NODE_COLS)
        upd = ",".join(f"{k}=EXCLUDED.{k}" for k in _NODE_COLS if k != "id")
        with self.conn.cursor() as cur:
            cur.execute(f"INSERT INTO node({cols}) VALUES({ph}) "
                        f"ON CONFLICT(id) DO UPDATE SET {upd}", vals)

    def upsert_edge(self, edge: Edge):
        with self.conn.cursor() as cur:
            cur.execute("INSERT INTO edge(src,rel,dst,created_at) VALUES(%s,%s,%s,%s) "
                        "ON CONFLICT(src,rel,dst) DO NOTHING",
                        (edge.src, edge.rel, edge.dst, edge.created_at))

    def _fetch(self, sql, params):
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]

    def get_node(self, node_id):
        rows = self._fetch("SELECT * FROM node WHERE id=%s", (node_id,))
        return _row_to_node(rows[0]) if rows else None

    def search(self, q, scope, node_types, limit):
        # Ranked full-text when there's a query (parity with the SQLite FTS5/BM25 path);
        # plain ILIKE only as the blank-query fallback. Without ranking, the shared
        # service would silently degrade retrieval below the local-file baseline.
        tsq = _pg_ts_query(q)
        params: list[Any] = []
        if tsq:
            # _PG_TSV is a module constant, not input; every caller-supplied value in
            # this query is bound as a %s parameter below.
            sql = (f"SELECT * FROM node WHERE ({_PG_TSV}) "  # noqa: S608
                   "@@ websearch_to_tsquery('english', %s)")
            params.append(tsq)
        else:
            sql = "SELECT * FROM node WHERE (title ILIKE %s OR body ILIKE %s)"
            params += [f"%{q}%", f"%{q}%"]
        if scope:
            sql += " AND scope=%s"; params.append(scope)
        if node_types:
            sql += " AND type = ANY(%s)"; params.append(list(node_types))
        if tsq:
            sql += f" ORDER BY ts_rank(({_PG_TSV}), websearch_to_tsquery('english', %s)) DESC"
            params.append(tsq)
        sql += " LIMIT %s"; params.append(limit)
        return [_row_to_node(r) for r in self._fetch(sql, params)]

    def neighbors(self, node_id, rels):
        sql = "SELECT src,rel,dst,created_at FROM edge WHERE (src=%s OR dst=%s)"
        params: list[Any] = [node_id, node_id]
        if rels:
            sql += " AND rel = ANY(%s)"; params.append(list(rels))
        out = []
        for r in self._fetch(sql, params):
            e = Edge(**r)
            other = e.dst if e.src == node_id else e.src
            n = self.get_node(other)
            if n:
                out.append((e, n))
        return out

    def recurrence_after_arming(self):
        return self._fetch("""
            SELECT d2.repo AS recurred_in, d1.title AS defect_class, g.title AS gate
            FROM edge rec JOIN node d2 ON rec.src=d2.id AND rec.rel='RECURS_IN'
            JOIN node d1 ON rec.dst=d1.id
            JOIN edge c ON c.rel='CATCHES' AND c.dst=d1.id
            JOIN node g ON c.src=g.id""", ())

    def all_nodes(self):
        return [_row_to_node(r) for r in self._fetch("SELECT * FROM node", ())]

    def close(self):
        self.conn.close()
