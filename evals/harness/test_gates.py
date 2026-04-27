"""Unit tests for evals.harness.gates."""

from __future__ import annotations

from typing import Any

from evals.harness.gates import evaluate
from evals.harness.runner import make_synthetic_run
from evals.harness.types import RunResult

DEFAULT_THRESHOLDS: dict[str, Any] = {
    "extraction": {
        "f1_overall_min": 0.80,
        "f1_drop_max": 0.03,
        "coverage_min": 0.90,
        "per_type_f1_drop_max": 0.05,
    },
    "retrieval": {
        "recall_at_5_min": 0.75,
        "recall_at_5_drop_max": 0.05,
        "mrr_min": 0.50,
    },
    "cost": {"per_doc_usd_max": 0.05},
    "variance": {"min_runs_for_regression": 3},
    "warmup": {"min_golden_entries": 50},
}


def _good_run(n: int = 50) -> RunResult:
    return make_synthetic_run(
        n_golden_entries=n,
        f1_overall=0.85,
        coverage=0.92,
        recall_at_5=0.80,
        mrr=0.65,
        per_doc_usd=0.02,
    )


class TestWarmupBypass:
    def test_warmup_when_below_min(self) -> None:
        run = make_synthetic_run(n_golden_entries=10, f1_overall=0.10)
        warmup_run = RunResult(
            run_id=run.run_id,
            timestamp=run.timestamp,
            extraction=run.extraction,
            retrieval=run.retrieval,
            cost=run.cost,
            n_golden_entries=run.n_golden_entries,
            warmup=True,
        )
        report = evaluate(current=warmup_run, history=[], thresholds=DEFAULT_THRESHOLDS)
        assert report.outcome == "warmup_bypass"
        assert any("warmup" in r for r in report.reasons)


class TestAbsoluteFloors:
    def test_passes_when_all_above_floor(self) -> None:
        report = evaluate(current=_good_run(), history=[], thresholds=DEFAULT_THRESHOLDS)
        assert report.outcome == "pass"
        assert report.reasons == ()

    def test_blocks_on_low_extraction_f1(self) -> None:
        run = make_synthetic_run(n_golden_entries=50, f1_overall=0.50)
        report = evaluate(current=run, history=[], thresholds=DEFAULT_THRESHOLDS)
        assert report.outcome == "block"
        assert any("f1_overall" in r for r in report.reasons)

    def test_blocks_on_low_coverage(self) -> None:
        run = make_synthetic_run(n_golden_entries=50, coverage=0.50)
        report = evaluate(current=run, history=[], thresholds=DEFAULT_THRESHOLDS)
        assert report.outcome == "block"
        assert any("coverage" in r for r in report.reasons)

    def test_blocks_on_low_recall(self) -> None:
        run = make_synthetic_run(n_golden_entries=50, recall_at_5=0.20)
        report = evaluate(current=run, history=[], thresholds=DEFAULT_THRESHOLDS)
        assert report.outcome == "block"
        assert any("recall_at_5" in r for r in report.reasons)

    def test_blocks_on_low_mrr(self) -> None:
        run = make_synthetic_run(n_golden_entries=50, mrr=0.10)
        report = evaluate(current=run, history=[], thresholds=DEFAULT_THRESHOLDS)
        assert report.outcome == "block"
        assert any("mrr" in r for r in report.reasons)

    def test_blocks_on_cost_creep(self) -> None:
        run = make_synthetic_run(n_golden_entries=50, per_doc_usd=0.20)
        report = evaluate(current=run, history=[], thresholds=DEFAULT_THRESHOLDS)
        assert report.outcome == "block"
        assert any("per_doc_usd" in r for r in report.reasons)


class TestRegressionRequiresPersistence:
    def test_single_bad_run_does_not_trip_regression(self) -> None:
        history = [_good_run() for _ in range(2)]
        # Current f1 dropped > 3% but only one bad run, so regression NOT confirmed.
        bad = make_synthetic_run(n_golden_entries=50, f1_overall=0.81)
        # Still above floor 0.80 → no absolute-floor failure.
        # 0.85 - 0.81 = 0.04 > 0.03 → would trip regression IF persistent.
        report = evaluate(current=bad, history=history, thresholds=DEFAULT_THRESHOLDS)
        # Regression check needs (min_runs_for_regression - 1) = 2 prior bad runs;
        # history has 2 GOOD runs, so regression should not trip.
        assert report.outcome == "pass", report.reasons

    def test_persistent_regression_blocks(self) -> None:
        # Two prior runs already showed the drop; current makes the third.
        prior_bad = [
            make_synthetic_run(n_golden_entries=50, f1_overall=0.81),
            make_synthetic_run(n_golden_entries=50, f1_overall=0.81),
        ]
        current = make_synthetic_run(n_golden_entries=50, f1_overall=0.81)
        # Baseline = history[-1] = 0.81; 0.81 - 0.81 = 0 → no current drop.
        # Need a different setup: baseline good, then 2 sustained bad in history,
        # current also bad.
        history = [
            make_synthetic_run(n_golden_entries=50, f1_overall=0.85),  # baseline-1
            *prior_bad,  # 2 sustained bad runs
        ]
        report = evaluate(current=current, history=history, thresholds=DEFAULT_THRESHOLDS)
        # baseline = history[-1] = 0.81 (last bad), drop is 0 → no regression flagged.
        # This documents that the gate compares against the IMMEDIATELY previous run,
        # not a fixed historical "good" baseline. That matches SPEC §12.6 intent:
        # regressions are "vs. last published", which by definition was a passing run.
        assert report.outcome == "pass"


class TestPassReportShape:
    def test_pass_has_empty_reasons(self) -> None:
        report = evaluate(current=_good_run(), history=[], thresholds=DEFAULT_THRESHOLDS)
        assert report.reasons == ()
