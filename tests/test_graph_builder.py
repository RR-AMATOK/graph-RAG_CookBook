"""Graph builder unit tests with a stub FalkorDB graph."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from knowledge_graph.canonicalizer.schema import CanonicalFrontmatter
from knowledge_graph.chunker import Chunk
from knowledge_graph.extractor.schemas import (
    ExtractedEntity,
    ExtractedRelationship,
    Extraction,
)
from knowledge_graph.graph import GraphBuilder, GraphClient
from knowledge_graph.graph.ids import edge_id, entity_id

# ─────────────────────────────────────────────────────────────────────
# Stub FalkorDB graph
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _StubResult:
    result_set: list[list[Any]] = field(default_factory=list)


class _StubGraph:
    """Records every query and returns a configurable result_set per pattern."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        # Maps node id -> stored aliases (for the entity-exists check).
        self.entities: dict[str, dict[str, Any]] = {}
        self.relationships: dict[str, dict[str, Any]] = {}

    def query(self, cypher: str, params: dict[str, Any]) -> _StubResult:
        self.calls.append((cypher, params))
        cypher_compact = " ".join(cypher.split())

        if cypher_compact.startswith("MATCH (e:Entity {entity_id: $id}) RETURN e.aliases"):
            ent_id = params["id"]
            if ent_id in self.entities:
                return _StubResult(result_set=[[self.entities[ent_id]["aliases"]]])
            return _StubResult(result_set=[])

        if cypher_compact.startswith("CREATE (e:Entity"):
            self.entities[params["id"]] = {
                "name": params["name"],
                "type": params["type"],
                "aliases": list(params["aliases"]),
                "description": params["description"],
                "first_seen_doc": params["first_seen_doc"],
                "mention_count": 1,
            }
            return _StubResult()

        if cypher_compact.startswith("MATCH (e:Entity {entity_id: $id}) SET e.aliases"):
            self.entities[params["id"]]["aliases"] = list(params["aliases"])
            self.entities[params["id"]]["mention_count"] = (
                self.entities[params["id"]].get("mention_count", 0) + 1
            )
            return _StubResult()

        if (
            cypher_compact.startswith(
                "MATCH (s:Entity {entity_id: $source_id})-[r:RELATES {edge_id: $edge_id}]"
            )
            and "RETURN" in cypher_compact
        ):
            edge = self.relationships.get(params["edge_id"])
            if edge:
                return _StubResult(
                    result_set=[
                        [
                            list(edge["source_doc_ids"]),
                            list(edge["evidence_spans"]),
                            edge["confidence"],
                        ]
                    ]
                )
            return _StubResult(result_set=[])

        if cypher_compact.startswith("MATCH (s:Entity {entity_id: $source_id}), (t:Entity"):
            self.relationships[params["edge_id"]] = {
                "source_id": params["source_id"],
                "target_id": params["target_id"],
                "predicate": params["predicate"],
                "confidence": params["confidence"],
                "provenance_tag": params["provenance_tag"],
                "source_doc_ids": list(params["doc_ids"]),
                "evidence_spans": list(params["spans"]),
            }
            return _StubResult()

        if (
            cypher_compact.startswith(
                "MATCH (s:Entity {entity_id: $source_id})-[r:RELATES {edge_id: $edge_id}]->(t"
            )
            and "SET" in cypher_compact
        ):
            edge = self.relationships[params["edge_id"]]
            edge["source_doc_ids"] = list(params["doc_ids"])
            edge["evidence_spans"] = list(params["spans"])
            edge["confidence"] = params["confidence"]
            return _StubResult()

        # MERGE Document and other writes — no-ops for the stub.
        return _StubResult()


def _make_fm(canonical: str = "corpus-a/test") -> CanonicalFrontmatter:
    return CanonicalFrontmatter(
        title="Test",
        aliases=[],
        tags=["t"],
        parent=None,
        source_repo="corpus-a",
        source_path="test.md",
        source_url=None,
        license=None,
        license_url=None,
        created=None,
        updated=date(2026, 4, 27),
        doc_id="doc_test_one",
        canonical_path=canonical,
        content_hash="sha256:" + "0" * 64,
    )


def _make_chunk(doc_id: str = "doc_test_one") -> Chunk:
    return Chunk(
        chunk_id="chk_test",
        doc_id=doc_id,
        canonical_path="corpus-a/test",
        offset=0,
        heading=None,
        text="Sample text.",
        token_estimate=5,
    )


def _make_extraction() -> Extraction:
    return Extraction(
        entities=[
            ExtractedEntity(name="Sheldon Cooper", type="Character"),
            ExtractedEntity(name="Caltech", type="Organization"),
        ],
        relationships=[
            ExtractedRelationship(
                source="Sheldon Cooper",
                target="Caltech",
                predicate="WORKS_AT",
                evidence_span="Sheldon works at Caltech",
                confidence=0.95,
                provenance_tag="EXTRACTED",
            )
        ],
    )


class TestGraphBuilder:
    def _build(self) -> tuple[_StubGraph, GraphBuilder]:
        stub = _StubGraph()
        client = GraphClient()
        client.inject_graph(stub)
        return stub, GraphBuilder(client=client)

    def test_upsert_document_increments_count(self) -> None:
        _, builder = self._build()
        builder.upsert_document(_make_fm())
        assert builder.stats.documents_upserted == 1

    def test_writes_entities_and_relationship(self) -> None:
        stub, builder = self._build()
        builder.upsert_document(_make_fm())
        builder.write_extraction(
            doc_fm=_make_fm(), chunk=_make_chunk(), extraction=_make_extraction()
        )
        assert builder.stats.entities_created == 2
        assert builder.stats.relationships_created == 1
        assert builder.stats.mentions_created == 2

        # The relationship in the stub uses the deterministic edge_id.
        eid = edge_id(
            entity_id("Sheldon Cooper", "Character"),
            entity_id("Caltech", "Organization"),
            "WORKS_AT",
        )
        assert eid in stub.relationships

    def test_second_chunk_with_same_entity_increments_mention_count(self) -> None:
        stub, builder = self._build()
        builder.upsert_document(_make_fm())
        builder.write_extraction(
            doc_fm=_make_fm(), chunk=_make_chunk(), extraction=_make_extraction()
        )
        # Same extraction again — mention_count should rise via update path.
        builder.write_extraction(
            doc_fm=_make_fm(), chunk=_make_chunk(), extraction=_make_extraction()
        )
        sheldon = entity_id("Sheldon Cooper", "Character")
        assert stub.entities[sheldon]["mention_count"] >= 2
        assert builder.stats.entities_updated >= 2

    def test_repeated_relationship_unions_evidence(self) -> None:
        stub, builder = self._build()
        builder.upsert_document(_make_fm())
        builder.write_extraction(
            doc_fm=_make_fm(), chunk=_make_chunk(), extraction=_make_extraction()
        )

        # Same predicate, new evidence span (e.g., another chunk).
        ext_b = Extraction(
            entities=_make_extraction().entities,
            relationships=[
                ExtractedRelationship(
                    source="Sheldon Cooper",
                    target="Caltech",
                    predicate="WORKS_AT",
                    evidence_span="...is a physicist at Caltech",
                    confidence=0.90,
                    provenance_tag="EXTRACTED",
                )
            ],
        )
        builder.write_extraction(doc_fm=_make_fm(), chunk=_make_chunk(), extraction=ext_b)

        eid = edge_id(
            entity_id("Sheldon Cooper", "Character"),
            entity_id("Caltech", "Organization"),
            "WORKS_AT",
        )
        edge = stub.relationships[eid]
        assert len(edge["evidence_spans"]) == 2
        assert builder.stats.relationships_updated == 1
