"""okl — the Observed Knowledge Ledger.

Install into any repo; read lessons curated by your other repos; contribute back.
Design rationale: README.md ("Where this sits") and docs/posts/.
"""
from . import core
from .client import Client, OKLUnreachable
from .store import EDGE_RELS, NODE_TYPES, Edge, Node, Store

__version__ = "0.1.0"
__all__ = ["Store", "Node", "Edge", "Client", "OKLUnreachable", "core",
           "NODE_TYPES", "EDGE_RELS", "__version__"]
