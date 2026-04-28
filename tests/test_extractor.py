"""Extractor unit tests with a fake Anthropic client."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from knowledge_graph.chunker import Chunk
from knowledge_graph.extractor import (
    Extractor,
    ExtractorSettings,
)
from knowledge_graph.extractor.cache import ExtractionCache, cache_key
from knowledge_graph.extractor.dedup import dedupe_within_doc
from knowledge_graph.extractor.extractor import ExtractorError
from knowledge_graph.extractor.schemas import (
    ExtractedEntity,
    record_extractions_tool,
)

# ─────────────────────────────────────────────────────────────────────
# Fake Anthropic client for tests
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0


@dataclass
class _FakeContentBlock:
    type: str
    name: str | None = None
    input: dict[str, Any] | None = None


@dataclass
class _FakeResponse:
    content: list[_FakeContentBlock]
    usage: _FakeUsage


class _FakeMessages:
    def __init__(self, response_payload: dict[str, Any]) -> None:
        self.response_payload = response_payload
        self.calls = 0

    def create(self, **kwargs: Any) -> _FakeResponse:
        self.calls += 1
        return _FakeResponse(
            content=[
                _FakeContentBlock(
                    type="tool_use",
                    name="record_extractions",
                    input=self.response_payload,
                )
            ],
            usage=_FakeUsage(),
        )


class _FakeClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.messages = _FakeMessages(payload)


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────


def _make_chunk(text: str = "Sample chunk content.") -> Chunk:
    return Chunk(
        chunk_id="chk_test",
        doc_id="doc_test",
        canonical_path="corpus-a/test",
        offset=0,
        heading="Heading",
        text=text,
        token_estimate=10,
    )


_SAMPLE_PAYLOAD: dict[str, Any] = {
    "entities": [
        {"name": "Sheldon Cooper", "type": "Character", "aliases": [], "description": ""},
        {"name": "Caltech", "type": "Organization", "aliases": [], "description": ""},
    ],
    "relationships": [
        {
            "source": "Sheldon Cooper",
            "target": "Caltech",
            "predicate": "WORKS_AT",
            "evidence_span": "Sheldon works at Caltech",
            "confidence": 0.95,
            "provenance_tag": "EXTRACTED",
        }
    ],
}


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────


class TestRecordExtractionsTool:
    def test_tool_definition_shape(self) -> None:
        tool = record_extractions_tool()
        assert tool["name"] == "record_extractions"
        schema = tool["input_schema"]
        assert "entities" in schema["properties"]
        assert "relationships" in schema["properties"]
        ent_props = schema["properties"]["entities"]["items"]["properties"]
        assert set(ent_props.keys()) == {"name", "type", "aliases", "description"}


class TestExtractor:
    def test_extract_calls_api_and_parses(self) -> None:
        extractor = Extractor(ExtractorSettings(api_key="test"))
        extractor.inject_client(_FakeClient(_SAMPLE_PAYLOAD))  # type: ignore[arg-type]
        result = extractor.extract(_make_chunk())
        assert result.cached is False
        assert len(result.extraction.entities) == 2
        assert len(result.extraction.relationships) == 1
        assert result.usage.input_tokens == 100
        assert result.prompt_version == "v0"

    def test_cache_hit_skips_api(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        # Pre-populate cache
        cache = ExtractionCache(cache_root=cache_dir)
        chunk = _make_chunk()
        key = cache_key("v0", chunk.text)
        cache.put(key, {"extraction": _SAMPLE_PAYLOAD, "prompt_version": "v0"})

        # Build extractor with a fake client that, if called, would return
        # something obviously different so a cache miss would be visible.
        sentinel = {
            "entities": [{"name": "WRONG", "type": "Concept"}],
            "relationships": [],
        }
        extractor = Extractor(ExtractorSettings(api_key="test", cache_root=cache_dir))
        fake_client = _FakeClient(sentinel)
        extractor.inject_client(fake_client)  # type: ignore[arg-type]

        result = extractor.extract(chunk)
        assert result.cached is True
        assert result.extraction.entities[0].name == "Sheldon Cooper"
        assert fake_client.messages.calls == 0

    def test_cache_miss_then_populates(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        extractor = Extractor(ExtractorSettings(api_key="test", cache_root=cache_dir))
        extractor.inject_client(_FakeClient(_SAMPLE_PAYLOAD))  # type: ignore[arg-type]
        chunk = _make_chunk("First call content.")

        first = extractor.extract(chunk)
        assert first.cached is False

        # Second call should now hit the cache.
        sentinel_client = _FakeClient(
            {"entities": [{"name": "X", "type": "Concept"}], "relationships": []}
        )
        extractor.inject_client(sentinel_client)  # type: ignore[arg-type]
        second = extractor.extract(chunk)
        assert second.cached is True
        assert sentinel_client.messages.calls == 0
        assert second.extraction.entities[0].name == "Sheldon Cooper"

    def test_orphan_relationship_raises(self) -> None:
        bad_payload = {
            "entities": [{"name": "A", "type": "Concept"}],
            "relationships": [
                {
                    "source": "A",
                    "target": "MISSING",
                    "predicate": "X_Y",
                    "evidence_span": "...",
                    "confidence": 0.9,
                    "provenance_tag": "EXTRACTED",
                }
            ],
        }
        extractor = Extractor(ExtractorSettings(api_key="test", max_retries=1))
        extractor.inject_client(_FakeClient(bad_payload))  # type: ignore[arg-type]
        with pytest.raises(ExtractorError):
            extractor.extract(_make_chunk())


class TestDedup:
    def test_merges_fuzzy_matches_within_type(self) -> None:
        a = ExtractedEntity(name="Sheldon Cooper", type="Character")
        b = ExtractedEntity(name="Dr. Sheldon Cooper", type="Character", aliases=["Shelly"])
        out = dedupe_within_doc([a, b])
        assert len(out) == 1
        assert out[0].name == "Sheldon Cooper"
        assert "Shelly" in out[0].aliases
        assert "Dr. Sheldon Cooper" in out[0].aliases

    def test_keeps_distinct_types_separate(self) -> None:
        a = ExtractedEntity(name="Mercury", type="Concept")
        b = ExtractedEntity(name="Mercury", type="Location")
        out = dedupe_within_doc([a, b])
        assert len(out) == 2

    def test_empty(self) -> None:
        assert dedupe_within_doc([]) == []
