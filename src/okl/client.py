"""Client resolution: talk to a REMOTE service if configured, else a LOCAL store.

`okl connect <url>` writes the service URL into .okl/config.json. When a remote
is configured every operation is an HTTP call; otherwise it falls back to a
local store file (single-machine mode). This is what lets the same CLI work
before you've deployed the shared service and after.
"""
from __future__ import annotations

import http.client
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib import request as _req
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode

from . import core, decide, drift, warm
from .store import Node, Store

CONFIG_DIR = ".okl"
CONFIG_FILE = "config.json"

# How long to wait on the shared service. It is not a limit on the whole call: urllib
# applies it to each connect and each read, and tries a connect once per address the host
# resolves to, so a dual-stack host that drops connections costs 10 s. The prompt hook
# bounds it: Claude Code cancels a UserPromptSubmit hook after 30 s and lets the prompt
# through unbriefed. At 10 s, three stalled tries took about 31 s (okl review R10); the
# hook now retries only a quick failure, and tests/test_remote_failures.py keeps its
# worst case, two stalled addresses included, under that limit.
_HTTP_TIMEOUT_S = 5


def _find_config(start: Path | None = None) -> Path | None:
    """Walk up from `start` looking for .okl/config.json.

    Ancestor search, not cwd-only, so okl works from a subdirectory of the repo the
    way git does. Returning None is meaningful: it is what `configured` reports on,
    and an unconfigured directory must refuse to answer rather than create an empty
    store and call it clean.
    """
    p = (start or Path.cwd()).resolve()
    for d in [p, *p.parents]:
        cfg = d / CONFIG_DIR / CONFIG_FILE
        if cfg.exists():
            return cfg
    return None


def load_config() -> dict[str, Any]:
    """Read the nearest config, or an empty dict when there is none."""
    cfg = _find_config()
    if cfg:
        return json.loads(cfg.read_text())
    return {}


def save_config(data: dict[str, Any], root: Path | None = None) -> Path:
    """Write .okl/config.json, creating the directory and its .gitignore.

    The .gitignore is written here rather than at init because this is the single
    place the directory is created — everything that lands in it is machine-local or
    secret, and a config written by any path must be protected the same way.
    """
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
    text = json.dumps(data, indent=2) + "\n"
    if not data.get("token"):
        path.write_text(text)
        return path
    # A config holding the service token is a credential file, so it is owner-only (#98):
    # written with default permissions, every local user could read it. The token goes
    # into a NEW file that replaces the old one, never into the old one: chmod does not
    # revoke a handle another user already opened on a world-readable config, and the
    # token written through that file would be read through it (CodeRabbit on #144).
    # mkstemp creates the file 0600; the replace swaps it in atomically. Windows has no
    # such bits; there the advice stays OKL_TOKEN from the environment.
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".config.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        Path(tmp).replace(path)
    finally:
        Path(tmp).unlink(missing_ok=True)   # gone after the replace; no stray copy if it failed
    return path


def hybrid_setting(env: str | None, configured: Any) -> str | None:
    """The fusion `check` runs, or None for full-text only: OKL_HYBRID wins over the
    config's `hybrid`; off/0/empty turn it off, on/1/true/linear mean the convex
    combination (the measured configuration, REPORT §4q), rrf reciprocal-rank fusion (#258)."""
    raw = env if env is not None else configured
    if raw in (None, False, "", "0", "off", "false", "none"):
        return None
    if raw in (True, "1", "on", "true", "linear"):
        return "linear"
    if raw == "rrf":
        return "rrf"
    raise ValueError(f"hybrid must be rrf, linear or off, not {raw!r}")


def rerank_setting(env: str | None, configured: Any) -> bool:
    """Whether `check` runs the cross-encoder second stage (REPORT §4t): OKL_RERANK wins over the
    config's `rerank`; off/0/empty mean no, on/1/true mean yes."""
    raw = env if env is not None else configured
    if raw in (None, False, "", "0", "off", "false", "none", "no"):
        return False
    if raw in (True, "1", "on", "true", "yes"):
        return True
    raise ValueError(f"rerank must be on or off, not {raw!r}")


def warm_setting(env: str | None, configured: Any) -> bool:
    """Whether `check` asks the warm model (REPORT §4z): OKL_WARM wins over the config's `warm`;
    off/0/empty mean no, on/1/true mean yes."""
    raw = env if env is not None else configured
    if raw in (None, False, "", "0", "off", "false", "none", "no"):
        return False
    if raw in (True, "1", "on", "true", "yes"):
        return True
    raise ValueError(f"warm must be on or off, not {raw!r}")


def decision_setting(env: str | None, configured: Any) -> str:
    """How `check` turns candidates into a briefing (#291, REPORT §4w, §4y): OKL_DECISION wins
    over the config's `decision`; decide.DEFAULT ("tiered": the calibrated line's lessons in
    full and the rest of what matched one line each) unless one names another setting."""
    raw = env if env not in (None, "") else configured
    if raw in (None, ""):
        return decide.DEFAULT
    raw = str(raw).strip().lower()
    decide.check_setting(raw)
    return raw


class Client:
    """Uniform surface over local-store and remote-service modes."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config if config is not None else load_config()
        self.service_url = os.environ.get("OKL_SERVICE_URL") or self.config.get("service_url")
        self.repo = self.config.get("repo") or Path.cwd().name
        self.interests = self.config.get("interests") or []
        self.hybrid = hybrid_setting(os.environ.get("OKL_HYBRID"), self.config.get("hybrid"))
        self.index = False   # the index arm (REPORT §4r): set per call by `okl check --index`
        self.near_misses = False   # the near-miss arm (REPORT §4s): `okl check --near-misses`
        self.rerank = rerank_setting(os.environ.get("OKL_RERANK"), self.config.get("rerank"))
        self.decision = decision_setting(os.environ.get("OKL_DECISION"), self.config.get("decision"))
        self.warm = warm_setting(os.environ.get("OKL_WARM"), self.config.get("warm"))
        self._store: Store | None = None

    @property
    def mode(self) -> str:
        """Where operations go: "remote" when a service URL is set, else "local"."""
        return "remote" if self.service_url else "local"

    @property
    def configured(self) -> bool:
        """True when a store has been named: by `okl init`, a service URL, or
        OKL_DATABASE_URL.

        Naming the database counts as configuring one. Leaving it out made the commands
        disagree — `record` honoured the variable and wrote, while `check` refused as
        unconfigured, so you could write to a store you were denied a read from.

        Safe because the thing this guard was written for is caught downstream anyway:
        `core.check` reports an empty store as EMPTY / "proves nothing" rather than clean.
        What it still protects is the bare directory where nothing has been named at all,
        where `_local_store` refuses rather than invent a database.
        """
        return (bool(self.service_url)
                or bool(os.environ.get("OKL_DATABASE_URL"))
                or _find_config() is not None)

    def _local_store(self) -> Store:
        if self._store is None:
            # OKL_DATABASE_URL wins when set. Store has honoured it since v0.1 and the
            # service passes it through, but this method used to build a config-adjacent
            # sqlite URL unconditionally — so every CLI command ignored it. Pointing the
            # variable at Postgres and running `okl record` wrote to a local file instead,
            # silently, which is the worst shape a storage bug can take: you are told the
            # record landed, and it landed somewhere else.
            url = os.environ.get("OKL_DATABASE_URL")
            if not url:
                # Otherwise the local store lives next to the config. With no config there
                # is no store, and this used to invent one as ./okl.db: `okl record` and
                # `okl seed` then exited 0 having written lessons where no hook, check or
                # CI job ever looks (#117). Refusing here covers every command at once.
                cfg = _find_config()
                if cfg is None:
                    raise OKLNotConfiguredError(
                        "not configured: no .okl/config.json here or in any parent directory, "
                        "and neither OKL_SERVICE_URL nor OKL_DATABASE_URL is set, so there is "
                        "no store to use. Run `okl init` here, or `okl connect <url>`.")
                url = f"sqlite:///{cfg.parent / 'okl.db'}"
            self._store = Store(url)
        return self._store

    def _remote_url(self, path: str) -> str:
        """Absolute URL for `path` on the configured service.

        Every remote call reaches here, so the "a service is configured" invariant is
        asserted once instead of being assumed at four call sites. Reaching it without a
        service_url is a programming error — the caller checked `mode` wrongly — not a
        user-facing condition, so it raises rather than degrading to a local read.
        """
        if not self.service_url:
            raise RuntimeError("no service configured; this path is only valid in remote mode")
        # The URL comes from .okl/config.json or an env var, so its scheme is input.
        # urlopen honours file:// and ftp://, which would turn "read from the shared
        # service" into "read a local file the caller chose" — checked here, once, rather
        # than trusted at four call sites.
        if not self.service_url.startswith(("http://", "https://")):
            raise ValueError(
                f"service_url must be http:// or https://, got {self.service_url!r}")
        return self.service_url.rstrip("/") + path

    def _authorize(self, req: _req.Request) -> None:
        """Attach the bearer token, if one is configured.

        One place, because both verbs need it: the token used to go on POSTs only, which
        was survivable only while the service left reads open. When reads were gated,
        every GET started 401-ing and surfaced as "unreachable" — an outage, for a
        credential problem.
        """
        token = os.environ.get("OKL_TOKEN") or self.config.get("token")
        if token:
            req.add_header("Authorization", f"Bearer {token}")

    # -- HTTP helper (stdlib only; fails CLOSED — raises, never returns empty) --
    def _post(self, path: str, payload: dict) -> dict:
        url = self._remote_url(path)
        data = json.dumps(payload).encode()
        # _remote_url has already rejected any scheme but http/https
        req = _req.Request(url, data=data,  # noqa: S310
                           headers={"Content-Type": "application/json"})
        self._authorize(req)
        try:
            with _req.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:  # noqa: S310
                body = resp.read()
        except HTTPError as e:
            # The service answered — so this is NOT "unreachable". A 4xx is the caller's
            # error and must surface its detail (found by E2E: an unknown-tag 400 was
            # reported to the agent as an outage). An HTTPError owns the response, socket
            # and all, so it is closed here: R1 made 400s and 404s routine, and the leak
            # failed the 3.14 suite on ResourceWarning.
            with e:
                try:
                    detail = json.loads(e.read()).get("detail", "")
                except Exception:  # noqa: BLE001
                    detail = ""
            if 400 <= e.code < 500:
                raise OKLRejectedError(f"OKL service rejected the request ({e.code}): {detail or e.reason}",
                                       status=e.code) from e
            raise OKLUnreachableError(f"OKL service error at {url}: {e.code} {detail or e.reason}") from e
        except URLError as e:
            raise OKLUnreachableError(f"OKL service unreachable at {url}: {e}") from e
        except (OSError, http.client.HTTPException) as e:   # after URLError, an OSError too
            raise _no_answer(url, e) from e
        return _json_reply(url, body)

    # -- operations ---------------------------------------------------------
    def check(self, task: str, repo: str | None = None, limit: int | None = None) -> dict:
        """The briefing for starting `task` in `repo` (default: this repo), as core.check returns it.

        Lessons whose governed code changed since their last check come back marked.
        Over a shared service, raises ValueError when the service rejects the request (any
        4xx, such as a 401 for a missing token) and OKLUnreachableError when it cannot be
        reached or fails on its side (a network error or any 5xx).
        """
        repo = repo or self.repo
        payload = {"repo": repo, "task": task, "interests": self.interests or None,
                   "hybrid": self.hybrid, "index": self.index, "near_misses": self.near_misses,
                   "rerank": self.rerank, "decision": self.decision}
        if limit is not None:
            payload["limit"] = limit
        if self.mode == "remote":
            result = self._post("/check", payload)
            # An older service drops a request field it does not know and answers an ordinary
            # briefing; a caller who asked for the index or the near misses must not read
            # that as "none" (review on #270).
            for wanted, key in ((self.index, "index"), (self.near_misses, "near_misses")):
                # A missing key and a null are the same answer: not the list that was asked for.
                if wanted and not isinstance(result.get(key), list):
                    raise OKLRejectedError(_TOO_OLD.format(what=f"answers `{key}` on /check"), status=404)
            # An older service drops `decision` too, and answers by the floor. Every client sends
            # a decision, so refusing as above would refuse every check in every repo until the
            # service is upgraded; a briefing must not fail on what the service cannot run (the
            # hybrid arm's rule), so the result says which decision answered (review on #292).
            answered = result.get("decision") or "floor"
            if answered != self.decision:
                result["decision_unavailable"] = (f"the service answered by the {answered} decision, not "
                                                  f"{self.decision}: it predates it; upgrade the service")
            result["decision"] = answered
        else:
            kw: dict[str, Any] = {"interests": self.interests, "hybrid": self.hybrid, "index": self.index,
                                  "near_misses": self.near_misses, "rerank": self.rerank,
                                  "decision": self.decision, "warm": self.warm}
            if limit is not None:
                kw["limit"] = limit
            store = self._local_store()
            result = core.check(store, repo, task, **kw)
            if "not running" in str(result.get("warm_unavailable", "")) and warm.installed():
                # Started now, in the background, so the next prompt is briefed by meaning too;
                # this one does not wait for a model to load (REPORT §4z).
                warm.start()
        # Mark briefed lessons whose code changed since their last check (#93). Done here,
        # not in core, because only the client has this repo's checkout: a shared service
        # answering /check has no git history to compare against.
        cfg = _find_config()
        drift.annotate_briefing(result, repo, str(cfg.parent.parent if cfg else Path.cwd()))
        if self.mode != "remote":
            # Over a shared service the service logs the briefing it answers; locally, the
            # client is the only one who sees it (#129). Logged after the drift marks, so
            # the log keeps which briefed lessons were stale at the time (#252).
            core.record_briefing(store, repo, result)
        return result

    def record(self, **kwargs: Any) -> str:
        """Record a lesson and return its id; takes core.record's keyword fields.

        `repo` defaults to this repo. Raises ValueError when the lesson is rejected,
        e.g. for an unknown tag or a bad scope.
        """
        # Default the repo in BOTH modes: `--scope repo` needs it to become repo:<name>,
        # and the remote path used to skip this (found by E2E: 400 on every repo-scoped record).
        # `setdefault` is not enough: callers that pass every field explicitly (the MCP
        # tools do) send repo=None, so the key EXISTS and setdefault leaves the None in
        # place. Found by live-testing the MCP server: every scope="repo" record failed.
        if kwargs.get("repo") is None:
            kwargs["repo"] = self.repo
        if self.mode == "remote":
            # None means "not given": the service has defaults for every optional field,
            # and a null where it expects a boolean (replace) is a 422 (review of okl R1).
            body = {k: v for k, v in kwargs.items() if v is not None}
            if body.get("id") and not (body.get("replace") or body.get("keep_verification")):
                self._require_refusing_service()
            try:
                return self._post("/record", body)["id"]
            except OKLRejectedError as e:
                # The same refusal as in local mode, so every caller can tell it apart
                # from any other rejected write.
                if e.status == 400 and "already exists" in str(e):
                    raise core.LessonExistsError(str(e)) from e
                raise
        return core.record(self._local_store(), **kwargs)

    def _require_refusing_service(self) -> None:
        """Refuse to record an id against a service that would silently overwrite it.

        A service older than okl's refusal (R1) ignores `replace` and replaces the lesson,
        proof and all, which is the defect R1 fixed. It also lacks GET /node, so asking for
        any lesson tells the two apart: a 404 is the old service.
        """
        try:
            self._get("/node/-")
        except OKLRejectedError as e:
            if e.status == 404:
                raise OKLRejectedError(_TOO_OLD.format(what="refuses to overwrite an "
                                                            "existing id"), status=404) from e
            raise

    def update(self, node_id: str, **fields: Any) -> dict:
        """Change the given fields of a lesson, keep the rest and its proof, and return it.

        Takes core.update's fields: None leaves one alone, "" clears an optional one. The
        proof is cleared only when the governed files change. Raises ValueError for an
        unknown id or a rejected value.
        """
        if self.mode == "remote":
            try:
                return self._post("/update", {"id": node_id, "repo": self.repo,
                                              "fields": {k: v for k, v in fields.items()
                                                         if v is not None}})
            except OKLRejectedError as e:
                if e.status == 404:
                    raise OKLRejectedError(_TOO_OLD.format(what="has okl update"),
                                           status=404) from e
                raise
        return core.update(self._local_store(), node_id, repo=self.repo, **fields)

    def retire(self, node_id: str, reason: str, by: str | None = None,
               obsolete: bool = False) -> dict:
        """Retire a lesson with a reason: wrong (the default), replaced `by` another, or
        `obsolete`. Returns the lesson; raises ValueError for anything core.retire refuses."""
        if self.mode == "remote":
            try:
                return self._post("/retire", {"id": node_id, "reason": reason, "by": by,
                                              "obsolete": obsolete})
            except OKLRejectedError as e:
                if e.status == 404:
                    raise OKLRejectedError(_TOO_OLD.format(what="has okl retire"),
                                           status=404) from e
                raise
        return core.retire(self._local_store(), node_id, reason, by=by, obsolete=obsolete)

    def log_check(self, node_id: str, *, passed: bool, command: str, outcome: str,
                  expect: str | None = None, commit: str | None = None) -> None:
        """Keep one run of a lesson's check, pass or fail (core.log_check). Raises
        ValueError for a run it refuses, or for a service too old to keep them."""
        if self.mode == "remote":
            try:
                self._post("/check-run", {"id": node_id, "passed": passed, "command": command,
                                          "outcome": outcome, "expect": expect, "commit": commit})
            except OKLRejectedError as e:
                if e.status == 404:
                    raise OKLRejectedError(_TOO_OLD.format(what="keeps check runs"),
                                           status=404) from e
                raise
            return
        core.log_check(self._local_store(), node_id, passed=passed, command=command,
                       outcome=outcome, expect=expect, commit=commit)

    def get(self, node_id: str) -> dict | None:
        """One lesson by id, or None if there is none."""
        if self.mode == "remote":
            # A missing lesson is {"node": null}, never a 404: a service too old to have
            # this route answers 404, and that must not read as "no such lesson".
            try:
                return self._get(f"/node/{quote(node_id, safe='')}")["node"]
            except OKLRejectedError as e:
                if e.status == 404:
                    raise OKLRejectedError(_TOO_OLD.format(what="has okl show"),
                                           status=404) from e
                raise
        return core.get(self._local_store(), node_id)

    def search(self, query: str, scope: str | None = None,
               node_types: list[str] | None = None, limit: int = 25) -> list[dict]:
        """Lessons matching `query`, best first, optionally limited to a scope and node types."""
        if self.mode == "remote":
            return self._post("/search", {"query": query, "scope": scope,
                                          "node_types": node_types, "limit": limit})["results"]
        return core.search(self._local_store(), query, scope, node_types, limit)

    def link(self, src: str, rel: str, dst: str) -> None:
        """Join two lessons with a typed edge, `src -rel-> dst`.

        An unknown relation raises ValueError, locally or over a shared service.
        """
        if self.mode == "remote":
            self._post("/link", {"src": src, "rel": rel, "dst": dst})
            return
        core.link(self._local_store(), src, rel, dst)

    def verify(self, node_id: str, evidence: str, commit: str | None = None) -> dict:
        """Mark a lesson verified and return it as a dict.

        `evidence` names the check that passed; `commit` is the git HEAD it passed at,
        which drift compares against. Raises ValueError for an unknown id, empty evidence or
        a commit that is not a git object name.
        """
        if self.mode == "remote":
            # A service older than #102 drops `commit` (pydantic ignores unknown fields),
            # and drift then falls back to comparing times: degraded, never wrong.
            return self._post("/verify", {"id": node_id, "evidence": evidence, "commit": commit})
        return core.verify(self._local_store(), node_id, evidence, commit)

    def recurrence_report(self) -> dict | None:
        """The coverage-aware report, or None from a service too old to compute one --
        in which case the caller must say coverage is unknown, not assume it is fine."""
        if self.mode == "remote":
            return self._get("/metric/recurrence").get("report")
        return core.recurrence_report(self._local_store())

    def exposure_report(self) -> dict | None:
        """Which lessons this repo's briefings have shown (#129), or None from a service
        too old to report it, in which case the caller says exposure is unknown."""
        if self.mode == "remote":
            query = urlencode({"repo": self.repo, "interests": ",".join(self.interests or [])})
            try:
                return self._get(f"/metric/exposure?{query}").get("report")
            except OKLRejectedError as e:
                if e.status == 404:
                    return None
                raise
        return core.exposure_report(self._local_store(), self.repo, self.interests)

    def hygiene_report(self) -> dict | None:
        """Stale-use and over-scope rates for this repo (#252), or None from a service too
        old to report them, in which case the caller says hygiene is unknown."""
        if self.mode == "remote":
            try:
                return self._get(f"/metric/hygiene?{urlencode({'repo': self.repo})}").get("report")
            except OKLRejectedError as e:
                if e.status == 404:
                    return None
                raise
        return core.hygiene_report(self._local_store(), self.repo)

    def recurrence(self) -> list[dict]:
        """The v0.5 flat rows, kept for callers written against that release. Both modes
        read the one report: remote through the legacy keys the service derives from it,
        local through the same derivation."""
        if self.mode == "remote":
            return self._get("/metric/recurrence")["recurrence_after_arming"]
        return core.recurrence_rows(core.recurrence_report(self._local_store()))

    def all_nodes(self) -> list[Node]:
        """Return every node in the store, unfiltered (local store, or /nodes on a remote service).

        Used by the drift detector, which needs the node set locally but runs its
        git lookups against the working tree.
        """
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
        url = self._remote_url(path)
        # _remote_url has already rejected any scheme but http/https
        req = _req.Request(url)  # noqa: S310
        self._authorize(req)
        try:
            with _req.urlopen(req, timeout=_HTTP_TIMEOUT_S) as resp:  # noqa: S310
                body = resp.read()
        except HTTPError as e:
            e.close()   # it owns the response and its socket; see _post
            if 400 <= e.code < 500:
                raise OKLRejectedError(
                    f"OKL service rejected the request ({e.code} {e.reason}). "
                    "If this is 401, set OKL_TOKEN or add \"token\" to .okl/config.json.",
                    status=e.code) from e
            raise OKLUnreachableError(f"OKL service error at {url}: {e.code} {e.reason}") from e
        except URLError as e:
            raise OKLUnreachableError(f"OKL service unreachable at {url}: {e}") from e
        except (OSError, http.client.HTTPException) as e:   # after URLError, an OSError too
            raise _no_answer(url, e) from e
        return _json_reply(url, body)


# For a 404 from a route a service older than R1 lacks: say so, rather than leave the
# person reading "404 Not Found" as a missing lesson or an outage.
_TOO_OLD = ("the OKL service is older than this okl client and nothing was changed: it "
            "predates the version that {what}. Upgrade the service to match.")


def _no_answer(url: str, e: OSError | http.client.HTTPException) -> OKLNoAnswerError:
    """The service took the request and no usable answer came back: it stalled past the
    timeout, dropped the connection, or replied with something that is not HTTP.

    urllib wraps a failure to connect or to send in URLError; these come later, from
    reading the reply, as a bare TimeoutError, ConnectionResetError, RemoteDisconnected,
    BadStatusLine or IncompleteRead. They escaped `okl check` as a traceback and exit 1
    (okl review R10). They are an outage like any other, so the callers that fail closed
    on OKLUnreachableError fail closed on them too.
    """
    if isinstance(e, TimeoutError):
        cause = f"no full reply came within {_HTTP_TIMEOUT_S} s"
    elif isinstance(e, OSError):   # RemoteDisconnected is an HTTPException as well
        cause = f"the connection was dropped before a full reply ({str(e) or type(e).__name__})"
    else:
        # repr, and cut short: a banner from whatever answered on that port carries its own
        # line breaks and can run to 64 KB, and the CLI prints this as one line.
        cause = f"the reply was not HTTP or was cut short ({repr(e)[:200]})"
    return OKLNoAnswerError(f"OKL service unreachable at {url}: the request was sent, and {cause}")


def _json_reply(url: str, body: bytes) -> Any:
    """The service's 2xx reply, parsed.

    Something that is not okl can answer 200: a proxy's sign-in page, or a web app on the
    port OKL_SERVICE_URL names. json.loads raised a ValueError, which every caller reads
    as the service refusing the request ("OKL REFUSED THE CHECK"); nothing refused it, and
    after a write the service behind the page may have stored it (okl review R10). So it
    is no answer: an outage to every caller that fails closed, a "maybe" to a writer.
    """
    try:
        return json.loads(body)
    except ValueError as e:   # JSONDecodeError, and UnicodeDecodeError for bytes that are not text
        # One line, cut short: the CLI prints it under its refusal.
        shown = " ".join(body[:120].decode("utf-8", "replace").split())
        raise OKLNoAnswerError(
            f"OKL service unreachable at {url}: the request was sent, and the reply was not "
            f"JSON ({shown!r}); is something other than okl answering at this address?") from e


class OKLRejectedError(ValueError):
    """Raised when a shared service answered and refused the request (any 4xx, such as a
    401 for a missing token or a 400 for an unknown tag). The caller's mistake, not an
    outage; a ValueError, so the CLI's backstop still turns it into exit 2.

    `status` is the HTTP code, so a caller can tell a 404 from an older service that
    lacks a route apart from a 401 it must not paper over.
    """

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class OKLNotConfiguredError(ValueError):
    """Raised when a command needs a store and nothing names one: no .okl/config.json, no
    OKL_SERVICE_URL, no OKL_DATABASE_URL. A ValueError, so the CLI's backstop turns it
    into exit 2 ("could not run") with this message, never a write to a stray file."""


class OKLUnreachableError(RuntimeError):
    """Raised when a configured remote service can't be reached. Callers that
    gate work on OKL (the pre-task hook) must FAIL CLOSED on this — the
    merge-gate lesson: a check that silently returns 'nothing' is worse than
    no check."""


class OKLNoAnswerError(OKLUnreachableError):
    """Raised when a request reached the shared service and no usable answer came back.

    The request was sent before the answer was lost, so the service may have acted on it.
    Still an outage to every caller that fails closed; a caller that wrote (record, verify)
    must not tell the person the write was lost, or a retry stores it twice.
    """


# The pre-0.4 name. Kept as an alias because it is importable from a published
# release and appears in consumers' except clauses; the class is the same object,
# so `except OKLUnreachable` still catches what `raise OKLUnreachableError` throws.
OKLUnreachable = OKLUnreachableError
