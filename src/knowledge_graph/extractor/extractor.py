"""Anthropic-backed extractor — synchronous, cache-first, retry-aware.

The extractor is intentionally a thin wrapper:

- Build the messages payload (system prompt with prompt-cache control, user
  message containing the chunk).
- Call the API forcing the ``record_extractions`` tool.
- Parse + Pydantic-validate the response.
- Dedupe entities within the chunk (FR-3.4).
- Track per-call usage (input/output tokens, cache hits, USD cost).

Tests cover this module by mocking the Anthropic client; the live API is
exercised by ``kg ingest`` with the user's ``ANTHROPIC_API_KEY``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError
from tenacity import (
    RetryError,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from knowledge_graph.chunker import Chunk
from knowledge_graph.extractor.cache import ExtractionCache, cache_key
from knowledge_graph.extractor.dedup import dedupe_within_doc
from knowledge_graph.extractor.prompts import PROMPT_VERSION, load_system_prompt
from knowledge_graph.extractor.schemas import (
    Extraction,
    record_extractions_tool,
)

if TYPE_CHECKING:
    from anthropic import Anthropic

logger = logging.getLogger(__name__)

# Per-million-token USD prices for Claude Sonnet 4.7 (as of 2026-04).
# Update when prices change; cost figures in run reports lean on these.
_PRICE_PER_M_INPUT_USD = 3.00
_PRICE_PER_M_OUTPUT_USD = 15.00
_PRICE_PER_M_CACHE_READ_USD = 0.30


class ExtractorError(Exception):
    """Raised when the extractor cannot produce a valid extraction."""


@dataclass
class ExtractorSettings:
    model: str = "claude-sonnet-4-7"
    max_output_tokens: int = 4096
    cache_root: Path | None = None
    prompt_version: str = PROMPT_VERSION
    api_key: str | None = None  # falls back to ANTHROPIC_API_KEY env var
    max_retries: int = 4


@dataclass
class CallUsage:
    """Per-call usage. Aggregated across a run for cost reporting."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cached_extraction_used: bool = False

    @property
    def cost_usd(self) -> float:
        """Conservative cost estimate using public Claude Sonnet pricing."""
        return (
            self.input_tokens / 1_000_000 * _PRICE_PER_M_INPUT_USD
            + self.output_tokens / 1_000_000 * _PRICE_PER_M_OUTPUT_USD
            + self.cache_read_tokens / 1_000_000 * _PRICE_PER_M_CACHE_READ_USD
        )


@dataclass
class ExtractionResult:
    chunk_id: str
    extraction: Extraction
    usage: CallUsage
    prompt_version: str
    cached: bool = False  # whether the result came from the local cache (no API call)


@dataclass
class Extractor:
    """Stateful extractor wrapping an :class:`Anthropic` client.

    Construction is lazy in two senses:
    1. The Anthropic client is only created on first ``extract`` call (so
       tests using ``inject_client`` never need credentials).
    2. The cache directory is created in ``ExtractionCache``'s ``__post_init__``
       only when ``cache_root`` is set.
    """

    settings: ExtractorSettings = field(default_factory=ExtractorSettings)
    _client: Anthropic | None = None
    _cache: ExtractionCache | None = None

    def __post_init__(self) -> None:
        if self.settings.cache_root is not None:
            self._cache = ExtractionCache(cache_root=self.settings.cache_root)

    def inject_client(self, client: Anthropic) -> None:
        """Test seam — replace the Anthropic client with a stub."""
        self._client = client

    def _get_client(self) -> Anthropic:
        if self._client is not None:
            return self._client
        from anthropic import Anthropic

        api_key = self.settings.api_key or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ExtractorError("ANTHROPIC_API_KEY not set; export it or pass settings.api_key")
        self._client = Anthropic(api_key=api_key)
        return self._client

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

        result = self._call_api(chunk)
        if self._cache is not None:
            self._cache.put(
                key,
                {
                    "extraction": result.extraction.model_dump(mode="json"),
                    "prompt_version": result.prompt_version,
                    "usage": {
                        "input_tokens": result.usage.input_tokens,
                        "output_tokens": result.usage.output_tokens,
                    },
                },
            )
        return result

    def _call_api(self, chunk: Chunk) -> ExtractionResult:
        @retry(
            reraise=True,
            stop=stop_after_attempt(self.settings.max_retries),
            wait=wait_exponential(multiplier=1, min=1, max=20),
            retry=retry_if_exception_type(_RetriableExtractorError),
        )
        def _do() -> ExtractionResult:
            client = self._get_client()
            # The SDK's typed overload doesn't yet model `cache_control` inside
            # a system TextBlock as part of an `Iterable[TextBlockParam]`, so
            # we suppress the call-overload check; the runtime payload matches
            # the public Anthropic prompt-caching docs.
            response = client.messages.create(  # type: ignore[call-overload]
                model=self.settings.model,
                max_tokens=self.settings.max_output_tokens,
                system=[
                    {
                        "type": "text",
                        "text": load_system_prompt(self.settings.prompt_version),
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=[record_extractions_tool()],
                tool_choice={"type": "tool", "name": "record_extractions"},
                messages=[
                    {
                        "role": "user",
                        "content": _user_message(chunk),
                    }
                ],
            )
            return _parse_response(response, chunk, self.settings.prompt_version)

        try:
            return _do()
        except _RetriableExtractorError as exc:
            raise ExtractorError(f"extractor retries exhausted: {exc}") from exc
        except RetryError as exc:  # pragma: no cover — tenacity edge case
            raise ExtractorError(f"extractor retries exhausted: {exc}") from exc


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


class _RetriableExtractorError(Exception):
    """Marker for transient API errors that should trigger a retry."""


def _user_message(chunk: Chunk) -> list[dict[str, Any]]:
    """Build the user-message content for one chunk."""
    heading_hint = f"\nSection heading: {chunk.heading}" if chunk.heading else ""
    return [
        {
            "type": "text",
            "text": (
                f"Document canonical_path: {chunk.canonical_path}\n"
                f"chunk_id: {chunk.chunk_id}{heading_hint}\n\n"
                "<chunk>\n"
                f"{chunk.text}\n"
                "</chunk>\n"
            ),
        }
    ]


def _parse_response(response: Any, chunk: Chunk, prompt_version: str) -> ExtractionResult:
    tool_block = next(
        (block for block in response.content if getattr(block, "type", None) == "tool_use"),
        None,
    )
    if tool_block is None or getattr(tool_block, "name", None) != "record_extractions":
        raise _RetriableExtractorError(
            f"chunk {chunk.chunk_id}: model did not call record_extractions"
        )

    raw_input = getattr(tool_block, "input", {}) or {}
    try:
        extraction = _parse_payload(raw_input)
    except ValidationError as exc:
        raise _RetriableExtractorError(
            f"chunk {chunk.chunk_id}: extraction failed validation: {exc}"
        ) from exc

    extraction = Extraction(
        entities=dedupe_within_doc(extraction.entities),
        relationships=extraction.relationships,
    )

    raw_usage = getattr(response, "usage", None)
    usage = CallUsage(
        input_tokens=getattr(raw_usage, "input_tokens", 0) or 0,
        output_tokens=getattr(raw_usage, "output_tokens", 0) or 0,
        cache_read_tokens=getattr(raw_usage, "cache_read_input_tokens", 0) or 0,
        cache_creation_tokens=getattr(raw_usage, "cache_creation_input_tokens", 0) or 0,
    )

    return ExtractionResult(
        chunk_id=chunk.chunk_id,
        extraction=extraction,
        usage=usage,
        prompt_version=prompt_version,
        cached=False,
    )


def _parse_payload(payload: dict[str, Any]) -> Extraction:
    return Extraction.model_validate(payload)


def extract_chunk(chunk: Chunk, *, settings: ExtractorSettings | None = None) -> ExtractionResult:
    """Convenience function for one-off extractions (mostly for tests)."""
    return Extractor(settings or ExtractorSettings()).extract(chunk)
