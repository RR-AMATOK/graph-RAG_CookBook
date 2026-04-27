"""Unit tests for evals.harness.metrics."""

from __future__ import annotations

import math

import pytest

from evals.harness.metrics import (
    coverage,
    mean_reciprocal_rank,
    ndcg_at_k,
    per_type_f1,
    precision_recall_f1,
    recall_at_k,
)


class TestPrecisionRecallF1:
    def test_perfect_match(self) -> None:
        p, r, f = precision_recall_f1({"a", "b", "c"}, {"a", "b", "c"})
        assert (p, r, f) == (1.0, 1.0, 1.0)

    def test_no_overlap(self) -> None:
        p, r, f = precision_recall_f1({"a"}, {"b"})
        assert (p, r, f) == (0.0, 0.0, 0.0)

    def test_partial(self) -> None:
        p, r, f = precision_recall_f1({"a", "b"}, {"b", "c"})
        assert p == 0.5
        assert r == 0.5
        assert f == 0.5

    def test_both_empty_returns_zeros(self) -> None:
        assert precision_recall_f1(set(), set()) == (0.0, 0.0, 0.0)

    def test_empty_predicted(self) -> None:
        p, r, f = precision_recall_f1(set(), {"a"})
        assert (p, r, f) == (0.0, 0.0, 0.0)


class TestCoverage:
    def test_full_cover(self) -> None:
        assert coverage({"a", "b"}, {"a", "b"}) == 1.0

    def test_partial(self) -> None:
        assert coverage({"a"}, {"a", "b"}) == 0.5

    def test_empty_expected_is_trivially_covered(self) -> None:
        assert coverage(set(), set()) == 1.0


class TestPerTypeF1:
    def test_per_type_isolated(self) -> None:
        out = per_type_f1(
            predicted_by_type={"Character": {"Sheldon"}, "Org": {"Caltech"}},
            expected_by_type={"Character": {"Sheldon"}, "Org": {"MIT"}},
        )
        assert out["Character"] == 1.0
        assert out["Org"] == 0.0

    def test_type_only_in_predicted_scores_zero(self) -> None:
        out = per_type_f1(
            predicted_by_type={"Bogus": {"x"}},
            expected_by_type={},
        )
        assert out["Bogus"] == 0.0


class TestRecallAtK:
    def test_present_in_top_k(self) -> None:
        assert recall_at_k(["a", "b", "c"], "b", k=2) == 1.0

    def test_outside_top_k(self) -> None:
        assert recall_at_k(["a", "b", "c"], "c", k=2) == 0.0

    def test_invalid_k(self) -> None:
        with pytest.raises(ValueError):
            recall_at_k(["a"], "a", k=0)


class TestMRR:
    def test_first_position(self) -> None:
        assert mean_reciprocal_rank([(["a", "b"], "a")]) == 1.0

    def test_second_position(self) -> None:
        assert mean_reciprocal_rank([(["a", "b"], "b")]) == 0.5

    def test_no_match(self) -> None:
        assert mean_reciprocal_rank([(["a", "b"], "z")]) == 0.0

    def test_empty_input(self) -> None:
        assert mean_reciprocal_rank([]) == 0.0

    def test_average(self) -> None:
        result = mean_reciprocal_rank([(["a", "b"], "a"), (["a", "b"], "b")])
        assert math.isclose(result, 0.75)


class TestNDCG:
    def test_perfect_ordering(self) -> None:
        assert ndcg_at_k(["a", "b"], {"a", "b"}, k=2) == 1.0

    def test_no_relevant_items(self) -> None:
        assert ndcg_at_k(["a", "b"], set(), k=2) == 0.0

    def test_relevant_at_back_loses(self) -> None:
        front = ndcg_at_k(["rel", "x", "y"], {"rel"}, k=3)
        back = ndcg_at_k(["x", "y", "rel"], {"rel"}, k=3)
        assert front > back

    def test_invalid_k(self) -> None:
        with pytest.raises(ValueError):
            ndcg_at_k(["a"], {"a"}, k=0)
