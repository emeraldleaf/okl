"""Tests never touch a real store, whatever the developer's shell has exported.

Incident (2026-09-27): OKL_DATABASE_URL was exported in a shell so `okl drift` could find
the main tree's store from a git worktree; two `pytest` runs inherited it and wrote 28
org-scoped fixture records into the real .okl/okl.db, where they would have reached every
briefing. okl has no delete on purpose, so the cleanup was direct SQL. This fixture makes
the suite deaf to those variables. Tests that need a store name one explicitly.
"""
import pytest

STORE_VARS = ("OKL_DATABASE_URL", "OKL_SERVICE_URL", "OKL_TOKEN")


@pytest.fixture(autouse=True)
def _no_real_store(monkeypatch):
    for var in STORE_VARS:
        monkeypatch.delenv(var, raising=False)
