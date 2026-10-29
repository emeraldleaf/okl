"""The warm model (#293, REPORT §4z): one local process keeps EmbeddingGemma loaded, so the
briefing can add what a lesson means to the words it shares with the prompt.

The prompt hook is a new process on every prompt, and loading even the int8 model there costs
about a second (§4w, §4z). So `okl warm start` runs a small server on a Unix socket in the
user's cache directory: it loads the model once and answers each connection with the vectors
for a list of texts. `okl check` asks it for the prompt's vector with a short timeout; when
nothing answers (not started, still loading, too slow) the briefing is the model-free one and
says why. Nothing here imports the model unless it serves or indexes.

The score is §4w's: a lesson's shared subject words (decide.score) plus WEIGHT times the best
cosine between the prompt and any of its phrasings (title and symptom, each alias, each
trigger), over the full-text candidates and the model's own NEAREST, against LINE: split
conformal at alpha 0.05 on the benchmark's calibration prompts, as decide.CALIBRATED_LINE is.
A lesson's vectors are kept in the store's embedding table, its phrasings' rows in one blob.
"""
from __future__ import annotations

import base64
import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
import socket
import struct
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from . import hub
from .store import RETIRED_STATUSES, Node, Store

# The one-server lock's flock; where it does not exist (Windows), nothing is locked.
fcntl: Any = importlib.import_module("fcntl") if importlib.util.find_spec("fcntl") else None

BASE_MODEL = "google/embeddinggemma-300m"
# The int8 file of the same model: 92.0% recall on the benchmark's selection split against full
# precision's 92.4%, and a quarter of the download, 309 MB against 1,235 MB
# (warm-model-files-20261029.txt). Encoding a prompt takes about as long (170.7 ms against 173.5
# in the benchmark's receipts; REPORT §4z's erratum).
MODEL_ID = BASE_MODEL + "-quantized"
DIM = 768
QUERY = "task: search result | query: {}"     # the model card's retrieval prompts
DOC = "title: none | text: {}"
WEIGHT = 8.0       # §4w: the top of a broad rise on the selection split
# The 269th of 282 calibration nulls' best scores at W = 8 with this model, 5.7679259776, and just
# above it (bench-20261027-sel-dense-embeddinggemma-int8-words.txt; its W = 0 line is
# decide.CALIBRATED_LINE's, so the two are set the same way).
LINE = 5.767926
NEAREST = 36       # the model's own candidates, as many as the full-text window
TIMEOUT_S = 0.5    # what a prompt waits for the prompt's vector before briefing without it
IDLE_EXIT_S = 4 * 3600
# How long after a start the default waits before starting the server again: loading takes about
# a second, so a server that is not up by then failed, and starting another each prompt would
# fail the same way (review on #300).
RESTART_AFTER_S = 300
# A start this recent is still coming up: the new process has not yet imported okl and taken
# the lock, so a free lock does not mean it failed (review on #300).
STARTING_S = 30
INDEX_BATCH = 32   # lessons a request when indexing
EXTRA = "observed-knowledge-ledger[warm]"

Encoder = Callable[[list[str], str], list[list[float]]]
_encoder: Encoder | None = None   # tests and evals encode in-process; production asks the server


class WarmUnavailableError(RuntimeError):
    """The warm model could not answer: not started, still loading, too slow, or no vectors.
    `reason` is the check result's `warm_reason`, so a caller can act on the cause rather than
    its wording."""
    reason = "unavailable"


class WarmNotRunningError(WarmUnavailableError):
    """Nothing answers on the socket: never started, stopped, idle past IDLE_EXIT_S, or crashed.
    The one reason the client starts the server for, told by its type, not its words (review on
    #300)."""
    reason = "not_running"


class WarmNotIndexedError(WarmUnavailableError):
    """No lesson in this store has warm vectors: `okl warm index` has never run here. Asked for,
    that is a reason to say; by default, it means the store has not opted in (§4z decision)."""
    reason = "not_indexed"


def set_encoder(encoder: Encoder | None) -> None:
    """Encode in this process instead of asking the server: (texts, "query" | "doc") -> rows."""
    global _encoder
    _encoder = encoder


def socket_path() -> Path:
    """The server's socket: OKL_WARM_SOCKET, else okl's cache directory. One per user, since the
    model is the same for every store; each store keeps its own lesson vectors."""
    override = os.environ.get("OKL_WARM_SOCKET")
    if override:
        return Path(override).expanduser()
    return Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "okl" / "warm.sock"


def phrasings(n: Node) -> list[str]:
    """What a lesson says it is about and when it applies, one text per phrasing (§4w)."""
    head = ". ".join(x for x in (n.title, n.symptom) if x)
    return ([head] if head else []) + [a.strip() for a in (n.aliases or "").split(";") if a.strip()] \
        + [t.strip() for t in (n.triggers or "").splitlines() if t.strip()]


def phrasings_hash(n: Node) -> str:
    """Changes whenever a lesson's phrasings do, so its vectors are re-embedded."""
    return hashlib.sha256("\n".join(phrasings(n)).encode()).hexdigest()[:16]


def _pack(rows: list[list[float]]) -> bytes:
    return b"".join(struct.pack(f"<{len(r)}f", *r) for r in rows)


def _unpack(blob: bytes) -> list[list[float]]:
    flat = struct.unpack(f"<{len(blob) // 4}f", blob)
    return [list(flat[i:i + DIM]) for i in range(0, len(flat), DIM)]


# -- the client side --------------------------------------------------------------------------

def _ask(request: dict[str, Any], timeout: float) -> dict[str, Any]:
    """One request to the server, one JSON line each way."""
    path = socket_path()
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall(json.dumps(request).encode() + b"\n")
            buf = b""
            while not buf.endswith(b"\n"):
                chunk = s.recv(1 << 16)
                if not chunk:
                    break
                buf += chunk
    except FileNotFoundError:
        raise WarmNotRunningError("the warm model is not running: `okl warm start`") from None
    except TimeoutError:
        raise WarmUnavailableError(f"the warm model did not answer within {timeout:.1f} s") from None
    except OSError as e:
        raise WarmNotRunningError(f"the warm model is not running ({e.strerror or e}): `okl warm start`") from None
    try:
        reply = json.loads(buf)
    except json.JSONDecodeError:
        raise WarmUnavailableError("the warm model sent an unreadable answer") from None
    if not reply.get("ok"):
        raise WarmUnavailableError(str(reply.get("error") or "the warm model refused the request"))
    return reply


def embed(texts: list[str], kind: str, *, timeout: float = TIMEOUT_S) -> list[list[float]]:
    """Unit vectors for `texts`, read as queries or as documents (the model card's prompts)."""
    if _encoder is not None:
        return _encoder(texts, kind)
    reply = _ask({"op": "embed", "kind": kind, "texts": texts}, timeout)
    return _unpack(base64.b64decode(reply["vectors"]))


def ping(timeout: float = TIMEOUT_S) -> dict[str, Any] | None:
    """The server's model and process id, or None when nothing answers."""
    try:
        return _ask({"op": "ping"}, timeout)
    except WarmUnavailableError:
        return None


def cosines(store: Store, text: str) -> dict[str, float]:
    """Each lesson's best cosine with `text` over its phrasings. Raises WarmUnavailableError
    when the model does not answer or no lesson has vectors."""
    rows = store.embeddings(MODEL_ID)
    if not rows:
        raise WarmNotIndexedError("no lesson has warm vectors yet: `okl warm index`")
    q = embed([text], "query")[0]
    try:
        import numpy as np
    except ImportError:
        return {node_id: max(sum(a * b for a, b in zip(q, r, strict=False)) for r in _unpack(blob))
                for node_id, _h, blob in rows if blob}
    qv = np.asarray(q, dtype=np.float32)
    return {node_id: float(np.max(np.frombuffer(blob, dtype="<f4").reshape(-1, DIM) @ qv))
            for node_id, _h, blob in rows if blob}


def nearest(store: Store, cos: dict[str, float], visible: Callable[[Node], bool], k: int = NEAREST) -> list[Node]:
    """The `k` live lessons nearest by meaning that `visible` lets this repo see, best first."""
    out: list[Node] = []
    for node_id in sorted(cos, key=lambda i: -cos[i]):
        n = store.get_node(node_id)
        if n is not None and n.status not in RETIRED_STATUSES and visible(n):
            out.append(n)
            if len(out) == k:
                break
    return out


def index(store: Store, *, timeout: float = 120.0) -> dict[str, Any]:
    """Embed every live lesson whose phrasings changed since it was last embedded, and drop the
    vectors of lessons that are gone or retired. Asks the server; `okl warm index` starts one
    in this process when none runs."""
    have = {node_id: digest for node_id, digest, _ in store.embeddings(MODEL_ID)}
    live = [n for n in store.all_nodes() if n.status not in RETIRED_STATUSES and phrasings(n)]
    todo = [n for n in live if have.get(n.id) != phrasings_hash(n)]
    # A few dozen lessons a request: one request a lesson spent most of its time on the round trip.
    for i in range(0, len(todo), INDEX_BATCH):
        batch = todo[i:i + INDEX_BATCH]
        texts = [p for n in batch for p in phrasings(n)]
        rows = iter(embed(texts, "doc", timeout=timeout))
        for n in batch:
            store.put_embedding(n.id, MODEL_ID, phrasings_hash(n), _pack([next(rows) for _ in phrasings(n)]))
    gone = sorted(set(have) - {n.id for n in live})
    for node_id in gone:
        store.delete_embedding(node_id, MODEL_ID)
    return {"model": MODEL_ID, "embedded": len(todo), "unchanged": len(live) - len(todo), "removed": len(gone)}


# -- the server side --------------------------------------------------------------------------

def load_model() -> Callable[[list[str], str], list[list[float]]]:
    """Load the int8 model from okl's cache (downloading it once) and return an encoder."""
    try:
        from fastembed import TextEmbedding
        from fastembed.common.model_description import DenseModelDescription
        from fastembed.text import builtin_sentence_embedding as builtin
    except ImportError:
        raise WarmUnavailableError(f"the warm model needs its extra: pip install '{EXTRA}'") from None
    known = builtin.supported_builtin_sentence_embedding_models
    if not any(m.model == MODEL_ID for m in known):
        base = next(m for m in known if m.model == BASE_MODEL)
        known.append(DenseModelDescription(
            model=MODEL_ID, dim=base.dim, description=f"{base.description} int8.", license=base.license,
            size_in_GB=0.31, sources=base.sources, model_file="onnx/model_quantized.onnx",
            additional_files=["onnx/model_quantized.onnx_data"]))
    model = TextEmbedding(model_name=MODEL_ID, cache_dir=str(hub.model_cache_dir()))

    def encode(texts: list[str], kind: str) -> list[list[float]]:
        template = QUERY if kind == "query" else DOC
        out = []
        for v in model.embed([template.format(t) for t in texts], batch_size=32):
            norm = sum(x * x for x in v) ** 0.5 or 1.0
            out.append([float(x) / norm for x in v])
        return out
    return encode


def _take_lock(path: Path) -> Any:
    """The one-server lock next to the socket, taken without waiting: the open lock file while
    this process holds it, None while another server does. A server still loading answers no
    ping, so without it every prompt in that second started another (review on #300). Where
    flock does not exist, nothing is locked."""
    if fcntl is None:
        return contextlib.nullcontext()
    lock = path.with_suffix(".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    f = lock.open("a")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    return f


def serve(path: Path | None = None, *, idle_exit_s: float = IDLE_EXIT_S) -> int:
    """Load the model, then answer requests on the socket until stopped or idle for
    `idle_exit_s`. One request per connection: ping, embed or stop. A second server exits at
    once while one holds the lock."""
    path = path or socket_path()
    lock = None
    for _ in range(20):   # a start's probe holds the lock for an instant; wait it out (review on #300)
        lock = _take_lock(path)
        if lock is not None:
            break
        time.sleep(0.05)
    if lock is None:
        sys.stderr.write("okl warm: another server holds the lock; this one exits\n")
        return 0
    with lock:
        return _serve(path, idle_exit_s)


def _serve(path: Path, idle_exit_s: float) -> int:
    started = time.perf_counter()
    encode = load_model()
    # The first inference allocates the runtime's working memory, about 1.1 GB once (§4z), and
    # took over TIMEOUT_S, so the first prompt after a start always fell back. Pay it here,
    # before the socket exists, so no prompt waits for it.
    encode(["warm up"], "query")
    if stopped():
        # `okl warm stop` while this was loading found no socket to ask (review on #300).
        sys.stderr.write("okl warm: stopped with `okl warm stop` while loading; exiting\n")
        return 0
    state: dict[str, Any] = {"loaded_s": round(time.perf_counter() - started, 2), "served": 0}
    path.parent.mkdir(parents=True, exist_ok=True)
    with contextlib.suppress(FileNotFoundError):
        path.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(path))
    path.chmod(0o600)   # this user's prompts only
    srv.listen(8)
    srv.settimeout(60)
    last = time.monotonic()
    try:
        # A stop asked while this was busy can time out before its answer, so the record
        # `okl warm stop` leaves is read here too (review on #300).
        while time.monotonic() - last < idle_exit_s and not stopped():
            try:
                conn, _ = srv.accept()
            except TimeoutError:
                continue
            last = time.monotonic()
            with conn:
                try:
                    if _handle(conn, encode, state) == "stop":
                        break
                except Exception as e:  # noqa: BLE001 - one vanished or broken client must not end the server
                    # A prompt gives up after TIMEOUT_S and closes its end, so a late answer
                    # meets a broken pipe; that ended the server (review on #300).
                    sys.stderr.write(f"okl warm: a request failed: {e!r}\n")
    finally:
        srv.close()
        with contextlib.suppress(FileNotFoundError):
            path.unlink()
    return 0


def _handle(conn: socket.socket, encode: Encoder, state: dict[str, Any]) -> str | None:
    """Answer one connection; return "stop" when asked to. `state` holds the load time and how
    many embed requests were answered, which ping reports: answered, not necessarily received,
    since a check that gave up has closed its end (review on #300)."""
    conn.settimeout(30)
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = conn.recv(1 << 16)
        if not chunk:
            break
        buf += chunk
    try:
        req = json.loads(buf)
        op = req.get("op")
        if op == "ping":
            reply: dict[str, Any] = {"ok": True, "model": MODEL_ID, "pid": os.getpid(), **state}
        elif op == "embed" and req.get("kind") in ("query", "doc") and isinstance(req.get("texts"), list):
            vectors = encode([str(t) for t in req["texts"]], req["kind"])
            reply = {"ok": True, "dim": DIM, "vectors": base64.b64encode(_pack(vectors)).decode()}
            state["served"] += 1
        elif op == "stop":
            reply = {"ok": True}
        else:
            reply = {"ok": False, "error": f"unknown request {op!r}"}
    except (AttributeError, TypeError, ValueError) as e:   # a JSONDecodeError is a ValueError
        reply, op = {"ok": False, "error": f"bad request: {e}"}, None
    conn.sendall(json.dumps(reply).encode() + b"\n")
    return "stop" if op == "stop" else None


def installed() -> bool:
    """Whether this environment can load the model at all (the warm extra is installed)."""
    return importlib.util.find_spec("fastembed") is not None


def log_path() -> Path:
    """Where the server writes what it says, including why it failed to load."""
    return socket_path().with_suffix(".log")


def _stopped_path() -> Path:
    return socket_path().with_suffix(".stopped")


def _started_path() -> Path:
    return socket_path().with_suffix(".started")


def stopped() -> bool:
    """Whether the person stopped the server with `okl warm stop` and has not started it since:
    the default then leaves it off (review on #300: the next prompt started it again)."""
    return _stopped_path().exists()


def resume() -> None:
    """Undo `okl warm stop`: what the person's own start, index or serve does first. The
    default's start for a prompt never does (review on #300)."""
    _stopped_path().unlink(missing_ok=True)


def start(*, wait_s: float = 0.0) -> dict[str, Any] | None:
    """Start the server in the background unless one answers; with `wait_s`, wait that long
    for it to load. Returns its ping, or None while it is still loading."""
    running = ping()
    if running:
        return running
    if not installed():
        raise WarmUnavailableError(f"the warm model needs its extra: pip install '{EXTRA}'")
    probe = _take_lock(socket_path())
    if probe is None:
        return _wait(wait_s)   # one is loading already: do not start another
    with probe:   # released at once, for the server to take; the fallback has no close() (review on #300)
        pass
    log = log_path()
    log.parent.mkdir(parents=True, exist_ok=True)
    _started_path().touch()
    with log.open("ab") as out:
        subprocess.Popen([sys.executable, "-m", "okl", "warm", "serve"], stdin=subprocess.DEVNULL,
                         stdout=out, stderr=subprocess.STDOUT, start_new_session=True, close_fds=True)
    return _wait(wait_s)


def _wait(wait_s: float) -> dict[str, Any] | None:
    """Ping until the server answers or `wait_s` passes."""
    deadline = time.monotonic() + wait_s
    while time.monotonic() < deadline:
        time.sleep(0.25)
        running = ping()
        if running:
            return running
    return None


def revive() -> str:
    """For a prompt that found no server: start one for the next prompt, unless one is loading or
    the last start, under RESTART_AFTER_S ago, did not come up. Returns what it found: "started",
    "loading" (the lock is held, or the start is under STARTING_S old) or "failed". Raises what
    start() raises (review on #300: a server that crashed while loading was started again on
    every prompt)."""
    probe = _take_lock(socket_path())
    if probe is None:
        return "loading"
    with probe:
        pass
    try:
        since = time.time() - _started_path().stat().st_mtime
    except OSError:
        since = None
    if since is not None and since < STARTING_S:
        return "loading"
    if since is not None and since < RESTART_AFTER_S:
        return "failed"
    start()
    return "started"


def stop() -> bool:
    """Ask a running server to exit, and keep the default from starting it again until `okl warm
    start` (review on #300). False when none answered."""
    _stopped_path().parent.mkdir(parents=True, exist_ok=True)
    _stopped_path().touch()
    try:
        _ask({"op": "stop"}, TIMEOUT_S)
    except WarmUnavailableError:
        return False
    return True
