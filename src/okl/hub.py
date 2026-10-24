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

_LOCK = threading.Lock()


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
