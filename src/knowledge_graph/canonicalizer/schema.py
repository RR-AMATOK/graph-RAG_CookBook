"""Frontmatter schemas: input (loose) and canonical (strict).

The canonicalizer reads a source file's frontmatter as :class:`InputFrontmatter`
(loose — accepts whatever the upstream fetcher emitted), then projects it to
:class:`CanonicalFrontmatter` (strict — every downstream stage relies on these
fields) before writing to ``corpus/``.

SPEC §7.1 lists the full canonical schema. Sprint 2 implements the subset that
the chunker, extractor, and graph builder actually need; later sprints will
extend with ``last_checked``, ``stale``, ``scrape_*``, etc.
"""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field, field_validator


class InputFrontmatter(BaseModel):
    """Loose schema accepted from upstream fetchers / source authors.

    Any field may be missing; the canonicalizer fills defaults where it can and
    raises :class:`~knowledge_graph.canonicalizer.canonicalizer.CanonicalizationError`
    when a required field cannot be derived.
    """

    model_config = ConfigDict(extra="allow")

    title: str | None = None
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    source_repo: str | None = None
    source_path: str | None = None
    source_url: str | None = None
    parent: str | None = None
    created: date | str | None = None
    updated: date | str | None = None
    fetched_at: str | None = None
    content_hash: str | None = None
    license: str | None = None
    license_url: str | None = None


class CanonicalFrontmatter(BaseModel):
    """Strict schema written to ``corpus/<canonical_path>.md``.

    Every field present here is something downstream stages may rely on. Adding
    a field is OK; removing or renaming one is a breaking change to the
    canonical contract and requires a corresponding bump in the graph schema
    version.
    """

    model_config = ConfigDict(extra="forbid")

    # Identity
    title: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)

    # Hierarchy (Breadcrumbs-compatible — ``parent`` is the absolute wikilink form)
    parent: str | None = None

    # Provenance
    source_repo: str
    source_path: str
    source_url: str | None = None
    license: str | None = None
    license_url: str | None = None

    # Freshness
    created: date | None = None
    updated: date

    # Graph metadata (computed)
    doc_id: str = Field(pattern=r"^doc_[A-Za-z0-9_]+$")
    canonical_path: str
    content_hash: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")

    @field_validator("tags")
    @classmethod
    def _strip_tags(cls, v: list[str]) -> list[str]:
        cleaned = [t.strip() for t in v if t and t.strip()]
        seen: set[str] = set()
        out: list[str] = []
        for t in cleaned:
            if t not in seen:
                seen.add(t)
                out.append(t)
        return out

    @field_validator("aliases")
    @classmethod
    def _dedupe_aliases(cls, v: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for a in v:
            if a and a not in seen:
                seen.add(a)
                out.append(a)
        return out
