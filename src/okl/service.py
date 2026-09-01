"""The shared OKL service — a small FastAPI app exposing check/record/search/link.

This is the "option 3" piece: one always-on service that owns the database, so
any repo on any machine reaches the SAME curated knowledge via a URL. Storage is
selected by OKL_DATABASE_URL (sqlite:///okl.db default, or postgres://... when
you deploy) — the code here never changes when you promote the backend.

Run: `okl serve` (or `uvicorn okl.service:app`).
"""
from __future__ import annotations

import os
from typing import Any

from . import core
from .store import Store

try:
    from fastapi import FastAPI, Header, HTTPException
    from pydantic import BaseModel
except ImportError as e:  # pragma: no cover
    raise RuntimeError("The service needs FastAPI — install okl[service]") from e


class CheckReq(BaseModel):
    repo: str
    task: str
    limit: int = 12
    interests: list[str] | None = None   # the calling repo's declared subject tags


class RecordReq(BaseModel):
    type: str
    title: str
    scope: str
    repo: str | None = None
    body: str | None = None
    status: str | None = None
    found_by: str | None = None
    ttl_days: int | None = None
    owner: str | None = None
    files: str | None = None
    symptom: str | None = None
    fix: str | None = None
    tags: str | None = None
    id: str | None = None
    verified: bool = False


class SearchReq(BaseModel):
    query: str
    scope: str | None = None
    node_types: list[str] | None = None
    limit: int = 25


class LinkReq(BaseModel):
    src: str
    rel: str
    dst: str


class VerifyReq(BaseModel):
    id: str
    evidence: str   # the observed check that passed (command + timestamp)


def create_app(store: Store | None = None) -> FastAPI:
    # Optional shared-secret gate. If OKL_TOKEN is set it covers READS as well as
    # writes. Reads used to be open while writes were gated, which meant a deployed
    # service handed anyone who found the URL a `GET /nodes` dump of the org's entire
    # encoded body — its known defects, its retired identifiers, its architecture
    # decisions. That is a catalogue of where the org is weak, and it is exactly the
    # material the layer exists to collect. If you set a token, you want it private.
    token = os.environ.get("OKL_TOKEN")
    # The same reasoning reaches the spec routes, and they were missed when the data
    # routes were closed: FastAPI serves /openapi.json, /docs and /redoc to anyone by
    # default, and no `_auth` call can protect them because the framework mounts them
    # itself. They leak the endpoint list, every schema and where the credential is
    # required — the map you would draw before attacking the routes. Setting the token
    # is the signal that this instance is not a laptop, so the spec comes down with it.
    docs = {} if token is None else {"openapi_url": None, "docs_url": None, "redoc_url": None}
    app = FastAPI(title="OKL — the sixth surface", version="0.1.0", **docs)
    _store = store or Store(os.environ.get("OKL_DATABASE_URL"))

    def _auth(authorization: str | None) -> None:
        if token and authorization != f"Bearer {token}":
            raise HTTPException(status_code=401, detail="missing or bad bearer token")

    @app.get("/health")
    def health() -> dict[str, Any]:
        # Deliberately open even when a token is set: schedulers and load balancers
        # probe this before they hold any credential, and a deploy that cannot be
        # health-checked never goes live. It returns a count and a backend name, no content.
        return {"ok": True, "nodes": len(_store.all_nodes()), "backend": _store.url.split(":")[0]}

    @app.post("/check")
    def check(req: CheckReq, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth(authorization)
        return core.check(_store, req.repo, req.task, limit=req.limit,
                          interests=req.interests)

    @app.post("/record")
    def record(req: RecordReq, authorization: str | None = Header(default=None)) -> dict[str, str]:
        _auth(authorization)
        try:
            node_id = core.record(_store, **req.model_dump())
        except ValueError as e:
            # Validation (unknown tag, bad scope) is the CALLER's error and must carry the
            # message (e.g. the tag vocabulary) — a 500 hides it and reads as an outage.
            raise HTTPException(status_code=400, detail=str(e)) from e
        return {"id": node_id}

    @app.post("/search")
    def search(req: SearchReq, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth(authorization)
        return {"results": core.search(_store, req.query, req.scope, req.node_types, req.limit)}

    @app.post("/link")
    def link(req: LinkReq, authorization: str | None = Header(default=None)) -> dict[str, bool]:
        _auth(authorization)
        core.link(_store, req.src, req.rel, req.dst)
        return {"ok": True}

    @app.post("/verify")
    def verify(req: VerifyReq, authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth(authorization)
        try:
            return core.verify(_store, req.id, req.evidence)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

    @app.get("/metric/recurrence")
    def recurrence(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth(authorization)
        rows = _store.recurrence_after_arming()
        return {"recurrence_after_arming": rows, "count": len(rows)}

    @app.get("/nodes")
    def nodes(authorization: str | None = Header(default=None)) -> dict[str, Any]:
        _auth(authorization)
        from dataclasses import asdict
        rows = [asdict(n) for n in _store.all_nodes()]
        return {"nodes": rows, "count": len(rows)}

    return app


_app: FastAPI | None = None


def __getattr__(name: str):
    """Build `app` on first attribute access, not at import.

    Every ASGI host — uvicorn, gunicorn, a platform's default start command — is
    pointed at `module:app`, and that is what this module's own docstring tells you
    to run. `app` used to be a module-level `None` that `run()` reassigned as a side
    effect, so `uvicorn okl.service:app` served a None: the process started, bound the
    port, looked healthy to anything watching the port, and answered 500 to every
    request. A deploy that fails at startup is a nuisance; one that comes up and then
    fails every call is an outage that reads as a bug in the caller.

    PEP 562 module `__getattr__` fires only when normal lookup fails, which is what
    keeps the database out of import time: `import okl.service` still touches nothing,
    so the CLI and the tests can import this module without a configured backend.
    """
    if name == "app":
        global _app
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def run(host: str = "0.0.0.0", port: int = 8080) -> None:
    import uvicorn
    uvicorn.run(create_app(), host=host, port=port)
