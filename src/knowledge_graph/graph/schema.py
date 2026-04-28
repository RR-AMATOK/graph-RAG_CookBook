"""Schema bootstrap — node / edge labels, indices, uniqueness constraints.

Called once at the start of an ingest run. Operations are idempotent; running
the function repeatedly is safe.
"""

from __future__ import annotations

from knowledge_graph.graph.client import GraphClient

# Indexes accelerate the MERGE-on-id pattern that the builder relies on.
_INDEX_STATEMENTS: list[str] = [
    "CREATE INDEX FOR (d:Document) ON (d.doc_id)",
    "CREATE INDEX FOR (e:Entity) ON (e.entity_id)",
    "CREATE INDEX FOR (e:Entity) ON (e.type)",
]


def ensure_schema(client: GraphClient) -> None:
    """Create indices for Document.doc_id and Entity.entity_id (idempotent)."""
    for statement in _INDEX_STATEMENTS:
        try:
            client.query(statement)
        except Exception:
            # Index already exists — FalkorDB raises rather than no-oping.
            # The builder will fail loudly later if anything else is wrong.
            continue
