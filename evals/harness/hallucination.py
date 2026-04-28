"""Hallucination-risk metrics for the eval harness (TODO-110).

Implements the cheap, structural signals from the Sprint 2 hallucination
metrics tier:

- **110.a — evidence grounding rate**: a relationship is grounded if both its
  source and target entity names (or any alias) appear in the cited
  ``evidence_span``. Substring match is the floor; rapidfuzz partial-ratio
  catches inflectional / case variation.
- **110.c — predicate type-signature check**: a small map of canonical
  ``predicate → (allowed_subject_types, allowed_object_types)``. Relationships
  whose endpoints don't match the predicate's signature are flagged. Unknown
  predicates pass — this is a precision gate, not a vocabulary lock.

Why no calibration ECE (110.b) yet: ECE needs ≥50 golden entries to be
statistically meaningful. Lands when the golden set is fully populated.

The output of :func:`score_extraction` plugs into ``RunResult`` and the
publish gate (``gates.evaluate``) — Sprint 2.5+ wiring extends ``gates`` to
threshold-block on a regression in either rate.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from knowledge_graph.extractor.schemas import (
    ExtractedEntity,
    ExtractedRelationship,
    Extraction,
)

# Unknown predicates are allowed (return ``True`` from the type check) so the
# vocabulary can grow without blocking publishes. Known predicates are checked
# strictly. Subject/object lists are entity-type strings from
# ``knowledge_graph.extractor.schemas.ENTITY_TYPES``.
_DEFAULT_PREDICATE_TYPES: dict[str, tuple[frozenset[str], frozenset[str]]] = {
    "WORKS_AT": (frozenset({"Person", "Character"}), frozenset({"Organization", "Location"})),
    "MEMBER_OF": (frozenset({"Person", "Character"}), frozenset({"Organization"})),
    "MARRIED_TO": (frozenset({"Person", "Character"}), frozenset({"Person", "Character"})),
    "ROOMMATES_WITH": (frozenset({"Person", "Character"}), frozenset({"Person", "Character"})),
    "PORTRAYS": (frozenset({"Person"}), frozenset({"Character"})),
    "LOCATED_IN": (frozenset({"Location", "Organization"}), frozenset({"Location"})),
    "PART_OF": (
        frozenset({"Event", "Work", "Location", "Organization", "Concept"}),
        frozenset({"Event", "Work", "Location", "Organization", "Concept"}),
    ),
    "AUTHORED": (frozenset({"Person", "Character"}), frozenset({"Work"})),
    "FOUNDED_BY": (frozenset({"Organization"}), frozenset({"Person", "Character"})),
}

_GROUNDING_FUZZ_THRESHOLD = 85


@dataclass(frozen=True)
class HallucinationReport:
    """Per-extraction hallucination signals (one document, one chunk OR aggregated)."""

    n_relationships: int = 0
    n_grounded: int = 0
    n_type_signature_ok: int = 0
    flagged: list[str] = field(default_factory=list)

    @property
    def evidence_grounding_rate(self) -> float:
        if self.n_relationships == 0:
            return 1.0
        return self.n_grounded / self.n_relationships

    @property
    def predicate_type_ok_rate(self) -> float:
        if self.n_relationships == 0:
            return 1.0
        return self.n_type_signature_ok / self.n_relationships

    def merge(self, other: HallucinationReport) -> HallucinationReport:
        """Combine two reports (used to aggregate per-chunk into per-doc / per-run)."""
        return HallucinationReport(
            n_relationships=self.n_relationships + other.n_relationships,
            n_type_signature_ok=self.n_type_signature_ok + other.n_type_signature_ok,
            n_grounded=self.n_grounded + other.n_grounded,
            flagged=[*self.flagged, *other.flagged],
        )


def score_extraction(
    extraction: Extraction,
    *,
    predicate_types: Mapping[str, tuple[frozenset[str], frozenset[str]]] | None = None,
) -> HallucinationReport:
    """Compute grounding + predicate-type metrics for one chunk's extraction.

    Args:
        extraction: The validated extraction output for a chunk.
        predicate_types: Override the default predicate→types map (mostly for
            tests / per-domain customization).

    Returns:
        A :class:`HallucinationReport` capturing per-relationship checks.
    """
    type_map = predicate_types if predicate_types is not None else _DEFAULT_PREDICATE_TYPES
    name_to_entity: dict[str, ExtractedEntity] = {e.name: e for e in extraction.entities}

    n = len(extraction.relationships)
    grounded = 0
    type_ok = 0
    flagged: list[str] = []

    for rel in extraction.relationships:
        ground_source = _is_grounded(rel.source, name_to_entity, rel.evidence_span)
        ground_target = _is_grounded(rel.target, name_to_entity, rel.evidence_span)
        if ground_source and ground_target:
            grounded += 1
        else:
            missing = []
            if not ground_source:
                missing.append(f"source {rel.source!r}")
            if not ground_target:
                missing.append(f"target {rel.target!r}")
            flagged.append(
                f"ungrounded[{rel.predicate}]: "
                + ", ".join(missing)
                + f" not in evidence span: {rel.evidence_span[:80]!r}"
            )

        if _predicate_signature_ok(rel, name_to_entity, type_map):
            type_ok += 1
        else:
            src_t = name_to_entity.get(rel.source)
            tgt_t = name_to_entity.get(rel.target)
            allowed = type_map.get(rel.predicate)
            flagged.append(
                f"type-violation[{rel.predicate}]: "
                f"({src_t.type if src_t else '?'} -> {tgt_t.type if tgt_t else '?'}) "
                f"not in {tuple(map(set, allowed)) if allowed else 'unknown'}"
            )

    return HallucinationReport(
        n_relationships=n,
        n_grounded=grounded,
        n_type_signature_ok=type_ok,
        flagged=flagged,
    )


def aggregate(reports: Iterable[HallucinationReport]) -> HallucinationReport:
    """Combine per-chunk reports into a single run-level report."""
    out = HallucinationReport()
    for r in reports:
        out = out.merge(r)
    return out


# ─────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────


def _is_grounded(
    entity_name: str,
    name_to_entity: Mapping[str, ExtractedEntity],
    span: str,
) -> bool:
    """An entity is grounded if its name OR any alias appears in ``span``.

    Substring match (case-insensitive) is the floor; rapidfuzz ``partial_ratio``
    catches reasonable inflectional drift (apostrophes, plurals).
    """
    span_l = span.lower()
    candidates = [entity_name]
    ent = name_to_entity.get(entity_name)
    if ent is not None:
        candidates.extend(ent.aliases)
    for surface in candidates:
        s = surface.strip().lower()
        if not s:
            continue
        if s in span_l:
            return True
        if fuzz.partial_ratio(s, span_l) >= _GROUNDING_FUZZ_THRESHOLD:
            return True
    return False


def _predicate_signature_ok(
    rel: ExtractedRelationship,
    name_to_entity: Mapping[str, ExtractedEntity],
    type_map: Mapping[str, tuple[frozenset[str], frozenset[str]]],
) -> bool:
    allowed = type_map.get(rel.predicate)
    if allowed is None:
        # Unknown predicate — soft pass; the gate is precision over recall.
        return True
    src = name_to_entity.get(rel.source)
    tgt = name_to_entity.get(rel.target)
    if src is None or tgt is None:
        return False
    subject_types, object_types = allowed
    return src.type in subject_types and tgt.type in object_types
