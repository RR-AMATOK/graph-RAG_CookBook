"""Graph DB layer — FalkorDB client (DEC-002), schema bootstrap, ingest builder.

Public API:
- :class:`GraphClient` — thin connection wrapper.
- :class:`GraphBuilder` — orchestrates Document/Entity/Edge writes per chunk.
- :func:`ensure_schema` — create indices and constraints (idempotent).

(SPEC §6.2, FR-4)
"""

from knowledge_graph.graph.builder import (
    BuilderStats,
    GraphBuilder,
)
from knowledge_graph.graph.client import GraphClient, GraphClientError
from knowledge_graph.graph.ids import edge_id, entity_id
from knowledge_graph.graph.schema import ensure_schema

__all__ = [
    "BuilderStats",
    "GraphBuilder",
    "GraphClient",
    "GraphClientError",
    "edge_id",
    "ensure_schema",
    "entity_id",
]
