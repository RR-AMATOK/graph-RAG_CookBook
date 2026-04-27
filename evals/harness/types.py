"""Typed dataclasses for the eval harness."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class ExpectedEntity:
    name: str
    type: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExpectedRelationship:
    source: str
    target: str
    predicate: str


@dataclass(frozen=True)
class GoldenEntry:
    doc_id: str
    canonical_path: str
    expected_entities: tuple[ExpectedEntity, ...]
    expected_relationships: tuple[ExpectedRelationship, ...]
    expected_top_doc_for_query: dict[str, str] = field(default_factory=dict)
    notes: str = ""


@dataclass(frozen=True)
class ExtractionMetrics:
    """Per-run extraction metrics (SPEC §12.2 — extraction.* keys)."""

    f1_overall: float
    coverage: float
    per_type_f1: dict[str, float]
    precision_overall: float
    recall_overall: float


@dataclass(frozen=True)
class RetrievalMetrics:
    """Per-run retrieval metrics (SPEC §12.2 — retrieval.* keys)."""

    recall_at_5: float
    mrr: float
    ndcg_at_10: float


@dataclass(frozen=True)
class CostMetrics:
    per_doc_usd: float
    total_usd: float


@dataclass(frozen=True)
class RunResult:
    """Output of a single harness run (one row in history.jsonl)."""

    run_id: str
    timestamp: str
    extraction: ExtractionMetrics
    retrieval: RetrievalMetrics
    cost: CostMetrics
    n_golden_entries: int
    warmup: bool


GateOutcome = Literal["pass", "block", "warmup_bypass"]


@dataclass(frozen=True)
class GateReport:
    outcome: GateOutcome
    reasons: tuple[str, ...]
    details: dict[str, object] = field(default_factory=dict)
