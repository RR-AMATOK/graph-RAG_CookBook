"""Golden-set scoring + prompt comparison for the eval harness.

This is what turns ``kg eval --compare-prompts v0,v1`` from a hand-wave into
a measurable A/B. The flow:

1. For each prompt version, run the corpus through ``extract_corpus`` (cache
   handles re-runs at the same prompt version cheaply; bumping the version
   forces a fresh extraction).
2. Aggregate per-doc predictions (entities + relationships) by union across
   chunks of that doc.
3. Score each doc's predictions against the matching golden entry using
   normalized + fuzzy matching at the entity level and triple-equality at
   the relationship level.
4. Combine reference-based scores (golden F1, coverage) with the existing
   reference-free structural scores (chunk_grounding, span_grounding,
   predicate_type_ok) and cost.
5. Diff two ``PromptEvaluation`` objects into a ``ComparisonReport``.

What this is NOT:
- A calibration ECE implementation (TODO-110.b — needs ≥50 goldens).
- A statistical significance test — the deltas are point estimates.
- A golden-set authoring tool — that's `evals/README.md` + the user.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from rapidfuzz import fuzz

from evals.harness.runner import load_golden_set
from evals.harness.types import GoldenEntry
from knowledge_graph.extractor.extractor import Extractor
from knowledge_graph.extractor.schemas import (
    ExtractedEntity,
    ExtractedRelationship,
    Extraction,
)
from knowledge_graph.pipeline import IngestSettings, extract_corpus

logger = logging.getLogger(__name__)


# Entity-name fuzzy-match threshold. Two entities are the same iff their
# normalized names match exactly OR rapidfuzz.token_set_ratio >= this.
_ENTITY_MATCH_THRESHOLD = 90

# Stopwords removed during normalization so "The Pilot" matches "Pilot" but
# trivial connectors don't false-match across distinct entities.
_NAME_STOPWORDS = frozenset({"the", "a", "an", "of", "in", "on", "at", "to", "for", "and"})


# ─────────────────────────────────────────────────────────────────────
# Result types
# ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class EntityScores:
    """Per-type and overall entity precision/recall/F1 + coverage."""

    n_predicted: int
    n_expected: int
    n_true_positive: int
    precision: float
    recall: float
    f1: float
    coverage: float  # = recall (alias for SPEC-§12 thresholds vocabulary)
    per_type_f1: dict[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class RelationshipScores:
    """Triple-level F1 over (norm(source), norm(target), predicate)."""

    n_predicted: int
    n_expected: int
    n_true_positive: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True)
class PromptEvaluation:
    """Everything we know about one prompt run on a corpus + goldens."""

    prompt_version: str
    n_docs: int
    n_chunks: int
    n_chunks_cache_hits: int
    n_chunks_extracted: int
    # Reference-free structural metrics (from extract_corpus → hallucination).
    chunk_grounding_rate: float
    span_grounding_rate: float
    predicate_type_ok_rate: float
    # Reference-based metrics (require goldens).
    has_goldens: bool
    n_goldens: int
    entity: EntityScores | None = None
    relationship: RelationshipScores | None = None
    # Cost.
    cost_input_tokens: int = 0
    cost_output_tokens: int = 0
    cost_cache_read_tokens: int = 0
    cost_usd: float = 0.0


@dataclass(frozen=True)
class ComparisonReport:
    """Two evaluations + the deltas a publish gate would care about."""

    baseline: PromptEvaluation
    candidate: PromptEvaluation
    # Deltas (candidate - baseline). Positive = candidate is better for
    # rate-style metrics; positive = candidate spent more for cost.
    delta_chunk_grounding: float
    delta_span_grounding: float
    delta_predicate_type_ok: float
    delta_entity_f1: float | None
    delta_entity_coverage: float | None
    delta_relationship_f1: float | None
    delta_cost_usd: float

    def write_json(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True, default=str),
            encoding="utf-8",
        )


# ─────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────


def evaluate_prompt(
    *,
    prompt_version: str,
    settings: IngestSettings,
    goldens: list[GoldenEntry] | None = None,
) -> PromptEvaluation:
    """Run the corpus once at ``prompt_version`` and score it.

    The extractor's prompt_version is overridden in a fresh
    ``ExtractorSettings`` copy so the caller's settings are not mutated.
    Cache lookups continue to work — different prompt versions write to
    different cache keys.
    """
    from dataclasses import replace as _replace

    ex_settings = _replace(settings.extractor, prompt_version=prompt_version)
    ex_settings = _replace(
        ex_settings,
        cache_root=ex_settings.cache_root or settings.cache_dir,
    )
    extractor = Extractor(ex_settings)
    eval_settings = _replace(settings, extractor=ex_settings)

    extracted = extract_corpus(settings=eval_settings, extractor=extractor)

    # Aggregate per-chunk extractions into per-doc predictions.
    predictions_by_doc: dict[str, _DocPrediction] = {}
    chunk_to_doc = {c.chunk_id: c.doc_id for c in extracted.chunks}
    for chunk_id, result in extracted.extractions.items():
        doc_id = chunk_to_doc[chunk_id]
        agg = predictions_by_doc.setdefault(doc_id, _DocPrediction())
        agg.merge(result.extraction)

    entity_scores: EntityScores | None = None
    relationship_scores: RelationshipScores | None = None
    has_goldens = bool(goldens)

    if goldens:
        entity_scores = _score_entities(predictions_by_doc, goldens)
        relationship_scores = _score_relationships(predictions_by_doc, goldens)

    return PromptEvaluation(
        prompt_version=prompt_version,
        n_docs=len(extracted.docs),
        n_chunks=len(extracted.chunks),
        n_chunks_cache_hits=extracted.chunks_cache_hits,
        n_chunks_extracted=extracted.chunks_extracted,
        chunk_grounding_rate=extracted.hallucination.chunk_grounding_rate,
        span_grounding_rate=extracted.hallucination.evidence_grounding_rate,
        predicate_type_ok_rate=extracted.hallucination.predicate_type_ok_rate,
        has_goldens=has_goldens,
        n_goldens=len(goldens) if goldens else 0,
        entity=entity_scores,
        relationship=relationship_scores,
        cost_input_tokens=extracted.cost_input_tokens,
        cost_output_tokens=extracted.cost_output_tokens,
        cost_cache_read_tokens=extracted.cost_cache_read_tokens,
        cost_usd=extracted.cost_usd,
    )


def compare_prompts(
    *,
    baseline_version: str,
    candidate_version: str,
    settings: IngestSettings,
    goldens_path: Path | None = None,
) -> ComparisonReport:
    """Run both prompts on the corpus and return a comparison report.

    Args:
        baseline_version: Usually the currently-shipping prompt (e.g., ``"v0"``).
        candidate_version: The challenger (e.g., ``"v1"``).
        settings: Ingest settings — paths, chunker config, base extractor config.
        goldens_path: Path to ``golden_set.jsonl``. ``None`` skips reference-based metrics.
    """
    goldens: list[GoldenEntry] = []
    if goldens_path is not None and goldens_path.exists() and goldens_path.stat().st_size > 0:
        goldens = load_golden_set(goldens_path)
        logger.info("loaded %d golden entries from %s", len(goldens), goldens_path)
    else:
        logger.info("no goldens supplied; comparison limited to structural metrics")

    baseline = evaluate_prompt(
        prompt_version=baseline_version, settings=settings, goldens=goldens or None
    )
    candidate = evaluate_prompt(
        prompt_version=candidate_version, settings=settings, goldens=goldens or None
    )

    return ComparisonReport(
        baseline=baseline,
        candidate=candidate,
        delta_chunk_grounding=candidate.chunk_grounding_rate - baseline.chunk_grounding_rate,
        delta_span_grounding=candidate.span_grounding_rate - baseline.span_grounding_rate,
        delta_predicate_type_ok=(
            candidate.predicate_type_ok_rate - baseline.predicate_type_ok_rate
        ),
        delta_entity_f1=(
            candidate.entity.f1 - baseline.entity.f1
            if candidate.entity and baseline.entity
            else None
        ),
        delta_entity_coverage=(
            candidate.entity.coverage - baseline.entity.coverage
            if candidate.entity and baseline.entity
            else None
        ),
        delta_relationship_f1=(
            candidate.relationship.f1 - baseline.relationship.f1
            if candidate.relationship and baseline.relationship
            else None
        ),
        delta_cost_usd=candidate.cost_usd - baseline.cost_usd,
    )


def format_comparison(report: ComparisonReport) -> str:
    """Render a side-by-side text table for human inspection."""
    b = report.baseline
    c = report.candidate

    lines = [
        f"# Prompt comparison: {b.prompt_version} (baseline) vs {c.prompt_version} (candidate)",
        f"# Generated at {datetime.now(UTC).isoformat()}",
        "",
        f"docs={b.n_docs}  chunks={b.n_chunks}  goldens={b.n_goldens}",
        "",
        f"{'metric':<32}{'baseline':>14}{'candidate':>14}{'delta':>12}",
        "-" * 72,
    ]

    def row(label: str, base: float | None, cand: float | None, delta: float | None) -> str:
        b_s = f"{base:.4f}" if base is not None else "—"
        c_s = f"{cand:.4f}" if cand is not None else "—"
        d_s = f"{delta:+.4f}" if delta is not None else "—"
        return f"{label:<32}{b_s:>14}{c_s:>14}{d_s:>12}"

    lines.append(
        row(
            "chunk_grounding_rate",
            b.chunk_grounding_rate,
            c.chunk_grounding_rate,
            report.delta_chunk_grounding,
        )
    )
    lines.append(
        row(
            "span_grounding_rate",
            b.span_grounding_rate,
            c.span_grounding_rate,
            report.delta_span_grounding,
        )
    )
    lines.append(
        row(
            "predicate_type_ok_rate",
            b.predicate_type_ok_rate,
            c.predicate_type_ok_rate,
            report.delta_predicate_type_ok,
        )
    )

    if b.entity and c.entity:
        lines.append(row("entity_f1", b.entity.f1, c.entity.f1, report.delta_entity_f1))
        lines.append(
            row(
                "entity_coverage",
                b.entity.coverage,
                c.entity.coverage,
                report.delta_entity_coverage,
            )
        )
    if b.relationship and c.relationship:
        lines.append(
            row(
                "relationship_f1",
                b.relationship.f1,
                c.relationship.f1,
                report.delta_relationship_f1,
            )
        )

    lines.append("")
    lines.append(
        f"{'cost_usd':<32}{b.cost_usd:>14.4f}{c.cost_usd:>14.4f}{report.delta_cost_usd:>+12.4f}"
    )
    lines.append(
        f"{'tokens (in/out)':<32}"
        f"{b.cost_input_tokens:>7}/{b.cost_output_tokens:<6}"
        f"{c.cost_input_tokens:>7}/{c.cost_output_tokens:<6}"
    )

    if b.entity and c.entity and (b.entity.per_type_f1 or c.entity.per_type_f1):
        lines.append("")
        lines.append("Per-type entity F1:")
        types = sorted(set(b.entity.per_type_f1) | set(c.entity.per_type_f1))
        for t in types:
            lines.append(
                row(
                    f"  {t}",
                    b.entity.per_type_f1.get(t, 0.0),
                    c.entity.per_type_f1.get(t, 0.0),
                    c.entity.per_type_f1.get(t, 0.0) - b.entity.per_type_f1.get(t, 0.0),
                )
            )

    return "\n".join(lines) + "\n"


# ─────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _DocPrediction:
    """Per-doc aggregation of chunk-level extractions."""

    entities: list[ExtractedEntity] = field(default_factory=list)
    relationships: list[ExtractedRelationship] = field(default_factory=list)

    def merge(self, ext: Extraction) -> None:
        self.entities.extend(ext.entities)
        self.relationships.extend(ext.relationships)


def _normalize_name(name: str) -> str:
    """Normalize an entity name for matching: lowercase, drop stopwords + punctuation."""
    s = name.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    tokens = [t for t in s.split() if t not in _NAME_STOPWORDS]
    return " ".join(tokens) if tokens else s


def _entity_match(
    predicted_name: str, expected_name: str, expected_aliases: Sequence[str] = ()
) -> bool:
    """A predicted entity name matches an expected name (or any alias) if
    normalized names agree exactly OR rapidfuzz token_set_ratio crosses the
    threshold."""
    p_norm = _normalize_name(predicted_name)
    if not p_norm:
        return False
    for surface in (expected_name, *expected_aliases):
        c_norm = _normalize_name(surface)
        if not c_norm:
            continue
        if p_norm == c_norm:
            return True
        if fuzz.token_set_ratio(p_norm, c_norm) >= _ENTITY_MATCH_THRESHOLD:
            return True
    return False


def _score_entities(
    predictions_by_doc: dict[str, _DocPrediction],
    goldens: Iterable[GoldenEntry],
) -> EntityScores:
    """Aggregate entity precision/recall/F1 across all goldens."""
    n_predicted = 0
    n_expected = 0
    n_tp = 0
    per_type_tp: dict[str, int] = {}
    per_type_predicted: dict[str, int] = {}
    per_type_expected: dict[str, int] = {}

    for golden in goldens:
        pred = predictions_by_doc.get(golden.doc_id)
        # Dedup predicted entities within this doc by (norm_name, type)
        # — multiple chunks emit the same entity; we count it once per doc.
        seen_pred: set[tuple[str, str]] = set()
        unique_pred: list[ExtractedEntity] = []
        if pred is not None:
            for entity in pred.entities:
                key = (_normalize_name(entity.name), entity.type)
                if key in seen_pred:
                    continue
                seen_pred.add(key)
                unique_pred.append(entity)
        n_predicted += len(unique_pred)
        n_expected += len(golden.expected_entities)

        # Track per-type counts.
        for entity in unique_pred:
            per_type_predicted[entity.type] = per_type_predicted.get(entity.type, 0) + 1
        for expected in golden.expected_entities:
            per_type_expected[expected.type] = per_type_expected.get(expected.type, 0) + 1

        # Match each expected entity against the predicted set; one-to-one.
        matched_pred_idx: set[int] = set()
        for expected in golden.expected_entities:
            for i, p in enumerate(unique_pred):
                if i in matched_pred_idx:
                    continue
                if p.type != expected.type:
                    continue
                if _entity_match(p.name, expected.name, list(expected.aliases)):
                    n_tp += 1
                    per_type_tp[expected.type] = per_type_tp.get(expected.type, 0) + 1
                    matched_pred_idx.add(i)
                    break

    precision = n_tp / n_predicted if n_predicted else 0.0
    recall = n_tp / n_expected if n_expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    per_type_f1: dict[str, float] = {}
    for t in set(per_type_predicted) | set(per_type_expected):
        tp = per_type_tp.get(t, 0)
        n_p = per_type_predicted.get(t, 0)
        n_e = per_type_expected.get(t, 0)
        prec = tp / n_p if n_p else 0.0
        rec = tp / n_e if n_e else 0.0
        per_type_f1[t] = 2 * prec * rec / (prec + rec) if (prec + rec) else 0.0

    return EntityScores(
        n_predicted=n_predicted,
        n_expected=n_expected,
        n_true_positive=n_tp,
        precision=precision,
        recall=recall,
        f1=f1,
        coverage=recall,
        per_type_f1=per_type_f1,
    )


def _score_relationships(
    predictions_by_doc: dict[str, _DocPrediction],
    goldens: Iterable[GoldenEntry],
) -> RelationshipScores:
    """Triple-level F1: a relationship matches iff (norm(source), norm(target),
    predicate) agrees AND both endpoints fuzzy-match through the entity matcher.

    Direction matters — (A, B, P) and (B, A, P) are distinct triples.
    """
    n_predicted = 0
    n_expected = 0
    n_tp = 0

    for golden in goldens:
        pred = predictions_by_doc.get(golden.doc_id)
        # Dedup predicted relationships within this doc by triple key.
        seen: set[tuple[str, str, str]] = set()
        unique_pred: list[ExtractedRelationship] = []
        if pred is not None:
            for r in pred.relationships:
                key = (_normalize_name(r.source), _normalize_name(r.target), r.predicate)
                if key in seen:
                    continue
                seen.add(key)
                unique_pred.append(r)
        n_predicted += len(unique_pred)
        n_expected += len(golden.expected_relationships)

        # Build a name → (canonical_name, aliases) index for endpoint matching.
        # ExpectedEntity is a frozen dataclass; we project to plain tuples.
        expected_by_name: dict[str, list[tuple[str, list[str]]]] = {}
        for ent in golden.expected_entities:
            expected_by_name.setdefault(ent.name, []).append((ent.name, list(ent.aliases)))

        matched_pred_idx: set[int] = set()
        for exp_rel in golden.expected_relationships:
            # If goldens omit an endpoint from expected_entities (legitimate),
            # fall back to the bare relationship name with no aliases.
            src_candidates = expected_by_name.get(exp_rel.source) or [(exp_rel.source, [])]
            tgt_candidates = expected_by_name.get(exp_rel.target) or [(exp_rel.target, [])]

            for i, p in enumerate(unique_pred):
                if i in matched_pred_idx:
                    continue
                if p.predicate != exp_rel.predicate:
                    continue
                src_ok = any(
                    _entity_match(p.source, name, aliases) for name, aliases in src_candidates
                )
                tgt_ok = any(
                    _entity_match(p.target, name, aliases) for name, aliases in tgt_candidates
                )
                if src_ok and tgt_ok:
                    n_tp += 1
                    matched_pred_idx.add(i)
                    break

    precision = n_tp / n_predicted if n_predicted else 0.0
    recall = n_tp / n_expected if n_expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return RelationshipScores(
        n_predicted=n_predicted,
        n_expected=n_expected,
        n_true_positive=n_tp,
        precision=precision,
        recall=recall,
        f1=f1,
    )
