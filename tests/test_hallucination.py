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
        # Without chunk_text, chunk_grounding falls back to span-grounding,
        # so the relationship is also flagged at the lenient (hallucinated) level.
        assert report.chunk_grounding_rate == 0.0
        assert any("hallucinated" in f for f in report.flagged)

    def test_chunk_grounding_rescues_unnamed_evidence_spans(self) -> None:
        """A relationship whose evidence span doesn't name the entities should
        still be chunk-grounded if the entities ARE in the chunk text — that's
        normal LLM citation behavior, not a hallucination."""
        ext = Extraction(
            entities=[
                ExtractedEntity(name="Leonard Hofstadter", type="Character"),
                ExtractedEntity(name="Caltech", type="Organization"),
            ],
            relationships=[
                ExtractedRelationship(
                    source="Leonard Hofstadter",
                    target="Caltech",
                    predicate="WORKS_AT",
                    evidence_span="works as an experimental physicist",
                    confidence=0.9,
                    provenance_tag="EXTRACTED",
                )
            ],
        )
        chunk = "Leonard Hofstadter works as an experimental physicist at Caltech in Pasadena."
        report = score_extraction(ext, chunk_text=chunk)
        # Strict (span) metric flags it — names not in span.
        assert report.evidence_grounding_rate == 0.0
        # Lenient (chunk) metric clears it — names ARE in the chunk.
        assert report.chunk_grounding_rate == 1.0
        assert report.flagged == []

    def test_partial_name_in_chunk_counts_as_grounded(self) -> None:
        """LLMs frequently emit canonical full names while the chunk uses
        a partial name (last name only, first name only). The grounding
        metric must accept any content-word token match, otherwise it
        false-flags every such canonical extraction as a hallucination."""
        ext = Extraction(
            entities=[
                ExtractedEntity(name="Leonard Hofstadter", type="Character"),
                ExtractedEntity(name="Sheldon Cooper", type="Character"),
            ],
            relationships=[
                ExtractedRelationship(
                    source="Leonard Hofstadter",
                    target="Sheldon Cooper",
                    predicate="ROOMMATES_WITH",
                    evidence_span="Because he has lived with Sheldon for years, Leonard knows him.",
                    confidence=0.9,
                    provenance_tag="EXTRACTED",
                )
            ],
        )
        report = score_extraction(ext, chunk_text=ext.relationships[0].evidence_span)
        # Span contains "Leonard" and "Sheldon" as standalone tokens — both
        # endpoints' content tokens match. Strict (substring) match is False
        # because "Leonard Hofstadter" is not a literal substring; token-level
        # match rescues it.
        assert report.chunk_grounding_rate == 1.0
        assert report.flagged == []

    def test_token_match_skips_stopwords(self) -> None:
        """A name like "The Pilot" must not be considered grounded just
        because the chunk contains "the" — only content tokens count."""
        ext = Extraction(
            entities=[
                ExtractedEntity(name="The Pilot", type="Event"),
                ExtractedEntity(name="The Series", type="Work"),
            ],
            relationships=[
                ExtractedRelationship(
                    source="The Pilot",
                    target="The Series",
                    predicate="PART_OF",
                    evidence_span="and another, in the meantime",
                    confidence=0.5,
                    provenance_tag="AMBIGUOUS",
                )
            ],
        )
        report = score_extraction(ext, chunk_text=ext.relationships[0].evidence_span)
        # Stopwords-only would falsely accept; correct behavior rejects.
        assert report.chunk_grounding_rate == 0.0
        assert any("hallucinated" in f for f in report.flagged)

    def test_token_match_uses_word_boundaries(self) -> None:
        """``"Big Bang"`` must not match ``"bigger"`` — token check uses
        whole-word boundaries."""
        ext = Extraction(
            entities=[
                ExtractedEntity(name="Big Bang", type="Concept"),
                ExtractedEntity(name="Cosmos", type="Concept"),
            ],
            relationships=[
                ExtractedRelationship(
                    source="Big Bang",
                    target="Cosmos",
                    predicate="PART_OF",
                    evidence_span="bigger telescopes look at distant stars",
                    confidence=0.4,
                    provenance_tag="AMBIGUOUS",
                )
            ],
        )
        report = score_extraction(ext, chunk_text=ext.relationships[0].evidence_span)
        # No content-word token of "Big Bang" or "Cosmos" appears as a whole
        # word — flagged as hallucinated.
        assert report.chunk_grounding_rate == 0.0

    def test_chunk_grounding_catches_real_hallucination(self) -> None:
        """A relationship whose entity is absent from BOTH span AND chunk is
        a real hallucination."""
        ext = _ext(
            [
                ExtractedRelationship(
                    source="Sheldon Cooper",
                    target="Hogwarts",
                    predicate="WORKS_AT",
                    evidence_span="Sheldon went to school",
                    confidence=0.5,
                    provenance_tag="AMBIGUOUS",
                )
            ]
        )
        chunk = "Sheldon Cooper went to school in Texas. He later attended Caltech."
        report = score_extraction(ext, chunk_text=chunk)
        assert report.chunk_grounding_rate == 0.0
        assert any("hallucinated" in f and "Hogwarts" in f for f in report.flagged)

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
