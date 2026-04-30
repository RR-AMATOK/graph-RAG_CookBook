"""Unit tests for evals.harness.prompt_eval — golden scoring + comparison."""

from __future__ import annotations

from evals.harness.prompt_eval import (
    _DocPrediction,
    _entity_match,
    _normalize_name,
    _score_entities,
    _score_relationships,
)
from evals.harness.types import (
    ExpectedEntity,
    ExpectedRelationship,
    GoldenEntry,
)

from knowledge_graph.extractor.schemas import (
    ExtractedEntity,
    ExtractedRelationship,
)

# ─────────────────────────────────────────────────────────────────────
# _normalize_name
# ─────────────────────────────────────────────────────────────────────


class TestNormalizeName:
    def test_lowercases_and_strips_punctuation(self) -> None:
        assert _normalize_name("Dr. Sheldon Cooper") == "dr sheldon cooper"

    def test_drops_stopwords(self) -> None:
        assert _normalize_name("The Pilot") == "pilot"
        assert _normalize_name("Lord of the Rings") == "lord rings"

    def test_keeps_content_only_string_for_all_stopwords(self) -> None:
        # All-stopword input falls back to the original normalized form
        # rather than producing an empty key (which would false-match).
        assert _normalize_name("the the the") == "the the the"

    def test_collapses_whitespace(self) -> None:
        assert _normalize_name("  Sheldon   Cooper  ") == "sheldon cooper"


# ─────────────────────────────────────────────────────────────────────
# _entity_match
# ─────────────────────────────────────────────────────────────────────


class TestEntityMatch:
    def test_exact_after_normalization(self) -> None:
        assert _entity_match("Sheldon Cooper", "sheldon cooper")

    def test_alias_match(self) -> None:
        assert _entity_match("Shelly", "Sheldon Cooper", ["Shelly", "Dr. Cooper"])

    def test_fuzzy_token_set_match(self) -> None:
        # rapidfuzz token_set_ratio >= 90 catches variant ordering / extra titles.
        assert _entity_match("Dr. Sheldon Cooper", "Sheldon Cooper")
        assert _entity_match("Sheldon Cooper Jr.", "Sheldon Cooper")

    def test_no_match_for_different_entities(self) -> None:
        assert not _entity_match("Penny", "Sheldon Cooper")
        assert not _entity_match("Caltech", "MIT")

    def test_empty_predicted_returns_false(self) -> None:
        assert not _entity_match("", "Sheldon Cooper")

    def test_partial_name_does_not_pass_strict_threshold(self) -> None:
        # Short partial name has low token_set_ratio against the full canonical name.
        # The chunk-level grounding metric handles this case via tokens; the
        # entity matcher here is stricter.
        assert not _entity_match("S", "Sheldon Cooper")


# ─────────────────────────────────────────────────────────────────────
# _score_entities
# ─────────────────────────────────────────────────────────────────────


def _golden(
    doc_id: str,
    entities: list[tuple[str, str]],
    relationships: list[tuple[str, str, str]] | None = None,
) -> GoldenEntry:
    return GoldenEntry(
        doc_id=doc_id,
        canonical_path=f"corpus-a/{doc_id}",
        expected_entities=tuple(ExpectedEntity(name=n, type=t) for n, t in entities),
        expected_relationships=tuple(
            ExpectedRelationship(source=s, target=t, predicate=p)
            for s, t, p in (relationships or [])
        ),
    )


def _predicted(
    entities: list[tuple[str, str]],
    relationships: list[tuple[str, str, str]] | None = None,
) -> _DocPrediction:
    pred = _DocPrediction()
    pred.entities = [ExtractedEntity(name=n, type=t) for n, t in entities]
    pred.relationships = [
        ExtractedRelationship(
            source=s,
            target=t,
            predicate=p,
            evidence_span=f"{s} ... {t}",
            confidence=0.9,
            provenance_tag="EXTRACTED",
        )
        for s, t, p in (relationships or [])
    ]
    return pred


class TestScoreEntities:
    def test_perfect_match(self) -> None:
        gold = _golden("d1", [("Sheldon Cooper", "Character"), ("Caltech", "Organization")])
        preds = {"d1": _predicted([("Sheldon Cooper", "Character"), ("Caltech", "Organization")])}
        scores = _score_entities(preds, [gold])
        assert scores.precision == 1.0
        assert scores.recall == 1.0
        assert scores.f1 == 1.0
        assert scores.coverage == 1.0
        assert scores.per_type_f1 == {"Character": 1.0, "Organization": 1.0}

    def test_extra_predictions_hurt_precision(self) -> None:
        gold = _golden("d1", [("Sheldon Cooper", "Character")])
        preds = {
            "d1": _predicted(
                [("Sheldon Cooper", "Character"), ("Penny", "Character"), ("Leonard", "Character")]
            )
        }
        scores = _score_entities(preds, [gold])
        # 1 TP, 2 FP; recall=1.0, precision=1/3
        assert scores.recall == 1.0
        assert abs(scores.precision - 1 / 3) < 1e-9

    def test_missing_predictions_hurt_recall(self) -> None:
        gold = _golden(
            "d1",
            [("Sheldon Cooper", "Character"), ("Penny", "Character"), ("Caltech", "Organization")],
        )
        preds = {"d1": _predicted([("Sheldon Cooper", "Character")])}
        scores = _score_entities(preds, [gold])
        # 1 TP / 3 expected → recall 1/3
        assert abs(scores.recall - 1 / 3) < 1e-9
        assert scores.precision == 1.0

    def test_type_mismatch_does_not_count(self) -> None:
        gold = _golden("d1", [("Sheldon Cooper", "Character")])
        # Predicted as Person instead of Character — no match.
        preds = {"d1": _predicted([("Sheldon Cooper", "Person")])}
        scores = _score_entities(preds, [gold])
        assert scores.n_true_positive == 0

    def test_alias_match_is_credited(self) -> None:
        gold = GoldenEntry(
            doc_id="d1",
            canonical_path="corpus-a/d1",
            expected_entities=(
                ExpectedEntity(name="Sheldon Cooper", type="Character", aliases=("Shelly",)),
            ),
            expected_relationships=(),
        )
        preds = {"d1": _predicted([("Shelly", "Character")])}
        scores = _score_entities(preds, [gold])
        assert scores.f1 == 1.0

    def test_per_doc_dedup(self) -> None:
        gold = _golden("d1", [("Sheldon Cooper", "Character")])
        # Multiple chunks emitted "Sheldon Cooper" — should count once per doc.
        preds = {
            "d1": _predicted([("Sheldon Cooper", "Character"), ("Sheldon Cooper", "Character")])
        }
        scores = _score_entities(preds, [gold])
        assert scores.n_predicted == 1

    def test_aggregates_across_docs(self) -> None:
        g1 = _golden("d1", [("Sheldon", "Character")])
        g2 = _golden("d2", [("Penny", "Character")])
        preds = {
            "d1": _predicted([("Sheldon", "Character")]),
            "d2": _predicted([("Penny", "Character"), ("Wrong", "Character")]),
        }
        scores = _score_entities(preds, [g1, g2])
        assert scores.n_true_positive == 2
        assert scores.n_predicted == 3
        assert scores.n_expected == 2


# ─────────────────────────────────────────────────────────────────────
# _score_relationships
# ─────────────────────────────────────────────────────────────────────


class TestScoreRelationships:
    def test_perfect_triple_match(self) -> None:
        gold = _golden(
            "d1",
            [("Sheldon Cooper", "Character"), ("Caltech", "Organization")],
            [("Sheldon Cooper", "Caltech", "WORKS_AT")],
        )
        preds = {
            "d1": _predicted(
                [("Sheldon Cooper", "Character"), ("Caltech", "Organization")],
                [("Sheldon Cooper", "Caltech", "WORKS_AT")],
            )
        }
        scores = _score_relationships(preds, [gold])
        assert scores.f1 == 1.0

    def test_direction_matters(self) -> None:
        gold = _golden(
            "d1",
            [("Daniel Kim", "Person"), ("Detective Lila", "Character")],
            [("Daniel Kim", "Detective Lila", "PORTRAYS")],
        )
        # Inverted direction
        preds = {
            "d1": _predicted(
                [("Daniel Kim", "Person"), ("Detective Lila", "Character")],
                [("Detective Lila", "Daniel Kim", "PORTRAYS")],
            )
        }
        scores = _score_relationships(preds, [gold])
        assert scores.n_true_positive == 0

    def test_predicate_must_match_exactly(self) -> None:
        gold = _golden(
            "d1",
            [("Sheldon", "Character"), ("Caltech", "Organization")],
            [("Sheldon", "Caltech", "WORKS_AT")],
        )
        preds = {
            "d1": _predicted(
                [("Sheldon", "Character"), ("Caltech", "Organization")],
                [("Sheldon", "Caltech", "EMPLOYED_BY")],
            )
        }
        scores = _score_relationships(preds, [gold])
        assert scores.n_true_positive == 0

    def test_endpoint_alias_match_via_expected_entities(self) -> None:
        gold = GoldenEntry(
            doc_id="d1",
            canonical_path="corpus-a/d1",
            expected_entities=(
                ExpectedEntity(name="Sheldon Cooper", type="Character", aliases=("Shelly",)),
                ExpectedEntity(name="Caltech", type="Organization"),
            ),
            expected_relationships=(
                ExpectedRelationship(
                    source="Sheldon Cooper", target="Caltech", predicate="WORKS_AT"
                ),
            ),
        )
        # Predicted relationship uses the alias surface form.
        preds = {
            "d1": _predicted(
                [("Shelly", "Character"), ("Caltech", "Organization")],
                [("Shelly", "Caltech", "WORKS_AT")],
            )
        }
        scores = _score_relationships(preds, [gold])
        assert scores.f1 == 1.0

    def test_dedup_within_doc(self) -> None:
        gold = _golden(
            "d1",
            [("Sheldon", "Character"), ("Caltech", "Organization")],
            [("Sheldon", "Caltech", "WORKS_AT")],
        )
        # Same triple emitted twice (different chunks) → counted once.
        preds = {
            "d1": _predicted(
                [("Sheldon", "Character"), ("Caltech", "Organization")],
                [
                    ("Sheldon", "Caltech", "WORKS_AT"),
                    ("Sheldon", "Caltech", "WORKS_AT"),
                ],
            )
        }
        scores = _score_relationships(preds, [gold])
        assert scores.n_predicted == 1
        assert scores.f1 == 1.0


class TestEdgeCases:
    def test_empty_goldens_yields_zero_metrics(self) -> None:
        scores = _score_entities({}, [])
        assert scores.precision == 0.0
        assert scores.recall == 0.0
        assert scores.f1 == 0.0

    def test_doc_with_no_predictions(self) -> None:
        gold = _golden("d1", [("Sheldon", "Character")])
        scores = _score_entities({}, [gold])
        # No predictions → recall 0, precision 0 (vacuous), f1 0.
        assert scores.recall == 0.0
        assert scores.precision == 0.0
        assert scores.f1 == 0.0
