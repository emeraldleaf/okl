"""The client and the service agree on every request field.

Lesson remote-path-test-through-client (three past breaks, #415). The service's request models
ignore a key they do not have, so a field the client sends that the model lacks is dropped
without a word: the feature works locally and does nothing over a shared service. Two checks:
every keyword the core functions behind the service take is a field of the model that carries it,
and every body the real client posts, through the real app (the remote fixture), names only
fields the model bound to that path reads.
"""
import inspect
import re
from pathlib import Path

import pytest

from okl import core

REPO = Path(__file__).resolve().parent.parent
RENAMED = {"node_id": "id"}   # the client sends the lesson's id as `id`


def models() -> dict[str, type]:
    """Each POST path the service answers, with the request model it binds."""
    pytest.importorskip("fastapi")
    from fastapi.routing import APIRoute

    from okl.service import create_app
    from okl.store import Store
    app = create_app(Store("sqlite:///:memory:"))
    out = {}
    for route in app.routes:
        if isinstance(route, APIRoute) and "POST" in route.methods:
            (body,) = route.dependant.body_params
            out[route.path] = body.field_info.annotation
    return out


def posted_paths() -> set[str]:
    """Every path the client's source posts to."""
    return set(re.findall(r'_post\("(/[\w-]+)"', (REPO / "src" / "okl" / "client.py").read_text()))


def test_each_core_function_behind_the_service_has_a_field_for_every_keyword():
    """A keyword core accepts that its request model lacks is one a remote caller cannot send."""
    from okl import service
    for fn, model in ((core.record, service.RecordReq), (core.retire, service.RetireReq),
                      (core.log_check, service.CheckRunReq), (core.search, service.SearchReq),
                      (core.link, service.LinkReq), (core.verify, service.VerifyReq)):
        takes = {RENAMED.get(p, p) for p in inspect.signature(fn).parameters} - {"store"}
        assert takes == set(model.model_fields), (fn.__name__, sorted(takes ^ set(model.model_fields)))
    assert set(core.UPDATABLE_FIELDS) == set(service.UpdateFields.model_fields)


def test_every_field_the_real_client_posts_is_one_the_service_reads(remote):
    """Each client call that posts, with every optional argument given, through the real app."""
    from okl.client import Client
    c = Client()
    c.index = c.near_misses = True
    c.check("add a login page", limit=5, log=False)
    c.check("", paths=["a.py"], log=False)
    first = c.record(type="Rule", title="Refuse an empty list", scope="org", body="cause: x",
                     symptom="s", fix="f", tags="method", files="a.py", status="live")
    second = c.record(type="Rule", title="Refuse an empty set", scope="org", fix="f")
    c.update(first, title="Refuse an empty list, loudly")
    c.search("empty", scope="org", node_types=["Rule"], limit=5)
    c.link(second, "SUPERSEDES", first)
    c.log_check(first, passed=True, command="true", outcome="exit 0", expect="ok", commit="abc1234")
    c.verify(first, evidence="`true` exit 0", commit="abc1234")
    c.retire(second, "wrong", by=None, obsolete=False)

    bound = models()
    for path, body in remote.sent:
        fields = set(bound[path].model_fields)
        assert set(body) <= fields, (path, sorted(set(body) - fields))
        if path == "/update":
            from okl.service import UpdateFields
            assert set(body["fields"]) <= set(UpdateFields.model_fields), sorted(body["fields"])
    assert posted_paths() <= {path for path, _ in remote.sent}, \
        f"a path the client posts to is not exercised here: {sorted(posted_paths() - {p for p, _ in remote.sent})}"
