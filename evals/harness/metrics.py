"""Metric calculators for the eval harness.

Implements F1 / precision / recall (extraction) and Recall@k / MRR / nDCG (retrieval)
following the conventions described in SPEC §12. All functions are pure and
operate on plain Python types so they can be unit-tested without infrastructure.
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def precision_recall_f1(predicted: set[str], expected: set[str]) -> tuple[float, float, float]:
    """Standard set-based precision, recall, F1.

    Returns ``(0.0, 0.0, 0.0)`` when both sets are empty (no signal to score).
    """
    if not predicted and not expected:
        return 0.0, 0.0, 0.0
    tp = len(predicted & expected)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(expected) if expected else 0.0
    if precision + recall == 0.0:
        return precision, recall, 0.0
    f1 = 2 * precision * recall / (precision + recall)
    return precision, recall, f1


def coverage(predicted: set[str], expected: set[str]) -> float:
    """Fraction of expected items found in predicted (recall, by another name)."""
    if not expected:
        return 1.0  # nothing to cover, trivially covered
    return len(predicted & expected) / len(expected)


def per_type_f1(
    predicted_by_type: dict[str, set[str]],
    expected_by_type: dict[str, set[str]],
) -> dict[str, float]:
    """F1 per entity type. Types only in predicted (no expected) score 0.0."""
    types = set(predicted_by_type) | set(expected_by_type)
    out: dict[str, float] = {}
    for t in types:
        _, _, f1 = precision_recall_f1(
            predicted_by_type.get(t, set()),
            expected_by_type.get(t, set()),
        )
        out[t] = f1
    return out


def recall_at_k(retrieved: Sequence[str], expected: str, k: int) -> float:
    """1.0 if ``expected`` is in the top ``k`` of ``retrieved``, else 0.0."""
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    return 1.0 if expected in list(retrieved)[:k] else 0.0


def mean_reciprocal_rank(
    retrievals: Sequence[tuple[Sequence[str], str]],
) -> float:
    """MRR over a sequence of (retrieved_list, expected_id) pairs.

    Reciprocal rank is ``1 / position`` (1-indexed) of the first match, or 0 if
    no match. MRR is the mean over the sequence.
    """
    if not retrievals:
        return 0.0
    total = 0.0
    for retrieved, expected in retrievals:
        for idx, item in enumerate(retrieved, start=1):
            if item == expected:
                total += 1.0 / idx
                break
    return total / len(retrievals)


def ndcg_at_k(retrieved: Sequence[str], relevant: set[str], k: int) -> float:
    """Binary-relevance nDCG@k.

    DCG = sum over top-k of ``rel_i / log2(i + 1)`` (1-indexed).
    IDCG = DCG of an optimally-ordered list.
    """
    if k <= 0:
        raise ValueError(f"k must be positive, got {k}")
    if not relevant:
        return 0.0

    def dcg(items: Sequence[str]) -> float:
        return sum(
            (1.0 if item in relevant else 0.0) / math.log2(idx + 1)
            for idx, item in enumerate(items[:k], start=1)
        )

    actual = dcg(retrieved)
    ideal_count = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_count + 1))
    return actual / ideal if ideal > 0 else 0.0
