"""Canonicalizer orchestrator — read source files, normalize, write to ``corpus/``.

Per FR-2:

- FR-2.1 — emit each source file to ``corpus/`` with standardized frontmatter.
- FR-2.2 — preserve the original basename in the ``aliases`` list.
- FR-2.3 — populate ``parent`` from ``__`` delimiters or folder path.
- FR-2.4 — populate ``source_url`` from input frontmatter when present.
- FR-2.5 — body content is unchanged.
- FR-2.6 — validate every emitted file against the canonical schema; fail fast
  with a file-path-indexed error list.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

import frontmatter
from pydantic import ValidationError

from knowledge_graph.canonicalizer.paths import (
    canonical_path as build_canonical_path,
)
from knowledge_graph.canonicalizer.paths import (
    flat_segments,
    nested_segments,
    parent_path,
    to_wikilink,
)
from knowledge_graph.canonicalizer.schema import (
    CanonicalFrontmatter,
    InputFrontmatter,
)

# Filename like ``Foo__Bar__Baz.md`` is treated as flat. Anything containing a
# path separator is treated as nested. We don't sniff content; the caller knows
# which layout each input directory represents.
_FLAT_FILENAME = re.compile(r"^[^/]+__[^/]+\.md$")


class CanonicalizationError(Exception):
    """Raised when an input file cannot be canonicalized.

    The message includes the offending source path so a directory walk can
    surface a file-path-indexed error list (FR-2.6) without losing context.
    """


@dataclass(frozen=True)
class CanonicalDoc:
    """Output of canonicalizing one input file.

    The ``frontmatter_md`` and ``body`` fields are kept separate so callers can
    write them to disk, hand them to the chunker, or hold them in memory
    without re-parsing.
    """

    frontmatter_obj: CanonicalFrontmatter
    body: str
    output_path: Path

    @property
    def doc_id(self) -> str:
        return self.frontmatter_obj.doc_id

    @property
    def canonical_path(self) -> str:
        return self.frontmatter_obj.canonical_path


def canonicalize_file(
    source_path: Path,
    *,
    source_repo: str,
    layout: str,
    corpus_root: Path,
    relative_to: Path | None = None,
) -> CanonicalDoc:
    """Canonicalize a single source file and return the in-memory result.

    Args:
        source_path: Absolute path to the input markdown file.
        source_repo: Logical identifier prefixed onto every canonical path
            (e.g., ``"corpus-a"``). Two source directories with the same repo
            identifier collide; the caller is responsible for picking unique
            ones.
        layout: ``"flat"`` (filename uses ``__`` as path separator) or
            ``"nested"`` (folder structure is the path).
        corpus_root: Directory under which canonical files are written.
        relative_to: For ``layout="nested"``, the directory the source path is
            resolved against. Required for nested; ignored for flat.

    Returns:
        A :class:`CanonicalDoc` ready to write or pipe into the chunker.

    Raises:
        CanonicalizationError: When required input fields are missing or the
            output frontmatter fails strict-schema validation.
    """
    if layout not in ("flat", "nested"):
        raise CanonicalizationError(f"{source_path}: invalid layout {layout!r}")

    raw = source_path.read_text(encoding="utf-8")
    try:
        post = frontmatter.loads(raw)
    except Exception as exc:
        raise CanonicalizationError(f"{source_path}: frontmatter parse failed: {exc}") from exc

    try:
        input_fm = InputFrontmatter.model_validate(post.metadata)
    except ValidationError as exc:
        raise CanonicalizationError(f"{source_path}: input frontmatter invalid: {exc}") from exc

    body = post.content
    if not body.strip():
        raise CanonicalizationError(f"{source_path}: empty body")

    if layout == "flat":
        segments = flat_segments(source_path.name)
    else:
        if relative_to is None:
            raise CanonicalizationError(f"{source_path}: layout='nested' requires relative_to")
        try:
            rel = source_path.resolve().relative_to(relative_to.resolve())
        except ValueError as exc:
            raise CanonicalizationError(
                f"{source_path}: not under relative_to={relative_to}"
            ) from exc
        segments = nested_segments(str(rel))

    canonical = build_canonical_path(source_repo, segments)

    # ``aliases`` preserves the upstream basename (FR-2.2). Loose dedup happens
    # in the schema validator.
    upstream_alias = source_path.stem
    aliases = [*input_fm.aliases, upstream_alias]

    title = input_fm.title or _title_from_segments(segments)
    if not title:
        raise CanonicalizationError(f"{source_path}: cannot derive title")

    parent = _resolve_parent(input_fm.parent, canonical)

    updated = _coerce_date(input_fm.updated) or _coerce_date(input_fm.fetched_at) or date.today()
    created = _coerce_date(input_fm.created)

    content_hash = input_fm.content_hash or _compute_content_hash(body)
    doc_id = _compute_doc_id(canonical)
    source_path_str = input_fm.source_path or _default_source_path(layout, source_path, segments)

    try:
        canonical_fm = CanonicalFrontmatter(
            title=title,
            aliases=aliases,
            tags=list(input_fm.tags),
            parent=parent,
            source_repo=source_repo,
            source_path=source_path_str,
            source_url=input_fm.source_url,
            license=input_fm.license,
            license_url=input_fm.license_url,
            created=created,
            updated=updated,
            doc_id=doc_id,
            canonical_path=canonical,
            content_hash=content_hash,
        )
    except ValidationError as exc:
        raise CanonicalizationError(f"{source_path}: canonical frontmatter invalid: {exc}") from exc

    output_path = corpus_root / f"{canonical}.md"
    return CanonicalDoc(frontmatter_obj=canonical_fm, body=body, output_path=output_path)


def canonicalize_corpus(
    sources: Iterable[tuple[Path, str, str]],
    *,
    corpus_root: Path,
    write: bool = True,
) -> tuple[list[CanonicalDoc], list[str]]:
    """Walk multiple source directories and canonicalize every ``.md`` under them.

    Args:
        sources: Iterable of ``(source_dir, source_repo, layout)`` triples.
            ``layout`` is either ``"flat"`` or ``"nested"``.
        corpus_root: Output directory.
        write: When True, write each canonicalized doc to ``corpus_root``.
            Tests that only need in-memory results pass ``write=False``.

    Returns:
        ``(docs, errors)`` — successfully canonicalized docs and the
        file-path-indexed error messages collected along the way (FR-2.6).
    """
    docs: list[CanonicalDoc] = []
    errors: list[str] = []

    for source_dir, source_repo, layout in sources:
        if not source_dir.exists():
            errors.append(f"{source_dir}: does not exist")
            continue
        for md_path in sorted(source_dir.rglob("*.md")):
            try:
                doc = canonicalize_file(
                    md_path,
                    source_repo=source_repo,
                    layout=layout,
                    corpus_root=corpus_root,
                    relative_to=source_dir if layout == "nested" else None,
                )
            except CanonicalizationError as exc:
                errors.append(str(exc))
                continue
            docs.append(doc)

    if write:
        for doc in docs:
            _write_doc(doc)

    return docs, errors


# ─────────────────────────────────────────────────────────────────────
# Internals
# ─────────────────────────────────────────────────────────────────────


def _title_from_segments(segments: list[str]) -> str:
    leaf = segments[-1]
    return leaf.replace("_", " ").strip()


def _resolve_parent(input_parent: str | None, canonical: str) -> str | None:
    if input_parent:
        # If the input is already a wikilink, keep it; otherwise wrap the bare path.
        if input_parent.startswith("[[") and input_parent.endswith("]]"):
            return input_parent
        return to_wikilink(input_parent)
    return to_wikilink(parent_path(canonical))


def _coerce_date(value: date | str | None) -> date | None:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.rstrip("Z")).date()
        except ValueError:
            try:
                return date.fromisoformat(value[:10])
            except ValueError:
                return None
    return None


def _compute_content_hash(body: str) -> str:
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _compute_doc_id(canonical: str) -> str:
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    return f"doc_{digest}"


def _default_source_path(layout: str, source_path: Path, segments: list[str]) -> str:
    return source_path.name if layout == "flat" else "/".join(segments) + ".md"


def _write_doc(doc: CanonicalDoc) -> None:
    """Write ``doc`` to disk with normalized frontmatter."""
    doc.output_path.parent.mkdir(parents=True, exist_ok=True)
    metadata = doc.frontmatter_obj.model_dump(mode="json", exclude_none=True)
    post = frontmatter.Post(content=doc.body, **metadata)
    serialized = frontmatter.dumps(post, sort_keys=False)
    if not serialized.endswith("\n"):
        serialized += "\n"
    doc.output_path.write_text(serialized, encoding="utf-8")


def _now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()
