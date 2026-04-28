"""Header-aware markdown chunker.

Chunking strategy:
1. Walk the body line-by-line. ``H2`` and ``H3`` headers are section boundaries.
2. Each section becomes one chunk; if a section exceeds the token soft-cap,
   it is split further on paragraph boundaries (blank-line separated).
3. Adjacent chunks within a single document share an overlap window of
   ``overlap_tokens`` tokens, drawn from the *end* of the previous chunk —
   this prevents entity mentions at chunk boundaries from being cut.
4. Each chunk gets a stable ``chunk_id = sha256(doc_id + offset + text)[:16]``
   so re-chunking the same content produces identical IDs (FR-3.5 cache key).

What this does **not** do (Sprint 2 MVP):
- Doesn't consult code fences, tables, or HTML blocks for special handling
  — it treats them as opaque text. Refinements land in Sprint 3 if needed.
- Doesn't honor list-item or sentence boundaries below the paragraph level.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from knowledge_graph.chunker.tokens import estimate_tokens

_HEADER_RE = re.compile(r"^(#{2,3})\s+(.+?)\s*$")


@dataclass(frozen=True)
class ChunkerSettings:
    soft_cap_tokens: int = 1500
    overlap_tokens: int = 200
    min_chunk_tokens: int = 32  # avoid emitting trivially small tail chunks

    def __post_init__(self) -> None:
        if self.overlap_tokens >= self.soft_cap_tokens:
            raise ValueError("overlap_tokens must be < soft_cap_tokens")
        if self.soft_cap_tokens <= 0:
            raise ValueError("soft_cap_tokens must be positive")


@dataclass(frozen=True)
class Chunk:
    """A single chunk produced by the chunker.

    ``offset`` is the character offset of the chunk's first character within
    the source body, **before** overlap padding. ``text`` is what the
    extractor sees (overlap included). The deterministic ``chunk_id`` is
    derived from ``(doc_id, offset, text)`` so identical inputs always yield
    the same id (FR-3.5 cache stability).
    """

    chunk_id: str
    doc_id: str
    canonical_path: str
    offset: int
    heading: str | None
    text: str
    token_estimate: int

    @staticmethod
    def make_id(doc_id: str, offset: int, text: str) -> str:
        digest = hashlib.sha256(f"{doc_id}|{offset}|{text}".encode()).hexdigest()
        return f"chk_{digest[:16]}"


@dataclass
class _Section:
    heading: str | None
    offset: int
    lines: list[str] = field(default_factory=list)

    @property
    def text(self) -> str:
        return "\n".join(self.lines).strip("\n")


def chunk_document(
    *,
    doc_id: str,
    canonical_path: str,
    body: str,
    settings: ChunkerSettings | None = None,
) -> list[Chunk]:
    """Split a canonical document body into chunks.

    Args:
        doc_id: Stable id of the source document (matches frontmatter).
        canonical_path: Vault-relative canonical path of the document.
        body: Markdown body (frontmatter already stripped by the canonicalizer).
        settings: Override defaults for testing or per-corpus tuning.

    Returns:
        Chunks in document order. Empty for an empty body.
    """
    settings = settings or ChunkerSettings()
    body = body.rstrip()
    if not body.strip():
        return []

    sections = _split_into_sections(body)
    out: list[Chunk] = []
    prev_text: str | None = None

    for section in sections:
        for piece_offset, piece_text in _split_section(section, settings):
            tokens = estimate_tokens(piece_text)
            if tokens < settings.min_chunk_tokens and out:
                # Coalesce a tiny tail with the previous chunk; the prior
                # entity-extraction call won't have to round-trip an
                # almost-empty payload.
                last = out.pop()
                merged = last.text.rstrip() + "\n\n" + piece_text.lstrip()
                merged = merged.strip("\n")
                out.append(
                    Chunk(
                        chunk_id=Chunk.make_id(doc_id, last.offset, merged),
                        doc_id=doc_id,
                        canonical_path=canonical_path,
                        offset=last.offset,
                        heading=last.heading,
                        text=merged,
                        token_estimate=estimate_tokens(merged),
                    )
                )
                prev_text = merged
                continue

            text_with_overlap = _with_overlap(prev_text, piece_text, settings)
            chunk = Chunk(
                chunk_id=Chunk.make_id(doc_id, piece_offset, text_with_overlap),
                doc_id=doc_id,
                canonical_path=canonical_path,
                offset=piece_offset,
                heading=section.heading,
                text=text_with_overlap,
                token_estimate=estimate_tokens(text_with_overlap),
            )
            out.append(chunk)
            prev_text = piece_text

    return out


# ─────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────


def _split_into_sections(body: str) -> list[_Section]:
    sections: list[_Section] = []
    cur = _Section(heading=None, offset=0)
    char_offset = 0

    for line in body.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        match = _HEADER_RE.match(stripped)
        if match:
            if cur.lines and cur.text:
                sections.append(cur)
            cur = _Section(heading=match.group(2), offset=char_offset)
        cur.lines.append(stripped)
        char_offset += len(line)

    if cur.lines and cur.text:
        sections.append(cur)

    if not sections:
        sections.append(_Section(heading=None, offset=0, lines=[body]))
    return sections


def _split_section(section: _Section, settings: ChunkerSettings) -> list[tuple[int, str]]:
    """Yield ``(char_offset, text)`` pieces for a section.

    A section under the soft cap emits one piece. An over-cap section is split
    on blank-line paragraph boundaries; if a single paragraph still exceeds
    the cap, it's emitted as one over-cap piece (we don't sentence-split in
    Sprint 2 — the extractor will see a slightly oversized chunk, which is
    OK; the cap is a *soft* cap by design).
    """
    full = section.text
    if not full:
        return []
    if estimate_tokens(full) <= settings.soft_cap_tokens:
        return [(section.offset, full)]

    pieces: list[tuple[int, str]] = []
    paragraphs = re.split(r"\n\s*\n", full)
    cursor_offset = section.offset
    buf: list[str] = []
    buf_offset = section.offset
    buf_tokens = 0

    for para in paragraphs:
        if not para.strip():
            cursor_offset += len(para) + 2  # the two-newline separator we split on
            continue
        para_tokens = estimate_tokens(para)
        if buf and buf_tokens + para_tokens > settings.soft_cap_tokens:
            pieces.append((buf_offset, "\n\n".join(buf)))
            buf = []
            buf_offset = cursor_offset
            buf_tokens = 0
        buf.append(para)
        buf_tokens += para_tokens
        cursor_offset += len(para) + 2

    if buf:
        pieces.append((buf_offset, "\n\n".join(buf)))
    return pieces


def _with_overlap(previous: str | None, current: str, settings: ChunkerSettings) -> str:
    """Prepend the trailing ``overlap_tokens`` of ``previous`` to ``current``.

    Returns ``current`` unchanged when there is no previous chunk or the
    previous chunk is shorter than the overlap budget.
    """
    if not previous or settings.overlap_tokens <= 0:
        return current
    overlap_chars = int(settings.overlap_tokens * 3.5)  # mirror tokens.py rate
    if overlap_chars <= 0 or len(previous) <= overlap_chars:
        return current
    tail = previous[-overlap_chars:]
    # Try to start the overlap on a paragraph boundary so we don't slice into a sentence.
    boundary = tail.find("\n\n")
    if boundary > 0:
        tail = tail[boundary + 2 :]
    return tail.rstrip() + "\n\n" + current.lstrip()
