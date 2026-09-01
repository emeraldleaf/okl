"""Client resolution: talk to a REMOTE service if configured, else a LOCAL store.

`okl connect <url>` writes the service URL into .okl/config.json. When a remote
is configured every operation is an HTTP call; otherwise it falls back to a
local store file (single-machine mode). This is what lets the same CLI work
before you've deployed the shared service and after.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any
from urllib import request as _req
from urllib.error import HTTPError, URLError

from . import core
from .store import Store

CONFIG_DIR = ".okl"
CONFIG_FILE = "config.json"


def _find_config(start: Path | None = None) -> Path | None:
    p = (start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        cfg = d / CONFIG_DIR / CONFIG_FILE
        if cfg.exists():
            return cfg
    return None


def load_config() -> dict[str, Any]:
    cfg = _find_config()
    if cfg:
        return json.loads(cfg.read_text())
    return {}


def save_config(data: dict[str, Any], root: Path | None = None) -> Path:
    d = (root or Path.cwd()) / CONFIG_DIR
    d.mkdir(parents=True, exist_ok=True)
    # Ignore the whole directory, from inside it. Everything okl writes here is either
    # machine-local (`okl_bin`, an absolute interpreter path) or secret (`token`, the
    # service bearer credential that `okl connect --token` stores in cleartext), and the
    # local store lands here too. The code claimed ".okl/ is gitignored" while writing
    # nothing to make that true, so a `git add .` after `okl connect --token` committed
    # a shared secret. A .gitignore inside .okl/ needs no edit to the repo's own.
    gitignore = d / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("# okl: machine-local config, credentials and local store\n*\n")
    path = d / CONFIG_FILE
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


class Client:
    """Uniform surface over local-store and remote-service modes."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config if config is not None else load_config()
        self.service_url = os.environ.get("OKL_SERVICE_URL") or self.config.get("service_url")
        self.repo = self.config.get("repo") or Path.cwd().name
        self.interests = self.config.get("interests") or []
        self._store: Store | None = None

    @property
    def mode(self) -> str:
        return "remote" if self.service_url else "local"

    @property
    def configured(self) -> bool:
        """True when this directory (or an ancestor) has been `okl init`-ed, or a
        service URL is set. Reading from an unconfigured directory would silently
        create an empty database and then report a clean check against it."""
        return bool(self.service_url) or _find_config() is not None

    def _local_store(self) -> Store:
        if self._store is None:
            # local store lives next to the config, or ./okl.db
            cfg = _find_config()
            db = (cfg.parent / "okl.db") if cfg else Path("okl.db")
            self._store = Store(f"sqlite:///{db}")
        return self._store

    # -- HTTP helper (stdlib only; fails CLOSED — raises, never returns empty) --
    def _post(self, path: str, payload: dict) -> dict:
        url = self.service_url.rstrip("/") + path
        data = json.dumps(payload).encode()
        req = _req.Request(url, data=data, headers={"Content-Type": "application/json"})
        token = os.environ.get("OKL_TOKEN") or self.config.get("token")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with _req.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            # The service answered — so this is NOT "unreachable". A 4xx is the caller's
            # error and must surface its detail (found by E2E: an unknown-tag 400 was
            # reported to the agent as an outage).
            try:
                detail = json.loads(e.read()).get("detail", "")
            except Exception:  # noqa: BLE001
                detail = ""
            if 400 <= e.code < 500:
                raise ValueError(f"OKL service rejected the request ({e.code}): {detail or e.reason}") from e
            raise OKLUnreachable(f"OKL service error at {url}: {e.code} {detail or e.reason}") from e
        except URLError as e:
            raise OKLUnreachable(f"OKL service unreachable at {url}: {e}") from e

    # -- operations ---------------------------------------------------------
    def check(self, task: str, repo: str | None = None, limit: int | None = None) -> dict:
        repo = repo or self.repo
        payload = {"repo": repo, "task": task, "interests": self.interests or None}
        if limit is not None:
            payload["limit"] = limit
        if self.mode == "remote":
            return self._post("/check", payload)
        kw = {"interests": self.interests}
        if limit is not None:
            kw["limit"] = limit
        return core.check(self._local_store(), repo, task, **kw)

    def record(self, **kwargs) -> str:
        # Default the repo in BOTH modes: `--scope repo` needs it to become repo:<name>,
        # and the remote path used to skip this (found by E2E: 400 on every repo-scoped record).
        # `setdefault` is not enough: callers that pass every field explicitly (the MCP
        # tools do) send repo=None, so the key EXISTS and setdefault leaves the None in
        # place. Found by live-testing the MCP server: every scope="repo" record failed.
        if kwargs.get("repo") is None:
            kwargs["repo"] = self.repo
        if self.mode == "remote":
            return self._post("/record", kwargs)["id"]
        return core.record(self._local_store(), **kwargs)

    def search(self, query: str, scope: str | None = None,
               node_types: list[str] | None = None, limit: int = 25) -> list[dict]:
        if self.mode == "remote":
            return self._post("/search", {"query": query, "scope": scope,
                                          "node_types": node_types, "limit": limit})["results"]
        return core.search(self._local_store(), query, scope, node_types, limit)

    def link(self, src: str, rel: str, dst: str) -> None:
        if self.mode == "remote":
            self._post("/link", {"src": src, "rel": rel, "dst": dst})
            return
        core.link(self._local_store(), src, rel, dst)

    def verify(self, node_id: str, evidence: str) -> dict:
        if self.mode == "remote":
            return self._post("/verify", {"id": node_id, "evidence": evidence})
        return core.verify(self._local_store(), node_id, evidence)

    def recurrence(self) -> list[dict]:
        if self.mode == "remote":
            return self._get("/metric/recurrence")["recurrence_after_arming"]
        return self._local_store().recurrence_after_arming()

    def all_nodes(self):
        """Return all in-scope Node objects (local store, or /nodes on a remote service).

        Used by the drift detector, which needs the node set locally but runs its
        git lookups against the working tree.
        """
        from .store import Node
        if self.mode == "remote":
            rows = self._get("/nodes")["nodes"]
            return [Node(**{k: v for k, v in r.items()
                            if k in Node.__dataclass_fields__}) for r in rows]
        return self._local_store().all_nodes()

    def _get(self, path: str) -> dict:
        # The token goes on GETs too. It used to go only on POSTs, which was survivable
        # only because the service left reads open; once reads are gated, an unauthenticated
        # GET makes drift detection (/nodes) and the recurrence metric fail against every
        # private deployment — and a 401 here surfaces as "unreachable", i.e. as an outage.
        url = self.service_url.rstrip("/") + path
        req = _req.Request(url)
        token = os.environ.get("OKL_TOKEN") or self.config.get("token")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with _req.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except HTTPError as e:
            if 400 <= e.code < 500:
                raise ValueError(
                    f"OKL service rejected the request ({e.code} {e.reason}). "
                    "If this is 401, set OKL_TOKEN or add \"token\" to .okl/config.json.") from e
            raise OKLUnreachable(f"OKL service error at {url}: {e.code} {e.reason}") from e
        except URLError as e:
            raise OKLUnreachable(f"OKL service unreachable at {url}: {e}") from e


class OKLUnreachable(RuntimeError):
    """Raised when a configured remote service can't be reached. Callers that
    gate work on OKL (the pre-task hook) must FAIL CLOSED on this — the
    merge-gate lesson: a check that silently returns 'nothing' is worse than
    no check."""
