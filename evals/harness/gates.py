"""Publish-gate logic.

Combines absolute thresholds (e.g., ``f1_overall_min``) with regression deltas
(e.g., ``f1_drop_max`` vs. last published) and a variance gate (require
``min_runs_for_regression`` consecutive bad runs before declaring regression).
Implements the warmup-mode bypass per DEC-011.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .types import GateReport, RunResult


def evaluate(
    *,
    current: RunResult,
    history: Sequence[RunResult],
    thresholds: dict[str, Any],
) -> GateReport:
    """Decide whether to block publish.

    Args:
        current: The just-finished run.
        history: Prior runs in chronological order (oldest first).
        thresholds: Parsed ``thresholds.yaml`` content.

    Returns:
        A ``GateReport`` with ``outcome`` ∈ {``pass``, ``block``, ``warmup_bypass``}.
    """
    warmup_min = int(thresholds.get("warmup", {}).get("min_golden_entries", 50))
    if current.warmup or current.n_golden_entries < warmup_min:
        return GateReport(
            outcome="warmup_bypass",
            reasons=(
                f"warmup mode: golden set has {current.n_golden_entries} entries "
                f"(need ≥ {warmup_min} to gate publish)",
            ),
            details={"warmup_min": warmup_min},
        )

    reasons: list[str] = []

    extraction_t = thresholds.get("extraction", {})
    if current.extraction.f1_overall < extraction_t.get("f1_overall_min", 0.0):
        reasons.append(
            f"extraction.f1_overall {current.extraction.f1_overall:.3f} "
            f"< floor {extraction_t['f1_overall_min']}"
        )
    if current.extraction.coverage < extraction_t.get("coverage_min", 0.0):
        reasons.append(
            f"extraction.coverage {current.extraction.coverage:.3f} "
            f"< floor {extraction_t['coverage_min']}"
        )

    retrieval_t = thresholds.get("retrieval", {})
    if current.retrieval.recall_at_5 < retrieval_t.get("recall_at_5_min", 0.0):
        reasons.append(
            f"retrieval.recall_at_5 {current.retrieval.recall_at_5:.3f} "
            f"< floor {retrieval_t['recall_at_5_min']}"
        )
    if current.retrieval.mrr < retrieval_t.get("mrr_min", 0.0):
        reasons.append(
            f"retrieval.mrr {current.retrieval.mrr:.3f} < floor {retrieval_t['mrr_min']}"
        )

    cost_t = thresholds.get("cost", {})
    if current.cost.per_doc_usd > cost_t.get("per_doc_usd_max", float("inf")):
        reasons.append(
            f"cost.per_doc_usd ${current.cost.per_doc_usd:.4f} "
            f"> ceiling ${cost_t['per_doc_usd_max']}"
        )

    min_runs = int(thresholds.get("variance", {}).get("min_runs_for_regression", 3))
    regression_reasons = _regression_reasons(current, history, thresholds, min_runs)
    reasons.extend(regression_reasons)

    if reasons:
        return GateReport(outcome="block", reasons=tuple(reasons))
    return GateReport(outcome="pass", reasons=())


def _regression_reasons(
    current: RunResult,
    history: Sequence[RunResult],
    thresholds: dict[str, Any],
    min_runs: int,
) -> list[str]:
    """Return regression reasons only if confirmed across ``min_runs`` consecutive runs.

    Compares against the last published baseline (if available) and confirms the
    drop persists across the most recent ``min_runs - 1`` history entries plus
    the current run. Avoids tripping on a single noisy run (SPEC §12.6).
    """
    if not history:
        return []

    baseline = history[-1]
    extraction_t = thresholds.get("extraction", {})
    retrieval_t = thresholds.get("retrieval", {})
    out: list[str] = []

    f1_drop_max = float(extraction_t.get("f1_drop_max", 1.0))
    recall_drop_max = float(retrieval_t.get("recall_at_5_drop_max", 1.0))
    per_type_drop_max = float(extraction_t.get("per_type_f1_drop_max", 1.0))

    f1_drop = baseline.extraction.f1_overall - current.extraction.f1_overall
    if f1_drop > f1_drop_max and _persists(
        history,
        min_runs - 1,
        lambda r: baseline.extraction.f1_overall - r.extraction.f1_overall > f1_drop_max,
    ):
        out.append(
            f"extraction.f1_overall regressed by {f1_drop:.3f} "
            f"(threshold {f1_drop_max}) across {min_runs} runs"
        )

    recall_drop = baseline.retrieval.recall_at_5 - current.retrieval.recall_at_5
    if recall_drop > recall_drop_max and _persists(
        history,
        min_runs - 1,
        lambda r: baseline.retrieval.recall_at_5 - r.retrieval.recall_at_5 > recall_drop_max,
    ):
        out.append(
            f"retrieval.recall_at_5 regressed by {recall_drop:.3f} "
            f"(threshold {recall_drop_max}) across {min_runs} runs"
        )

    for type_name, current_f1 in current.extraction.per_type_f1.items():
        baseline_f1 = baseline.extraction.per_type_f1.get(type_name)
        if baseline_f1 is None:
            continue
        if (baseline_f1 - current_f1) > per_type_drop_max:
            out.append(
                f"extraction.per_type_f1[{type_name}] regressed by "
                f"{baseline_f1 - current_f1:.3f} (threshold {per_type_drop_max})"
            )

    return out


def _persists(
    history: Sequence[RunResult],
    n_required: int,
    predicate: Any,
) -> bool:
    """True if ``predicate`` holds for the most recent ``n_required`` history entries."""
    if n_required <= 0:
        return True
    recent = list(history)[-n_required:]
    if len(recent) < n_required:
        return False
    return all(predicate(r) for r in recent)
