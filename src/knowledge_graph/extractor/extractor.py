"""Backend-agnostic extractor.

The extractor owns:
- the cache lookup/store cycle (FR-3.5)
- Pydantic validation of tool input
- within-doc dedup (FR-3.4)
- retry/backoff for transient backend failures
- usage + cost aggregation reported up to the pipeline

Provider-specific concerns (API shape, prompt caching, pricing) live inside
the :class:`~knowledge_graph.extractor.backends.LLMBackend` implementation
selected at construction time.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import ValidationError
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from knowledge_graph.chunker import Chunk
from knowledge_graph.extractor.backends import BackendError, LLMBackend, make_backend
from knowledge_graph.extractor.cache import ExtractionCache, cache_key
from knowledge_graph.extractor.dedup import dedupe_within_doc
from knowledge_graph.extractor.prompts import PROMPT_VERSION, load_system_prompt
from knowledge_graph.extractor.schemas import (
    Extraction,
    record_extractions_tool,
)

logger = logging.getLogger(__name__)


class ExtractorError(Exception):
    """Raised when the extractor cannot produce a valid extraction."""


@dataclass
class ExtractorSettings:
    """Settings for the extractor and the underlying backend.

    Backend selection is by ``backend`` name. Per-backend fields
    (``base_url``, ``api_key``, ``api_key_env``) are only used by some
    backends — leave at their defaults when not relevant.
    """

    backend: str = "anthropic"
    model: str = "claude-sonnet-4-7"
    max_output_tokens: int = 4096
    cache_root: Path | None = None
    prompt_version: str = PROMPT_VERSION
    api_key: str | None = None
    api_key_env: str | None = None
    base_url: str | None = None
    max_retries: int = 4


@dataclass
class CallUsage:
    """Per-call usage. Aggregated across a run for cost reporting."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0
    cached_extraction_used: bool = False


@dataclass
class ExtractionResult:
    chunk_id: str
    extraction: Extraction
    usage: CallUsage
    prompt_version: str
    cached: bool = False  # whether the result came from the local cache (no API call)


@dataclass
class Extractor:
    """Orchestrates one chunk → one extraction with caching and retries."""

    settings: ExtractorSettings = field(default_factory=ExtractorSettings)
    _backend: LLMBackend | None = None
    _cache: ExtractionCache | None = None

    def __post_init__(self) -> None:
        if self.settings.cache_root is not None:
            self._cache = ExtractionCache(cache_root=self.settings.cache_root)

    def inject_backend(self, backend: LLMBackend) -> None:
        """Test seam — replace the LLM backend with a stub or pre-built instance."""
        self._backend = backend

    def _get_backend(self) -> LLMBackend:
        if self._backend is not None:
            return self._backend
        self._backend = make_backend(self.settings.backend, self.settings)
        return self._backend

    def extract(self, chunk: Chunk) -> ExtractionResult:
        """Extract entities + relationships from a single chunk."""
        key = cache_key(self.settings.prompt_version, chunk.text)
        if self._cache is not None:
            cached_payload = self._cache.get(key)
            if cached_payload is not None:
                try:
                    extraction = _parse_payload(cached_payload["extraction"])
                except (KeyError, ValidationError) as exc:
                    logger.warning("cache entry %s invalid: %s — refetching", key, exc)
                else:
                    usage = CallUsage(cached_extraction_used=True)
                    return ExtractionResult(
                        chunk_id=chunk.chunk_id,
                        extraction=extraction,
                        usage=usage,
                        prompt_version=self.settings.prompt_version,
                        cached=True,
                    )

        result = self._call_backend(chunk)
        if self._cache is not None:
            self._cache.put(
                key,
                {
                    "extraction": result.extraction.model_dump(mode="json"),
                    "prompt_version": result.prompt_version,
                    "usage": {
                        "input_tokens": result.usage.input_tokens,
                        "output_tokens": result.usage.output_tokens,
                        "cost_usd": result.usage.cost_usd,
                    },
                },
            )
        return result

    def _call_backend(self, chunk: Chunk) -> ExtractionResult:
        @retry(
            reraise=True,
            stop=stop_after_attempt(self.settings.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_exception_type((BackendError, _RetriableExtractorError)),
        )
        def _do() -> ExtractionResult:
            backend = self._get_backend()
            response = backend.call(
                system_prompt=load_system_prompt(self.settings.prompt_version),
                user_message=_user_message(chunk),
                tool=record_extractions_tool(),
                max_tokens=self.settings.max_output_tokens,
            )

            try:
                extraction = _parse_payload(response.tool_input)
            except ValidationError as exc:
                raise _RetriableExtractorError(
                    f"chunk {chunk.chunk_id}: extraction failed validation: {exc}"
                ) from exc

            # Dedup may merge near-duplicate entity names within the same
            # type (e.g., "Season 5" + "Season 5 finale" at threshold 90).
            # Rewrite relationship endpoints through the rename map so the
            # post-dedup Extraction stays self-consistent — without this,
            # relationships pointing at merged-away surface forms fail the
            # endpoints-resolve validator.
            deduped_entities, rename_map = dedupe_within_doc(extraction.entities)
            remapped_relationships = [
                rel.model_copy(
                    update={
                        "source": rename_map.get(rel.source, rel.source),
                        "target": rename_map.get(rel.target, rel.target),
                    }
                )
                for rel in extraction.relationships
            ]
            try:
                extraction = Extraction(
                    entities=deduped_entities, relationships=remapped_relationships
                )
            except ValidationError as exc:
                raise _RetriableExtractorError(
                    f"chunk {chunk.chunk_id}: post-dedup validation failed: {exc}"
                ) from exc
            usage = CallUsage(
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                cache_read_tokens=response.cache_read_tokens,
                cache_creation_tokens=response.cache_creation_tokens,
                cost_usd=response.cost_usd,
            )
            return ExtractionResult(
                chunk_id=chunk.chunk_id,
                extraction=extraction,
                usage=usage,
                prompt_version=self.settings.prompt_version,
                cached=False,
            )

        try:
            return _do()
        except (_RetriableExtractorError, BackendError) as exc:
            raise ExtractorError(f"extractor retries exhausted: {exc}") from exc
        except RetryError as exc:  # pragma: no cover — tenacity edge case
            raise ExtractorError(f"extractor retries exhausted: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


class _RetriableExtractorError(Exception):
    """Marker for transient validation errors that should trigger a retry."""


def _user_message(chunk: Chunk) -> str:
    """Build the user-message text for one chunk."""
    heading_hint = f"\nSection heading: {chunk.heading}" if chunk.heading else ""
    return (
        f"Document canonical_path: {chunk.canonical_path}\n"
        f"chunk_id: {chunk.chunk_id}{heading_hint}\n\n"
        "<chunk>\n"
        f"{chunk.text}\n"
        "</chunk>\n"
    )


def _parse_payload(payload: object) -> Extraction:
    return Extraction.model_validate(payload)


def extract_chunk(chunk: Chunk, *, settings: ExtractorSettings | None = None) -> ExtractionResult:
    """Convenience function for one-off extractions (mostly for tests)."""
    return Extractor(settings or ExtractorSettings()).extract(chunk)
