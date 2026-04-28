"""Extractor — LLM calls for entity + relationship extraction.

Public API:
- :func:`extract_chunk` — one-chunk extraction (sync).
- :class:`Extractor` — stateful client wrapper with caching, retries, and cost tracking.
- :class:`ExtractedEntity`, :class:`ExtractedRelationship`, :class:`Extraction` — output types.
- :class:`LLMBackend`, :func:`make_backend` — pluggable backend protocol.

The extractor itself is provider-agnostic; an :class:`LLMBackend` (Anthropic,
OpenAI-compatible, or test mock) handles the actual API call.

(SPEC §6.2, FR-3.2..3.5)
"""

from knowledge_graph.extractor.backends import (
    BackendError,
    BackendResponse,
    LLMBackend,
    make_backend,
)
from knowledge_graph.extractor.cache import ExtractionCache
from knowledge_graph.extractor.extractor import (
    Extractor,
    ExtractorSettings,
    extract_chunk,
)
from knowledge_graph.extractor.prompts import (
    PROMPT_VERSION,
    load_system_prompt,
)
from knowledge_graph.extractor.schemas import (
    ENTITY_TYPES,
    PROVENANCE_TAGS,
    ExtractedEntity,
    ExtractedRelationship,
    Extraction,
    record_extractions_tool,
)

__all__ = [
    "ENTITY_TYPES",
    "PROMPT_VERSION",
    "PROVENANCE_TAGS",
    "BackendError",
    "BackendResponse",
    "ExtractedEntity",
    "ExtractedRelationship",
    "Extraction",
    "ExtractionCache",
    "Extractor",
    "ExtractorSettings",
    "LLMBackend",
    "extract_chunk",
    "load_system_prompt",
    "make_backend",
    "record_extractions_tool",
]
