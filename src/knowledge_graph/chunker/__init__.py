"""Header-aware markdown chunker. (SPEC §6.2, FR-3.1)

Public API:
- :func:`chunk_document` — split a single canonical document into chunks.
- :func:`Chunk` — dataclass returned per chunk; carries a deterministic id.

The token estimator is intentionally offline and conservative — see
:mod:`knowledge_graph.chunker.tokens`.
"""

from knowledge_graph.chunker.chunker import (
    Chunk,
    ChunkerSettings,
    chunk_document,
)
from knowledge_graph.chunker.tokens import estimate_tokens

__all__ = [
    "Chunk",
    "ChunkerSettings",
    "chunk_document",
    "estimate_tokens",
]
