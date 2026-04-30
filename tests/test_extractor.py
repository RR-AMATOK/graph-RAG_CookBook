"""Extractor unit tests using the MockBackend."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from knowledge_graph.chunker import Chunk
from knowledge_graph.extractor import (
    Extractor,
    ExtractorSettings,
)
from knowledge_graph.extractor.backends import make_backend
from knowledge_graph.extractor.backends.mock import MockBackend
from knowledge_graph.extractor.cache import ExtractionCache, cache_key
from knowledge_graph.extractor.dedup import dedupe_within_doc
from knowledge_graph.extractor.extractor import ExtractorError
from knowledge_graph.extractor.prompts import PROMPT_VERSION
from knowledge_graph.extractor.schemas import (
    ExtractedEntity,
    record_extractions_tool,
)


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


def _extractor_with_mock(
    payload: dict[str, Any], **settings_kwargs: Any
) -> tuple[Extractor, MockBackend]:
    settings = ExtractorSettings(api_key="test", **settings_kwargs)
    extractor = Extractor(settings)
    mock = MockBackend()
    mock.set_response(payload)
    extractor.inject_backend(mock)
    return extractor, mock


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
    def test_extract_calls_backend_and_parses(self) -> None:
        extractor, mock = _extractor_with_mock(_SAMPLE_PAYLOAD)
        result = extractor.extract(_make_chunk())
        assert result.cached is False
        assert len(result.extraction.entities) == 2
        assert len(result.extraction.relationships) == 1
        assert result.usage.input_tokens == 10
        assert result.prompt_version == PROMPT_VERSION
        assert mock.calls == 1

    def test_cache_hit_skips_backend(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        cache = ExtractionCache(cache_root=cache_dir)
        chunk = _make_chunk()
        key = cache_key(PROMPT_VERSION, chunk.text)
        cache.put(key, {"extraction": _SAMPLE_PAYLOAD, "prompt_version": PROMPT_VERSION})

        sentinel = {
            "entities": [{"name": "WRONG", "type": "Concept"}],
            "relationships": [],
        }
        extractor, mock = _extractor_with_mock(sentinel, cache_root=cache_dir)
        result = extractor.extract(chunk)
        assert result.cached is True
        assert result.extraction.entities[0].name == "Sheldon Cooper"
        assert mock.calls == 0

    def test_cache_miss_then_populates(self, tmp_path: Path) -> None:
        cache_dir = tmp_path / "cache"
        extractor, _ = _extractor_with_mock(_SAMPLE_PAYLOAD, cache_root=cache_dir)
        chunk = _make_chunk("First call content.")

        first = extractor.extract(chunk)
        assert first.cached is False

        # Swap to a sentinel backend; cache should serve next call.
        sentinel_mock = MockBackend()
        sentinel_mock.set_response(
            {"entities": [{"name": "X", "type": "Concept"}], "relationships": []}
        )
        extractor.inject_backend(sentinel_mock)
        second = extractor.extract(chunk)
        assert second.cached is True
        assert sentinel_mock.calls == 0
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
        extractor, _ = _extractor_with_mock(bad_payload, max_retries=1)
        with pytest.raises(ExtractorError):
            extractor.extract(_make_chunk())


class TestDedup:
    def test_merges_fuzzy_matches_within_type(self) -> None:
        a = ExtractedEntity(name="Sheldon Cooper", type="Character")
        b = ExtractedEntity(name="Dr. Sheldon Cooper", type="Character", aliases=["Shelly"])
        out, rename_map = dedupe_within_doc([a, b])
        assert len(out) == 1
        assert out[0].name == "Sheldon Cooper"
        assert "Shelly" in out[0].aliases
        assert "Dr. Sheldon Cooper" in out[0].aliases
        # Both surface forms map to the canonical first-seen name.
        assert rename_map["Sheldon Cooper"] == "Sheldon Cooper"
        assert rename_map["Dr. Sheldon Cooper"] == "Sheldon Cooper"

    def test_keeps_distinct_types_separate(self) -> None:
        a = ExtractedEntity(name="Mercury", type="Concept")
        b = ExtractedEntity(name="Mercury", type="Location")
        out, rename_map = dedupe_within_doc([a, b])
        assert len(out) == 2
        assert rename_map == {"Mercury": "Mercury"}  # both are identity (only one key wins)

    def test_empty(self) -> None:
        assert dedupe_within_doc([]) == ([], {})

    def test_rename_map_preserves_relationship_validity(self) -> None:
        """Relationships referencing merged surface forms must remap cleanly."""
        from knowledge_graph.extractor.schemas import ExtractedRelationship, Extraction

        a = ExtractedEntity(name="Season 5", type="Event")
        b = ExtractedEntity(name="Season 5 finale", type="Event")
        rel = ExtractedRelationship(
            source="Season 5 finale",
            target="Season 5",
            predicate="PART_OF",
            evidence_span="The Season 5 finale wraps Season 5.",
            confidence=0.9,
            provenance_tag="EXTRACTED",
        )
        deduped, rename_map = dedupe_within_doc([a, b])
        remapped = rel.model_copy(
            update={
                "source": rename_map.get(rel.source, rel.source),
                "target": rename_map.get(rel.target, rel.target),
            }
        )
        # Both endpoints now resolve to the surviving entity ("Season 5").
        assert remapped.source == "Season 5"
        assert remapped.target == "Season 5"
        # Self-loop after dedup is fine — Extraction validation passes.
        Extraction(entities=deduped, relationships=[remapped])


class TestBackendFactory:
    def test_make_backend_anthropic(self) -> None:
        backend = make_backend("anthropic", ExtractorSettings(api_key="test"))
        assert backend.__class__.__name__ == "AnthropicBackend"

    def test_make_backend_openai(self) -> None:
        backend = make_backend(
            "openai", ExtractorSettings(api_key="test", base_url="http://localhost:11434/v1")
        )
        assert backend.__class__.__name__ == "OpenAIBackend"

    def test_make_backend_mock(self) -> None:
        backend = make_backend("mock", ExtractorSettings())
        assert backend.__class__.__name__ == "MockBackend"

    def test_make_backend_unknown(self) -> None:
        with pytest.raises(ValueError, match="unknown LLM backend"):
            make_backend("xyz", ExtractorSettings())
