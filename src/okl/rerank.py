"""A local cross-encoder over the fused candidates: the second stage of retrieval (#258, REPORT §4t).

Off unless asked for. The first stage, full text fused with the embedding's nearest records,
orders candidates by what they share with the task; a cross-encoder reads each (task, record)
pair together and scores whether the record answers it, which is a different and sharper
question. The model (`Xenova/ms-marco-MiniLM-L-6-v2`, an ONNX cross-encoder of 92 MB (model-files-20261029-1207.txt),
installed with the `rerank` extra, downloaded once by `okl embed`, kept under `okl.hub.model_cache_dir()`, not the temp directory fastembed
would use) scores the first RERANK_POOL candidates against a short text per record (title, symptom, aliases; the cause
paragraph slows the model five-fold and buys nothing, measured in §4t's spike) and reorders
them; the tail keeps its order. At check time the model loads from the local cache only, so a
hook never reaches the network, and when the extra or the model is missing the first-stage
order stands and the result says why. The absolute score is not a relevance line: on the same
records the governing lesson scored between -11 and +8 while chat filler peaked at -4, so the
reranker orders and the relevance floor still decides (§4t).
"""
from __future__ import annotations

from typing import Any

from . import hub
from .store import Node

MODEL_ID = "Xenova/ms-marco-MiniLM-L-6-v2"
EXTRA = "observed-knowledge-ledger[rerank]"
RERANK_POOL = 24   # pairs scored per check: the fused top 24, about 0.6 s on a laptop CPU

_LOADED: dict[str, Any] = {}


class RerankUnavailableError(RuntimeError):
    """The reranker cannot run here: no extra or no cached model."""


def pair_text(n: Node) -> str:
    """What the cross-encoder reads for a record: its subject, not its cause paragraph."""
    return ". ".join(x for x in (n.title, n.symptom, n.aliases) if x)


def load_model(model_id: str = MODEL_ID, *, offline: bool = True) -> Any:
    """The cross-encoder, loaded once per process, or RerankUnavailableError with the remedy.

    `offline` is the check-time rule: the model comes from the local cache or not at all;
    `okl embed` passes offline=False to fetch it once. The cache check and the load happen
    under the process's one model-loading lock (`okl.hub`), which owns the offline switch.
    """
    with hub.loading(offline=offline):
        if model_id in _LOADED:
            return _LOADED[model_id]
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        except ImportError as e:
            raise RerankUnavailableError(f"the rerank extra is not installed: pip install '{EXTRA}'") from e
        try:
            _LOADED[model_id] = TextCrossEncoder(model_name=model_id, cache_dir=str(hub.model_cache_dir()))
        except (OSError, ValueError, RuntimeError) as e:
            raise RerankUnavailableError(
                f"the reranker {model_id} is not cached locally ({type(e).__name__}); run `okl embed` once online"
            ) from e
        return _LOADED[model_id]


def rerank(task: str, nodes: list[Node], model_id: str = MODEL_ID,
           pool: int = RERANK_POOL) -> tuple[list[Node], dict[str, float]]:
    """The candidates with their first `pool` reordered by the cross-encoder's score for
    (task, record), best first, and the scores by id; the rest keep their order."""
    head, tail = nodes[:pool], nodes[pool:]
    if not head:
        return nodes, {}
    model = load_model(model_id, offline=True)
    scores = [float(s) for s in model.rerank(task, [pair_text(n) for n in head])]
    order = sorted(zip(head, scores, strict=True), key=lambda p: -p[1])
    return [n for n, _ in order] + tail, {n.id: s for n, s in order}
