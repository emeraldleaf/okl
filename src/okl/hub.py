"""The local model cache's two rules, shared by every loader (the embedder, the reranker).

Both models come from the Hugging Face cache through libraries that read one process-wide
switch, HF_HUB_OFFLINE, while they load. A briefing must never wait on the network, so a
check-time load sets the switch and restores it after; `okl embed` loads with it off, once,
to fetch. Two loaders doing that at the same time on a service's thread pool would race:
one could restore the other's value, leaving the process offline (or online) for good. So
every cache check and load happens inside `loading`, which holds one lock for the process
and owns the switch (review on #271). The tokenizer's thread pool is also turned off here:
it warns, loudly, in any process that forks after encoding, and nothing is lost on one short
task text or two dozen pairs.
"""
from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

_LOCK = threading.Lock()


def model_cache_dir() -> Path:
    """Where okl keeps the models it fetches itself (today the reranker's ONNX files).

    fastembed's default is the system temp directory, which macOS prunes on its own schedule,
    so a model that loaded offline one day is "not cached" the next and the check-time load
    fails. okl passes an explicit directory under the user's cache home instead:
    FASTEMBED_CACHE_PATH when set (fastembed's own override, kept for people who manage that
    cache), else $XDG_CACHE_HOME/okl/models, else ~/.cache/okl/models. The embedder is not
    affected: model2vec reads the Hugging Face hub cache, which already lives under ~/.cache.
    """
    override = os.environ.get("FASTEMBED_CACHE_PATH")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CACHE_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".cache"
    return root / "okl" / "models"


@contextmanager
def loading(*, offline: bool) -> Iterator[None]:
    """Hold the process's one model-loading lock, with HF_HUB_OFFLINE set when `offline`
    and restored to what it was on the way out."""
    with _LOCK:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        prior = os.environ.get("HF_HUB_OFFLINE")
        if offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
        try:
            yield
        finally:
            if offline:
                if prior is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = prior
