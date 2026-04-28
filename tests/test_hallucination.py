"""Hallucination metrics unit tests."""

from __future__ import annotations

from evals.harness.hallucination import aggregate, score_extraction

from knowledge_graph.extractor.schemas import (
    ExtractedEntity,
    ExtractedRelationship,
    Extraction,
)


def _ext(
    rels: list[ExtractedRelationship], ents: list[ExtractedEntity] | None = None
) -> Extraction:
    if ents is None:
        names = {r.source for r in rels} | {r.target for r in rels}
        ents = [ExtractedEntity(name=n, type="Character") for n in names]
    return Extraction(entities=ents, relationships=rels)


class TestEvidenceGrounding:
    def test_grounded_substring(self) -> None:
        ext = _ext(
            [
                ExtractedRelationship(
                    source="Sheldon",
                    target="Leonard",
                    predicate="ROOMMATES_WITH",
                    evidence_span="Sheldon and Leonard share an apartment.",
                    confidence=0.9,
                    provenance_tag="EXTRACTED",
                )
            ]
        )
        report = score_extraction(ext)
        assert report.evidence_grounding_rate == 1.0
        assert report.flagged == []

    def test_ungrounded_when_neither_appears(self) -> None:
        ext = _ext(
            [
                ExtractedRelationship(
                    source="Sheldon",
                    target="Penny",
                    predicate="ROOMMATES_WITH",
                    evidence_span="They have known each other for years.",
                    confidence=0.6,
                    provenance_tag="AMBIGUOUS",
                )
            ]
        )
        report = score_extraction(ext)
        assert report.evidence_grounding_rate == 0.0
        assert any("ungrounded" in f for f in report.flagged)

    def test_alias_counts_as_grounding(self) -> None:
        ext = Extraction(
            entities=[
                ExtractedEntity(name="Sheldon Cooper", type="Character", aliases=["Shelly"]),
                ExtractedEntity(name="Caltech", type="Organization"),
            ],
            relationships=[
                ExtractedRelationship(
                    source="Sheldon Cooper",
                    target="Caltech",
                    predicate="WORKS_AT",
                    evidence_span="Shelly works at Caltech.",
                    confidence=0.92,
                    provenance_tag="EXTRACTED",
                )
            ],
        )
        report = score_extraction(ext)
        assert report.evidence_grounding_rate == 1.0


class TestPredicateTypeSignature:
    def test_works_at_with_correct_types_passes(self) -> None:
        ext = Extraction(
            entities=[
                ExtractedEntity(name="Sheldon", type="Character"),
                ExtractedEntity(name="Caltech", type="Organization"),
            ],
            relationships=[
                ExtractedRelationship(
                    source="Sheldon",
                    target="Caltech",
                    predicate="WORKS_AT",
                    evidence_span="Sheldon works at Caltech",
                    confidence=0.95,
                    provenance_tag="EXTRACTED",
                )
            ],
        )
        report = score_extraction(ext)
        assert report.predicate_type_ok_rate == 1.0

    def test_works_at_with_wrong_target_type_fails(self) -> None:
        ext = Extraction(
            entities=[
                ExtractedEntity(name="Sheldon", type="Character"),
                ExtractedEntity(name="Mercury", type="Concept"),  # not Organization/Location
            ],
            relationships=[
                ExtractedRelationship(
                    source="Sheldon",
                    target="Mercury",
                    predicate="WORKS_AT",
                    evidence_span="Sheldon works at Mercury",
                    confidence=0.7,
                    provenance_tag="INFERRED",
                )
            ],
        )
        report = score_extraction(ext)
        assert report.predicate_type_ok_rate == 0.0
        assert any("type-violation" in f for f in report.flagged)

    def test_unknown_predicate_passes(self) -> None:
        ext = Extraction(
            entities=[
                ExtractedEntity(name="A", type="Concept"),
                ExtractedEntity(name="B", type="Concept"),
            ],
            relationships=[
                ExtractedRelationship(
                    source="A",
                    target="B",
                    predicate="NOVEL_PREDICATE_NOT_IN_MAP",
                    evidence_span="A is connected to B",
                    confidence=0.8,
                    provenance_tag="INFERRED",
                )
            ],
        )
        report = score_extraction(ext)
        # Unknown predicates don't count against you (precision over recall).
        assert report.predicate_type_ok_rate == 1.0


class TestAggregate:
    def test_combines_counts(self) -> None:
        ext1 = _ext(
            [
                ExtractedRelationship(
                    source="A",
                    target="B",
                    predicate="MARRIED_TO",
                    evidence_span="A married B",
                    confidence=0.9,
                    provenance_tag="EXTRACTED",
                )
            ]
        )
        ext2 = _ext(
            [
                ExtractedRelationship(
                    source="C",
                    target="D",
                    predicate="MARRIED_TO",
                    evidence_span="They are spouses.",  # neither name in span
                    confidence=0.6,
                    provenance_tag="AMBIGUOUS",
                )
            ]
        )
        agg = aggregate([score_extraction(ext1), score_extraction(ext2)])
        assert agg.n_relationships == 2
        assert agg.n_grounded == 1
        assert agg.evidence_grounding_rate == 0.5

    def test_empty_aggregation(self) -> None:
        agg = aggregate([])
        assert agg.n_relationships == 0
        assert agg.evidence_grounding_rate == 1.0
