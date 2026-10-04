"""okl — the Observed Knowledge Ledger.

Install into any repo; read lessons curated by your other repos; contribute back.
Design rationale: README.md ("Where this sits") and docs/posts/.
"""
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _version

from . import core
from .client import Client, OKLNotConfiguredError, OKLRejectedError, OKLUnreachable
from .store import EDGE_RELS, NODE_TYPES, Edge, Node, Store

try:
    # The installed distribution's version, so this cannot drift from pyproject.toml
    # again (it said 0.1.0 through 0.7.8). A source tree with no install says so.
    __version__ = _version("observed-knowledge-ledger")
except PackageNotFoundError:
    __version__ = "unknown"

__all__ = ["Store", "Node", "Edge", "Client", "OKLUnreachable", "OKLNotConfiguredError",
           "OKLRejectedError", "core",
           "NODE_TYPES", "EDGE_RELS", "__version__"]
