"""Stable id derivation for graph nodes and edges.

Entities are keyed by ``(normalized_name, type)`` so the same entity in
multiple documents produces the same id (FR-4.1 cross-document resolution).
Edges are keyed by ``(source_id, target_id, predicate)`` so the same triple
asserted from multiple documents updates a single edge instead of creating
duplicates; the per-document evidence accumulates in the edge properties.
"""

from __future__ import annotations

import hashlib
import re


def _normalize_name(name: str) -> str:
    name = name.lower().strip()
    name = re.sub(r"[\s_]+", " ", name)
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


def entity_id(name: str, type_: str) -> str:
    """Stable id for an entity, identical across documents and runs."""
    key = f"{_normalize_name(name)}\x00{type_.strip()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"ent_{digest}"


def edge_id(source_id: str, target_id: str, predicate: str) -> str:
    """Stable id for a typed edge between two entities."""
    key = f"{source_id}\x00{target_id}\x00{predicate.strip()}"
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]
    return f"edge_{digest}"
