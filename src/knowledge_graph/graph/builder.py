"""Graph ingest builder — writes Documents, Entities, and Edges from extraction results.

The builder maintains an in-process map of ``(name, type) → entity_id`` so a
relationship's ``source``/``target`` (which the LLM emits by name) resolves to
the right entity id even when the same entity appears in multiple chunks of
the same document. Cross-document resolution falls out for free because the
id is derived purely from ``(normalized_name, type)`` — see
:mod:`knowledge_graph.graph.ids`.

Sprint 2 scope:
- Documents: MERGE on ``doc_id``; set/refresh canonical metadata.
- Entities: MERGE on ``entity_id``; first-write wins for ``description`` /
  ``first_seen_doc`` / ``type``. Aliases union via MATCH-then-SET so we don't
  lose forms emitted by later chunks.
- Edges: MERGE typed relationship by ``edge_id``. Per-source-doc evidence
  accumulates in ``source_doc_ids`` and ``evidence_spans`` on update.
- MENTIONS: a separate edge from Document to Entity per chunk, carrying
  ``chunk_offset`` and ``chunk_id``. Always created (no MERGE) — multiple
  mentions per doc are expected.

Out of scope (Sprint 3+): PARENT_OF edges between documents, FR-4.7 re-ingest
delete-and-reinsert, batch CYPHER UNWIND.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from knowledge_graph.canonicalizer.schema import CanonicalFrontmatter
from knowledge_graph.chunker import Chunk
from knowledge_graph.extractor.schemas import (
    ExtractedEntity,
    ExtractedRelationship,
    Extraction,
)
from knowledge_graph.graph.client import GraphClient
from knowledge_graph.graph.ids import edge_id, entity_id

logger = logging.getLogger(__name__)


@dataclass
class BuilderStats:
    documents_upserted: int = 0
    entities_created: int = 0
    entities_updated: int = 0
    relationships_created: int = 0
    relationships_updated: int = 0
    mentions_created: int = 0


@dataclass
class GraphBuilder:
    """Orchestrates writes to FalkorDB for an ingest run."""

    client: GraphClient
    stats: BuilderStats = field(default_factory=BuilderStats)

    def upsert_document(self, fm: CanonicalFrontmatter) -> None:
        """Create or refresh a Document node. Idempotent on ``doc_id``."""
        params: dict[str, Any] = {
            "doc_id": fm.doc_id,
            "canonical_path": fm.canonical_path,
            "title": fm.title,
            "source_url": fm.source_url or "",
            "content_hash": fm.content_hash,
            "updated_at": fm.updated.isoformat(),
            "ingested_at": _utc_now_iso(),
        }
        self.client.query(
            """
            MERGE (d:Document {doc_id: $doc_id})
            SET d.canonical_path = $canonical_path,
                d.title = $title,
                d.source_url = $source_url,
                d.content_hash = $content_hash,
                d.updated_at = $updated_at,
                d.ingested_at = $ingested_at
            """,
            params,
        )
        self.stats.documents_upserted += 1

    def write_extraction(
        self, *, doc_fm: CanonicalFrontmatter, chunk: Chunk, extraction: Extraction
    ) -> None:
        """Write all entities + relationships + mentions from one chunk."""
        name_to_id: dict[str, str] = {}

        for ent in extraction.entities:
            ent_id = entity_id(ent.name, ent.type)
            name_to_id[ent.name] = ent_id
            self._upsert_entity(ent, ent_id=ent_id, first_seen_doc=doc_fm.doc_id)
            self._create_mention(
                doc_id=doc_fm.doc_id,
                entity_id=ent_id,
                chunk_id=chunk.chunk_id,
                chunk_offset=chunk.offset,
            )

        for rel in extraction.relationships:
            source_id = name_to_id.get(rel.source)
            target_id = name_to_id.get(rel.target)
            if source_id is None or target_id is None:
                # Schema-level validation guarantees the names match an
                # extracted entity, but defensive logging surfaces any
                # consistency drift.
                logger.warning(
                    "skipping relationship with unresolved endpoint: %s -[%s]-> %s",
                    rel.source,
                    rel.predicate,
                    rel.target,
                )
                continue
            self._upsert_relationship(
                rel,
                source_id=source_id,
                target_id=target_id,
                doc_id=doc_fm.doc_id,
            )

    # ─────────────────────────────────────────────────────────────────
    # Internals
    # ─────────────────────────────────────────────────────────────────

    def _upsert_entity(self, ent: ExtractedEntity, *, ent_id: str, first_seen_doc: str) -> None:
        existing = self.client.query(
            "MATCH (e:Entity {entity_id: $id}) RETURN e.aliases AS aliases",
            {"id": ent_id},
        )
        rows = list(getattr(existing, "result_set", []) or [])
        if rows:
            current_aliases = list(rows[0][0]) if rows[0] and rows[0][0] else []
            merged = _union_preserve_order(current_aliases, [*ent.aliases, ent.name])
            self.client.query(
                """
                MATCH (e:Entity {entity_id: $id})
                SET e.aliases = $aliases,
                    e.mention_count = coalesce(e.mention_count, 0) + 1
                """,
                {"id": ent_id, "aliases": merged},
            )
            self.stats.entities_updated += 1
        else:
            self.client.query(
                """
                CREATE (e:Entity {
                    entity_id: $id,
                    name: $name,
                    type: $type,
                    aliases: $aliases,
                    description: $description,
                    first_seen_doc: $first_seen_doc,
                    mention_count: 1
                })
                """,
                {
                    "id": ent_id,
                    "name": ent.name,
                    "type": ent.type,
                    "aliases": list(dict.fromkeys([*ent.aliases, ent.name])),
                    "description": ent.description,
                    "first_seen_doc": first_seen_doc,
                },
            )
            self.stats.entities_created += 1

    def _create_mention(
        self,
        *,
        doc_id: str,
        entity_id: str,
        chunk_id: str,
        chunk_offset: int,
    ) -> None:
        self.client.query(
            """
            MATCH (d:Document {doc_id: $doc_id}), (e:Entity {entity_id: $ent_id})
            CREATE (d)-[:MENTIONS {chunk_id: $chunk_id, chunk_offset: $chunk_offset}]->(e)
            """,
            {
                "doc_id": doc_id,
                "ent_id": entity_id,
                "chunk_id": chunk_id,
                "chunk_offset": chunk_offset,
            },
        )
        self.stats.mentions_created += 1

    def _upsert_relationship(
        self,
        rel: ExtractedRelationship,
        *,
        source_id: str,
        target_id: str,
        doc_id: str,
    ) -> None:
        e_id = edge_id(source_id, target_id, rel.predicate)
        existing = self.client.query(
            """
            MATCH (s:Entity {entity_id: $source_id})-[r:RELATES {edge_id: $edge_id}]->(t:Entity {entity_id: $target_id})
            RETURN r.source_doc_ids AS doc_ids, r.evidence_spans AS spans, r.confidence AS confidence
            """,
            {"source_id": source_id, "target_id": target_id, "edge_id": e_id},
        )
        rows = list(getattr(existing, "result_set", []) or [])
        if rows:
            current_doc_ids = list(rows[0][0]) if rows[0][0] else []
            current_spans = list(rows[0][1]) if rows[0][1] else []
            current_conf = float(rows[0][2]) if rows[0][2] is not None else rel.confidence
            new_doc_ids = _union_preserve_order(current_doc_ids, [doc_id])
            new_spans = _union_preserve_order(current_spans, [rel.evidence_span])
            # Confidence: max of seen values — multiple supporting docs only
            # raise our certainty.
            new_conf = max(current_conf, rel.confidence)
            self.client.query(
                """
                MATCH (s:Entity {entity_id: $source_id})-[r:RELATES {edge_id: $edge_id}]->(t:Entity {entity_id: $target_id})
                SET r.source_doc_ids = $doc_ids,
                    r.evidence_spans = $spans,
                    r.confidence = $confidence
                """,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "edge_id": e_id,
                    "doc_ids": new_doc_ids,
                    "spans": new_spans,
                    "confidence": new_conf,
                },
            )
            self.stats.relationships_updated += 1
        else:
            self.client.query(
                """
                MATCH (s:Entity {entity_id: $source_id}), (t:Entity {entity_id: $target_id})
                CREATE (s)-[r:RELATES {
                    edge_id: $edge_id,
                    predicate: $predicate,
                    confidence: $confidence,
                    provenance_tag: $provenance_tag,
                    source_doc_ids: $doc_ids,
                    evidence_spans: $spans
                }]->(t)
                """,
                {
                    "source_id": source_id,
                    "target_id": target_id,
                    "edge_id": e_id,
                    "predicate": rel.predicate,
                    "confidence": rel.confidence,
                    "provenance_tag": rel.provenance_tag,
                    "doc_ids": [doc_id],
                    "spans": [rel.evidence_span],
                },
            )
            self.stats.relationships_created += 1


def _union_preserve_order(existing: list[Any], incoming: list[Any]) -> list[Any]:
    seen: set[Any] = set()
    out: list[Any] = []
    for item in [*existing, *incoming]:
        if item is None or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat()
