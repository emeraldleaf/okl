"""Tests never touch a real store, whatever the developer's shell has exported.

Incident (2026-09-27): OKL_DATABASE_URL was exported in a shell so `okl drift` could find
the main tree's store from a git worktree; two `pytest` runs inherited it and wrote 28
org-scoped fixture records into the real .okl/okl.db, where they would have reached every
briefing. okl has no delete on purpose, so the cleanup was direct SQL. This fixture makes
the suite deaf to those variables. Tests that need a store name one explicitly.
"""
import json

import pytest

STORE_VARS = ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN")


@pytest.fixture(autouse=True)
def _no_real_store(monkeypatch):
    for var in STORE_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def remote(tmp_path, monkeypatch):
    """A repo connected to an okl service served in-process: the Client's real remote code
    (urllib, its error mapping) talks to the real app, with no socket. Both reviews found
    remote paths that only ever had their service posted to directly, never via Client."""
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")
    import io
    from types import SimpleNamespace
    from urllib.error import HTTPError
    from urllib.parse import urlsplit

    from fastapi.testclient import TestClient

    from okl.service import create_app
    from okl.store import Store

    for k in ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".okl").mkdir()
    (tmp_path / ".okl" / "config.json").write_text(
        json.dumps({"repo": "r", "service_url": "http://okl.test"}))
    store = Store("sqlite:///:memory:")
    app = create_app(store=store)
    api = TestClient(app)

    class Reply(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def urlopen(req, timeout=None):
        u = urlsplit(req.full_url)
        r = api.request(req.get_method(), u.path + (f"?{u.query}" if u.query else ""),
                        content=req.data, headers=dict(req.header_items()))
        if r.status_code >= 400:
            raise HTTPError(req.full_url, r.status_code, r.reason_phrase, None,
                            io.BytesIO(r.content))
        return Reply(r.content)

    monkeypatch.setattr("okl.client._req.urlopen", urlopen)
    return SimpleNamespace(store=store, app=app, api=api)
