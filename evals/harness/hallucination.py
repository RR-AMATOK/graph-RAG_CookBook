"""Hallucination-risk metrics for the eval harness (TODO-110).

Implements the cheap, structural signals from the Sprint 2 hallucination
metrics tier:

- **110.a — evidence grounding** (two flavors):
  - **span-grounding** (strict): both endpoint names appear in the cited
    ``evidence_span``. A writing-style indicator — Sonnet hits ~0.95+;
    Qwen3 hits ~0.10 because it cites name-free contextual spans.
  - **chunk-grounding** (lenient): both endpoint names appear anywhere in
    the source chunk. The actual *hallucination floor* — if a name isn't
    in the chunk at all, the relationship is invented. The publish gate
    thresholds on this metric.
- **110.c — predicate type-signature check**: a small map of canonical
  ``predicate → (allowed_subject_types, allowed_object_types)``. Relationships
  whose endpoints don't match the predicate's signature are flagged. Unknown
  predicates pass — this is a precision gate, not a vocabulary lock.

Why no calibration ECE (110.b) yet: ECE needs ≥50 golden entries to be
statistically meaningful. Lands when the golden set is fully populated.
"""

from __future__ import annotations

import re
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

# Tokens skipped in token-level grounding so trivial words like "the"/"and"
# can't false-match a multi-word entity name. Honorifics and short connectors
# only — content words like "Big"/"Bang" stay because they're often the
# discriminating part of a name.
_GROUNDING_STOPWORDS: frozenset[str] = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "on",
        "at",
        "to",
        "for",
        "with",
        "by",
        "is",
        "as",
        "dr",
        "mr",
        "mrs",
        "ms",
        "st",
        "sir",
        "lord",
        "lady",
    }
)
# Tokens shorter than this are too noisy to match on their own (e.g., "Mr",
# "St", "5th"). Names are reduced to tokens >= this length before matching.
_MIN_TOKEN_LEN = 4


@dataclass(frozen=True)
class HallucinationReport:
    """Per-extraction hallucination signals (one document, one chunk OR aggregated)."""

    n_relationships: int = 0
    n_grounded: int = 0  # strict: name in cited evidence_span
    n_chunk_grounded: int = 0  # lenient: name anywhere in chunk (publish-gate signal)
    n_type_signature_ok: int = 0
    flagged: list[str] = field(default_factory=list)

    @property
    def evidence_grounding_rate(self) -> float:
        """Strict: both endpoints' names appear in the cited evidence_span."""
        if self.n_relationships == 0:
            return 1.0
        return self.n_grounded / self.n_relationships

    @property
    def chunk_grounding_rate(self) -> float:
        """Lenient: both endpoints' names appear anywhere in the source chunk.

        Equals :attr:`evidence_grounding_rate` when ``chunk_text`` was not
        supplied to :func:`score_extraction`.
        """
        if self.n_relationships == 0:
            return 1.0
        return self.n_chunk_grounded / self.n_relationships

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
            n_chunk_grounded=self.n_chunk_grounded + other.n_chunk_grounded,
            flagged=[*self.flagged, *other.flagged],
        )


def score_extraction(
    extraction: Extraction,
    *,
    chunk_text: str | None = None,
    predicate_types: Mapping[str, tuple[frozenset[str], frozenset[str]]] | None = None,
) -> HallucinationReport:
    """Compute grounding + predicate-type metrics for one chunk's extraction.

    Args:
        extraction: The validated extraction output for a chunk.
        chunk_text: The full chunk body. When supplied, enables the lenient
            *chunk-grounding* metric — a relationship is chunk-grounded iff
            both endpoint names appear anywhere in the chunk. This is the
            actual hallucination floor. When ``None``, chunk-grounding falls
            back to span-grounding so existing callers see no behavior change.
        predicate_types: Override the default predicate→types map.

    Returns:
        A :class:`HallucinationReport` with both strict (span) and lenient
        (chunk) grounding rates populated.
    """
    type_map = predicate_types if predicate_types is not None else _DEFAULT_PREDICATE_TYPES
    name_to_entity: dict[str, ExtractedEntity] = {e.name: e for e in extraction.entities}

    n = len(extraction.relationships)
    span_grounded = 0
    chunk_grounded = 0
    type_ok = 0
    flagged: list[str] = []

    for rel in extraction.relationships:
        sg_source = _is_grounded(rel.source, name_to_entity, rel.evidence_span)
        sg_target = _is_grounded(rel.target, name_to_entity, rel.evidence_span)
        span_ok = sg_source and sg_target

        if chunk_text is not None:
            cg_source = sg_source or _is_grounded(rel.source, name_to_entity, chunk_text)
            cg_target = sg_target or _is_grounded(rel.target, name_to_entity, chunk_text)
        else:
            cg_source, cg_target = sg_source, sg_target
        chunk_ok = cg_source and cg_target

        if span_ok:
            span_grounded += 1
        if chunk_ok:
            chunk_grounded += 1
        else:
            # Only flag relationships failing the LENIENT check — those are
            # the actual suspect facts. Span-only-failures are sub-optimal
            # citation style, not hallucinations.
            missing = []
            if not cg_source:
                missing.append(f"source {rel.source!r}")
            if not cg_target:
                missing.append(f"target {rel.target!r}")
            flagged.append(
                f"hallucinated[{rel.predicate}]: "
                + ", ".join(missing)
                + f" absent from chunk; cited span: {rel.evidence_span[:80]!r}"
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
        n_grounded=span_grounded,
        n_chunk_grounded=chunk_grounded,
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
    """An entity is grounded if its name OR any alias OR a content-word token
    of the name appears in ``span``.

    Three checks, in order of strictness:
    1. Full-name substring match (case-insensitive).
    2. ``rapidfuzz.partial_ratio`` ≥ 85 — handles apostrophes, plurals,
       minor casing/punctuation drift.
    3. **Token-level match** — any content-word token of the name (length
       ≥ 4, not a stopword) appears as a whole word in the span. Catches
       the very common pattern where the LLM canonicalizes a partial-name
       chunk reference (``"Leonard"``) into the full canonical entity name
       (``"Leonard Hofstadter"``); the chunk is still validly the source.
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
        if _token_match(s, span_l):
            return True
    return False


def _token_match(name_lower: str, target_lower: str) -> bool:
    """Whole-word match for any content token of ``name_lower`` in ``target_lower``.

    A "content token" is any token of length >= ``_MIN_TOKEN_LEN`` that
    isn't a stopword/honorific. We split on non-alphanumeric to handle
    punctuation in the name (apostrophes, dashes). Whole-word match in the
    target uses regex word boundaries so e.g. ``"big"`` doesn't match
    ``"bigger"``.
    """
    tokens = [t for t in re.split(r"[^a-z0-9]+", name_lower) if t]
    content_tokens = [
        t for t in tokens if len(t) >= _MIN_TOKEN_LEN and t not in _GROUNDING_STOPWORDS
    ]
    if not content_tokens:
        return False
    return any(re.search(rf"\b{re.escape(token)}\b", target_lower) for token in content_tokens)


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
