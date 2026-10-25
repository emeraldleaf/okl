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
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

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


def _set_hub_offline(value: bool) -> None:
    """huggingface_hub reads HF_HUB_OFFLINE once, when it is first imported, into a constant
    its downloads consult from then on. In a process whose first load was online (`okl embed`
    fetching the reranker), the variable alone left every later check-time load going to the
    network first: twelve connection attempts before the cache answered, and a stalled test
    suite when the network was slow. So the constant is set beside the variable whenever the
    module is loaded."""
    constants: Any = sys.modules.get("huggingface_hub.constants")   # a third-party module
    if constants is not None:
        constants.HF_HUB_OFFLINE = value


@contextmanager
def loading(*, offline: bool) -> Iterator[None]:
    """Hold the process's one model-loading lock, with HF_HUB_OFFLINE set when `offline`
    and restored to what it was on the way out, in the environment and in huggingface_hub's
    own constant. After the block the constant reads what the restored variable says, as a
    fresh import would, even when the module was first imported inside the block."""
    with _LOCK:
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        prior = os.environ.get("HF_HUB_OFFLINE")
        # huggingface_hub's own reading: the first of the two variables that is set and not
        # empty, then any of its four true spellings, so HF_HUB_OFFLINE=0 outranks
        # TRANSFORMERS_OFFLINE=1 (review on #290).
        setting = os.environ.get("HF_HUB_OFFLINE") or os.environ.get("TRANSFORMERS_OFFLINE") or ""
        prior_offline = setting.upper() in {"1", "ON", "YES", "TRUE"}
        if offline:
            os.environ["HF_HUB_OFFLINE"] = "1"
        _set_hub_offline(offline or prior_offline)
        try:
            yield
        finally:
            if offline:
                if prior is None:
                    os.environ.pop("HF_HUB_OFFLINE", None)
                else:
                    os.environ["HF_HUB_OFFLINE"] = prior
            _set_hub_offline(prior_offline)
