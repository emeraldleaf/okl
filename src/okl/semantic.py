"""Semantic retrieval beside the full-text search: one local static embedding per record (#258).

Off unless asked for: `okl check --hybrid`, `"hybrid": "rrf"` in .okl/config.json, or
OKL_HYBRID. The model (`minishlab/potion-retrieval-32M`, a Model2Vec static embedding: 249 MB on
disk, 512 dimensions, well under a millisecond per text on a CPU) comes with the `hybrid`
extra and is downloaded once by `okl embed`, which also writes a vector per record into the
store. At check time the model is loaded from the local cache only, so the hook path never
reaches the network; when the model or the vectors are missing the briefing is the full-text
one and the result says why.

How it scales, measured on 2026-10-23 (REPORT §4q): the search is one matrix product over
every stored vector, in numpy when the extra is installed (numpy comes with the model):
under a millisecond for 10,000 records and 3 ms for 50,000, plus 14 ms and 49 ms to read
the vectors out of the store. The pure-Python fallback below exists for a process without
numpy (the test suite's stub model) and costs 5 ms at 300 records and 165 ms at 10,000; it
is not the path a hybrid install runs. Per process the model load is the fixed cost, 0.8 s
from the local cache, paid once per `okl check` because a hook is a new process each prompt.
Past roughly 100,000 vectors (a 200 MB matrix) the next tier is an approximate index on the
same table's data, sqlite-vec locally and pgvector on the shared service; that is the
retrieval ADR's next amendment, keyed on a store crossing that size or a search over 100 ms,
not something to build before a store exists that needs it.
"""
from __future__ import annotations

import hashlib
import os
import struct
from typing import Any

from .store import Node, Store

MODEL_ID = "minishlab/potion-retrieval-32M"
EXTRA = "observed-knowledge-ledger[hybrid]"
# A candidate whose cosine with the task reaches this is on the task's subject for the
# relevance floor, whatever words it shares. Chosen by the grid in REPORT §4q (receipt
# evals/results/hybrid-grid-20261023.txt): the static model's cosines run in a narrow band
# (true pairs 0.3 to 0.5, chat filler up to 0.42), and 0.40 is the line at which the six
# short real prompts gain at most one record each; 0.25, the first pass, admitted 31 records
# to one of them. Lower lines buy paraphrase recall at the cost of precision; see §4q.
SUBJECT_SIMILARITY = 0.40


class SemanticUnavailableError(RuntimeError):
    """The semantic arm cannot run here: no extra, no cached model, or no vectors."""


def record_text(n: Node) -> str:
    """The text a record is embedded from: what it is about, when it bites, what to do."""
    return ". ".join(x for x in (n.title, n.symptom, n.aliases, n.body, n.fix) if x)


def text_hash(text: str) -> str:
    """A short digest of the embedded text, so `okl embed` re-embeds only what changed."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def load_model(model_id: str = MODEL_ID, *, offline: bool = True) -> Any:
    """The embedding model, or SemanticUnavailableError with the reason and the remedy.

    `offline` is the check-time rule: a briefing must never wait on the network, so the
    model comes from the local cache or not at all. `okl embed` passes offline=False.
    """
    try:
        from model2vec import StaticModel
    except ImportError as e:
        raise SemanticUnavailableError(f"the hybrid extra is not installed: pip install '{EXTRA}'") from e
    prior = os.environ.get("HF_HUB_OFFLINE")
    if offline:
        os.environ["HF_HUB_OFFLINE"] = "1"
    try:
        return StaticModel.from_pretrained(model_id)
    except (OSError, ValueError, RuntimeError) as e:
        raise SemanticUnavailableError(
            f"the model {model_id} is not cached locally ({type(e).__name__}); run `okl embed` once online"
        ) from e
    finally:
        if offline:
            if prior is None:
                os.environ.pop("HF_HUB_OFFLINE", None)
            else:
                os.environ["HF_HUB_OFFLINE"] = prior


def encode(model: Any, texts: list[str]) -> list[list[float]]:
    """Unit-length vectors for `texts`, as plain lists so the rest of okl needs no numpy."""
    return [[float(x) for x in row] for row in model.encode(texts, normalize=True)]


def pack(vector: list[float]) -> bytes:
    """A vector as little-endian float32 bytes, the form the store keeps."""
    return struct.pack(f"<{len(vector)}f", *vector)


def unpack(blob: bytes) -> list[float]:
    """The vector a `pack` wrote."""
    return list(struct.unpack(f"<{len(blob) // 4}f", blob))


def build_index(store: Store, model_id: str = MODEL_ID, *, offline: bool = False) -> dict[str, Any]:
    """Embed every record whose text changed since it was last embedded; drop vectors of
    records that are gone. Returns the counts and the model, for `okl embed` to print."""
    model = load_model(model_id, offline=offline)
    have = {node_id: digest for node_id, digest, _ in store.embeddings(model_id)}
    nodes = store.all_nodes()
    todo = [n for n in nodes if have.get(n.id) != text_hash(record_text(n))]
    vectors = encode(model, [record_text(n) for n in todo]) if todo else []
    for n, v in zip(todo, vectors, strict=True):
        store.put_embedding(n.id, model_id, text_hash(record_text(n)), pack(v))
    gone = sorted(set(have) - {n.id for n in nodes})
    for node_id in gone:
        store.delete_embedding(node_id, model_id)
    return {"model": model_id, "dim": len(vectors[0]) if vectors else None,
            "embedded": len(todo), "unchanged": len(nodes) - len(todo), "removed": len(gone)}


def search(store: Store, text: str, limit: int, model_id: str = MODEL_ID) -> list[tuple[str, float]]:
    """The `limit` records nearest to `text` by cosine, best first, as (id, score).

    Raises SemanticUnavailableError when the model is not cached or no record has a vector, so
    the caller falls back to the full-text search and says so.
    """
    rows = store.embeddings(model_id)
    if not rows:
        raise SemanticUnavailableError("no record has a vector yet; run `okl embed`")
    model = load_model(model_id, offline=True)
    q = encode(model, [text])[0]
    try:
        import numpy as np
    except ImportError:
        # No numpy in this process (the test suite's stub model): the same product, slowly.
        scored = [(node_id, sum(a * b for a, b in zip(q, unpack(blob), strict=False)))
                  for node_id, _, blob in rows]
        scored.sort(key=lambda t: -t[1])
        return scored[:limit]
    # One matrix product over every vector: the cost that scales (see the module docstring).
    matrix = np.frombuffer(b"".join(blob for _, _, blob in rows), dtype="<f4").reshape(len(rows), -1)
    sims = matrix @ np.asarray(q, dtype=np.float32)
    k = min(limit, len(rows))
    top = np.argpartition(-sims, k - 1)[:k]
    top = top[np.argsort(-sims[top])]
    return [(rows[i][0], float(sims[i])) for i in top]
