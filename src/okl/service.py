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
    app = FastAPI(title="OKL — the sixth surface", version="0.1.0")
    _store = store or Store(os.environ.get("OKL_DATABASE_URL"))
    # Optional shared-secret gate. If OKL_TOKEN is set, writes require it.
    write_token = os.environ.get("OKL_TOKEN")

    def _auth(authorization: str | None) -> None:
        if write_token and authorization != f"Bearer {write_token}":
            raise HTTPException(status_code=401, detail="missing or bad bearer token")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True, "nodes": len(_store.all_nodes()), "backend": _store.url.split(":")[0]}

    @app.post("/check")
    def check(req: CheckReq) -> dict[str, Any]:
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
    def search(req: SearchReq) -> dict[str, Any]:
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
    def recurrence() -> dict[str, Any]:
        rows = _store.recurrence_after_arming()
        return {"recurrence_after_arming": rows, "count": len(rows)}

    @app.get("/nodes")
    def nodes() -> dict[str, Any]:
        from dataclasses import asdict
        rows = [asdict(n) for n in _store.all_nodes()]
        return {"nodes": rows, "count": len(rows)}

    return app


app = None


def run(host: str = "0.0.0.0", port: int = 8080) -> None:
    import uvicorn
    global app
    app = create_app()
    uvicorn.run(app, host=host, port=port)
