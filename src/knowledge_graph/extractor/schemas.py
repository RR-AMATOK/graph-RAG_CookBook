"""Pydantic models + Anthropic tool definition for the extractor's structured output."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ENTITY_TYPES: tuple[str, ...] = (
    "Character",
    "Person",
    "Organization",
    "Location",
    "Event",
    "Concept",
    "Work",
)

PROVENANCE_TAGS: tuple[str, ...] = ("EXTRACTED", "INFERRED", "AMBIGUOUS")

_PREDICATE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class ExtractedEntity(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    type: str
    aliases: list[str] = Field(default_factory=list)
    description: str = ""

    @field_validator("type")
    @classmethod
    def _check_type(cls, v: str) -> str:
        if v not in ENTITY_TYPES:
            raise ValueError(f"entity type {v!r} not in {ENTITY_TYPES}")
        return v

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()

    @field_validator("aliases")
    @classmethod
    def _clean_aliases(cls, v: list[str]) -> list[str]:
        return [a.strip() for a in v if a and a.strip()]


class ExtractedRelationship(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str = Field(min_length=1)
    target: str = Field(min_length=1)
    predicate: str
    evidence_span: str = Field(min_length=1)
    confidence: float = Field(ge=0.0, le=1.0)
    provenance_tag: str

    @field_validator("predicate")
    @classmethod
    def _check_predicate(cls, v: str) -> str:
        if not _PREDICATE_RE.match(v):
            raise ValueError(f"predicate {v!r} must match {_PREDICATE_RE.pattern}")
        return v

    @field_validator("provenance_tag")
    @classmethod
    def _check_provenance(cls, v: str) -> str:
        if v not in PROVENANCE_TAGS:
            raise ValueError(f"provenance_tag {v!r} not in {PROVENANCE_TAGS}")
        return v

    @field_validator("source", "target")
    @classmethod
    def _strip_endpoints(cls, v: str) -> str:
        return v.strip()


class Extraction(BaseModel):
    """Output of one chunk extraction.

    ``source`` and ``target`` of every relationship are validated to refer to
    a name in ``entities`` — prevents the model from emitting orphan edges.
    """

    model_config = ConfigDict(extra="forbid")

    entities: list[ExtractedEntity] = Field(default_factory=list)
    relationships: list[ExtractedRelationship] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_endpoints_resolve(self) -> Extraction:
        names = {e.name for e in self.entities}
        for rel in self.relationships:
            if rel.source not in names:
                raise ValueError(f"relationship.source {rel.source!r} not in entities list")
            if rel.target not in names:
                raise ValueError(f"relationship.target {rel.target!r} not in entities list")
        return self


def record_extractions_tool() -> dict[str, Any]:
    """Return the Anthropic tool definition for ``record_extractions``.

    Built dynamically from :data:`ENTITY_TYPES` and :data:`PROVENANCE_TAGS` so
    schema and runtime validation stay in lockstep.
    """
    return {
        "name": "record_extractions",
        "description": (
            "Record entities and typed relationships extracted from a "
            "markdown chunk. Call exactly once per chunk."
        ),
        "input_schema": {
            "type": "object",
            "required": ["entities", "relationships"],
            "additionalProperties": False,
            "properties": {
                "entities": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["name", "type"],
                        "additionalProperties": False,
                        "properties": {
                            "name": {"type": "string", "minLength": 1},
                            "type": {"type": "string", "enum": list(ENTITY_TYPES)},
                            "aliases": {
                                "type": "array",
                                "items": {"type": "string"},
                                "default": [],
                            },
                            "description": {"type": "string", "default": ""},
                        },
                    },
                },
                "relationships": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": [
                            "source",
                            "target",
                            "predicate",
                            "evidence_span",
                            "confidence",
                            "provenance_tag",
                        ],
                        "additionalProperties": False,
                        "properties": {
                            "source": {"type": "string", "minLength": 1},
                            "target": {"type": "string", "minLength": 1},
                            "predicate": {"type": "string", "pattern": _PREDICATE_RE.pattern},
                            "evidence_span": {"type": "string", "minLength": 1},
                            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                            "provenance_tag": {
                                "type": "string",
                                "enum": list(PROVENANCE_TAGS),
                            },
                        },
                    },
                },
            },
        },
    }
