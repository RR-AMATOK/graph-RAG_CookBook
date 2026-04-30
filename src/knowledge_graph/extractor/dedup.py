"""Within-document entity deduplication using rapidfuzz.

FR-3.4: dedupe entities within a single document by name + fuzzy match
(rapidfuzz, threshold 90). Aliases of merged entities are unioned. The first
entity emitted (by extraction order) is the canonical one — its name wins.
"""

from __future__ import annotations

import re

from rapidfuzz import fuzz

from knowledge_graph.extractor.schemas import ExtractedEntity

DEFAULT_THRESHOLD = 90


def _normalize(name: str) -> str:
    """Lowercase, strip, collapse whitespace, drop punctuation."""
    name = name.lower().strip()
    name = re.sub(r"[\s_]+", " ", name)
    name = re.sub(r"[^\w\s]", "", name)
    return name.strip()


def _is_match(a: str, b: str, threshold: int) -> bool:
    if a == b:
        return True
    return fuzz.token_set_ratio(a, b) >= threshold


def dedupe_within_doc(
    entities: list[ExtractedEntity], *, threshold: int = DEFAULT_THRESHOLD
) -> tuple[list[ExtractedEntity], dict[str, str]]:
    """Merge entities with matching normalized names *within the same type*.

    Aliases from merged entities are unioned and the longer description wins.
    Cross-type collisions (e.g., a Character and a Concept with the same name)
    are intentionally NOT merged — type drives identity.

    Returns ``(deduped_entities, rename_map)`` where ``rename_map`` carries
    every original surface form → its canonical (first-seen) name. Callers
    that hold relationship references must re-map ``source`` / ``target``
    through this map before re-validating, otherwise post-dedup orphans will
    fail validation.

    >>> a = ExtractedEntity(name="Sheldon Cooper", type="Character")
    >>> b = ExtractedEntity(name="Dr. Sheldon Cooper", type="Character", aliases=["Shelly"])
    >>> ents, rm = dedupe_within_doc([a, b])
    >>> [e.name for e in ents]
    ['Sheldon Cooper']
    >>> rm == {"Sheldon Cooper": "Sheldon Cooper", "Dr. Sheldon Cooper": "Sheldon Cooper"}
    True
    """
    out: list[ExtractedEntity] = []
    norm_keys: list[str] = []
    rename_map: dict[str, str] = {}

    for ent in entities:
        norm = _normalize(ent.name)
        merged = False
        for i, existing_norm in enumerate(norm_keys):
            if out[i].type != ent.type:
                continue
            if _is_match(norm, existing_norm, threshold):
                _merge_into(out, i, ent)
                rename_map[ent.name] = out[i].name
                merged = True
                break
        if not merged:
            out.append(ent)
            norm_keys.append(norm)
            rename_map[ent.name] = ent.name

    return out, rename_map


def _merge_into(out: list[ExtractedEntity], i: int, incoming: ExtractedEntity) -> None:
    base = out[i]
    aliases_set: set[str] = set(base.aliases)
    aliases_set.update(incoming.aliases)
    if incoming.name != base.name:
        aliases_set.add(incoming.name)
    description = (
        base.description
        if len(base.description) >= len(incoming.description)
        else incoming.description
    )
    out[i] = ExtractedEntity(
        name=base.name,
        type=base.type,
        aliases=sorted(aliases_set),
        description=description,
    )
