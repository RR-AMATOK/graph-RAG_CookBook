"""Eval harness runner — Sprint 1 skeleton.

Wires together: golden-set load → metric computation → gate evaluation → history append.

Sprint 1 status: extraction outputs aren't produced yet (Sprint 2+), so this
runner exercises the gate logic against synthetic inputs when invoked directly.
The wiring is real; only the source of metrics changes when extraction lands.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from .types import (
    CostMetrics,
    ExpectedEntity,
    ExpectedRelationship,
    ExtractionMetrics,
    GoldenEntry,
    RetrievalMetrics,
    RunResult,
)

EVAL_ROOT = Path(__file__).resolve().parents[1]
THRESHOLDS_PATH = EVAL_ROOT / "thresholds.yaml"
GOLDEN_SET_PATH = EVAL_ROOT / "golden_set.jsonl"
HISTORY_PATH = EVAL_ROOT / "history.jsonl"


def load_thresholds(path: Path = THRESHOLDS_PATH) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def load_golden_set(path: Path = GOLDEN_SET_PATH) -> list[GoldenEntry]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    entries: list[GoldenEntry] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{line_no} invalid JSON: {exc}") from exc
            entries.append(_parse_golden_entry(row, source=f"{path}:{line_no}"))
    return entries


def _parse_golden_entry(row: dict[str, Any], *, source: str) -> GoldenEntry:
    try:
        return GoldenEntry(
            doc_id=row["doc_id"],
            canonical_path=row["canonical_path"],
            expected_entities=tuple(
                ExpectedEntity(
                    name=e["name"],
                    type=e["type"],
                    aliases=tuple(e.get("aliases", [])),
                )
                for e in row.get("expected_entities", [])
            ),
            expected_relationships=tuple(
                ExpectedRelationship(
                    source=r["source"],
                    target=r["target"],
                    predicate=r["predicate"],
                )
                for r in row.get("expected_relationships", [])
            ),
            expected_top_doc_for_query=dict(row.get("expected_top_doc_for_query", {})),
            notes=row.get("notes", ""),
        )
    except KeyError as exc:
        raise ValueError(f"{source} missing required field: {exc}") from exc


def append_history(result: RunResult, path: Path = HISTORY_PATH) -> None:
    payload: dict[str, Any] = {
        "run_id": result.run_id,
        "timestamp": result.timestamp,
        "warmup": result.warmup,
        "n_golden_entries": result.n_golden_entries,
        "extraction": {
            "f1_overall": result.extraction.f1_overall,
            "coverage": result.extraction.coverage,
            "precision_overall": result.extraction.precision_overall,
            "recall_overall": result.extraction.recall_overall,
            "per_type_f1": result.extraction.per_type_f1,
        },
        "retrieval": {
            "recall_at_5": result.retrieval.recall_at_5,
            "mrr": result.retrieval.mrr,
            "ndcg_at_10": result.retrieval.ndcg_at_10,
        },
        "cost": {
            "per_doc_usd": result.cost.per_doc_usd,
            "total_usd": result.cost.total_usd,
        },
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(payload, sort_keys=True) + "\n")


def make_synthetic_run(
    *,
    n_golden_entries: int,
    f1_overall: float = 0.85,
    coverage: float = 0.92,
    recall_at_5: float = 0.80,
    mrr: float = 0.65,
    per_doc_usd: float = 0.02,
) -> RunResult:
    """Build a synthetic ``RunResult`` for harness self-testing.

    Used by the Sprint 1 smoke run and unit tests. Replaced by real extraction
    output in Sprint 2+.
    """
    return RunResult(
        run_id=f"synthetic-{datetime.now(UTC).isoformat()}",
        timestamp=datetime.now(UTC).isoformat(),
        extraction=ExtractionMetrics(
            f1_overall=f1_overall,
            coverage=coverage,
            per_type_f1={"Character": f1_overall, "Organization": f1_overall},
            precision_overall=f1_overall,
            recall_overall=coverage,
        ),
        retrieval=RetrievalMetrics(
            recall_at_5=recall_at_5,
            mrr=mrr,
            ndcg_at_10=mrr,
        ),
        cost=CostMetrics(per_doc_usd=per_doc_usd, total_usd=per_doc_usd * 100),
        n_golden_entries=n_golden_entries,
        warmup=False,
    )


def main() -> int:
    """Sprint 1 entry point — exercises load + gate path on a synthetic run.

    Real extraction wiring lands in Sprint 2+. Until then ``main`` proves the
    harness pipeline is intact and outputs a sensible report.
    """
    from . import gates  # local import to keep module load fast

    thresholds = load_thresholds()
    golden = load_golden_set()
    n = len(golden)
    warmup_min = int(thresholds.get("warmup", {}).get("min_golden_entries", 50))
    is_warmup = n < warmup_min

    synthetic = make_synthetic_run(n_golden_entries=n)
    if is_warmup:
        synthetic = RunResult(
            run_id=synthetic.run_id,
            timestamp=synthetic.timestamp,
            extraction=synthetic.extraction,
            retrieval=synthetic.retrieval,
            cost=synthetic.cost,
            n_golden_entries=n,
            warmup=True,
        )

    report = gates.evaluate(current=synthetic, history=[], thresholds=thresholds)
    print(f"[eval] golden_entries={n} warmup={is_warmup}")
    print(f"[eval] gate outcome: {report.outcome}")
    for reason in report.reasons:
        print(f"[eval]   - {reason}")

    append_history(synthetic)
    return 0 if report.outcome != "block" else 1


if __name__ == "__main__":
    raise SystemExit(main())
