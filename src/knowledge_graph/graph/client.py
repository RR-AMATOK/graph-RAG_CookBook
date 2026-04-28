"""Thin FalkorDB connection wrapper.

Tests substitute a stub for the underlying ``falkordb.Graph`` via
:meth:`GraphClient.inject_graph`; this module never speaks Redis directly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


class GraphClientError(Exception):
    """Raised when a FalkorDB query fails."""


@dataclass
class GraphClient:
    """Minimal wrapper around a ``falkordb.Graph`` handle.

    The wrapper centralizes query logging and lets tests inject a stub graph
    via :meth:`inject_graph`. Production code constructs the client with
    ``GraphClient.connect(...)``.
    """

    host: str = "localhost"
    port: int = 6390  # see DEC + MEMORY: avoids 6379 conflicts on dev hosts
    graph_name: str = "graph_rag"
    _graph: Any | None = None

    @classmethod
    def connect(
        cls, *, host: str = "localhost", port: int = 6390, graph_name: str = "graph_rag"
    ) -> GraphClient:
        from falkordb import FalkorDB

        client = cls(host=host, port=port, graph_name=graph_name)
        db = FalkorDB(host=host, port=port)
        client._graph = db.select_graph(graph_name)
        return client

    def inject_graph(self, graph: Any) -> None:
        """Test seam — replace the underlying ``falkordb.Graph`` handle."""
        self._graph = graph

    def query(self, cypher: str, params: dict[str, Any] | None = None) -> Any:
        """Run a parameterized Cypher query and return the raw result."""
        if self._graph is None:
            raise GraphClientError("graph not connected; call connect() or inject_graph()")
        try:
            return self._graph.query(cypher, params or {})
        except Exception as exc:
            raise GraphClientError(f"query failed: {exc}") from exc

    def reset(self) -> None:
        """Drop and recreate the graph. Destructive — used by integration tests only."""
        if self._graph is None:
            return
        try:
            self._graph.delete()
        except Exception:
            # Graph may not exist yet; ignore.
            logger.debug("reset: delete failed (graph may not exist)")
