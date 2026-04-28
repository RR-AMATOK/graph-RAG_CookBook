"""Pure path-derivation helpers for the canonicalizer.

Two source-repo styles are supported (SPEC §1, FR-1.1..1.3):
- **Flat with ``__`` delimiters**: ``BBT__Series__Overview.md`` represents the path
  ``BBT/Series/Overview``. The original filename is preserved as an alias.
- **Folder-based**: ``series/seasons/season_1.md`` represents the path as-is, with
  the ``.md`` suffix removed.
"""

from __future__ import annotations

from pathlib import PurePosixPath


def flat_segments(filename: str) -> list[str]:
    """Split a flat ``__``-delimited filename into hierarchy segments.

    >>> flat_segments("BBT__Series__Overview.md")
    ['BBT', 'Series', 'Overview']
    >>> flat_segments("Single.md")
    ['Single']
    """
    if not filename:
        raise ValueError("empty filename")
    stem = filename
    if stem.endswith(".md"):
        stem = stem[:-3]
    segments = stem.split("__")
    if any(not s for s in segments):
        raise ValueError(f"empty segment in flat filename: {filename!r}")
    return segments


def nested_segments(relative_path: str) -> list[str]:
    """Split a folder-based relative path into hierarchy segments.

    >>> nested_segments("series/seasons/season_1.md")
    ['series', 'seasons', 'season_1']
    >>> nested_segments("./single.md")
    ['single']
    """
    if not relative_path:
        raise ValueError("empty relative_path")
    posix = PurePosixPath(relative_path)
    parts = [p for p in posix.parts if p not in (".", "")]
    if not parts:
        raise ValueError(f"path resolves to no segments: {relative_path!r}")
    last = parts[-1]
    if last.endswith(".md"):
        last = last[:-3]
    if not last:
        raise ValueError(f"empty leaf segment in {relative_path!r}")
    return [*parts[:-1], last]


def canonical_path(source_repo: str, segments: list[str]) -> str:
    """Combine the source repo identifier with hierarchy segments.

    >>> canonical_path("corpus-a", ["BBT", "Series", "Overview"])
    'corpus-a/BBT/Series/Overview'
    """
    if not source_repo:
        raise ValueError("source_repo is required")
    if not segments:
        raise ValueError("segments must be non-empty")
    return "/".join([source_repo, *segments])


def parent_path(canonical: str) -> str | None:
    """Return the parent canonical path (drop the leaf segment), or None at the root.

    >>> parent_path("corpus-a/BBT/Series/Overview")
    'corpus-a/BBT/Series'
    >>> parent_path("corpus-a/Single") is None
    True
    """
    parts = canonical.split("/")
    if len(parts) <= 2:
        # ``corpus-a/Leaf`` has no meaningful parent within the repo.
        return None
    return "/".join(parts[:-1])


def to_wikilink(target: str | None) -> str | None:
    """Wrap a canonical path as an absolute Obsidian wikilink, or pass through None."""
    if target is None:
        return None
    return f"[[{target}]]"
