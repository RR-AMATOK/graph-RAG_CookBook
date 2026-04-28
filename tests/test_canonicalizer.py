"""Canonicalizer unit tests."""

from __future__ import annotations

from pathlib import Path

import frontmatter
import pytest

from knowledge_graph.canonicalizer import (
    CanonicalFrontmatter,
    CanonicalizationError,
    canonicalize_corpus,
    canonicalize_file,
)
from knowledge_graph.canonicalizer.paths import (
    canonical_path,
    flat_segments,
    nested_segments,
    parent_path,
    to_wikilink,
)


class TestPaths:
    def test_flat_segments_simple(self) -> None:
        assert flat_segments("BBT__Series__Overview.md") == ["BBT", "Series", "Overview"]

    def test_flat_segments_single(self) -> None:
        assert flat_segments("Single.md") == ["Single"]

    def test_flat_segments_rejects_empty(self) -> None:
        with pytest.raises(ValueError):
            flat_segments("")

    def test_flat_segments_rejects_double_separator(self) -> None:
        with pytest.raises(ValueError):
            flat_segments("Foo____Bar.md")

    def test_nested_segments_strips_md(self) -> None:
        assert nested_segments("series/seasons/season_1.md") == ["series", "seasons", "season_1"]

    def test_nested_segments_handles_leading_dot(self) -> None:
        assert nested_segments("./single.md") == ["single"]

    def test_canonical_path_joins(self) -> None:
        assert canonical_path("corpus-a", ["BBT", "Series"]) == "corpus-a/BBT/Series"

    def test_parent_path_drops_leaf(self) -> None:
        assert parent_path("corpus-a/BBT/Series/Overview") == "corpus-a/BBT/Series"

    def test_parent_path_root_returns_none(self) -> None:
        assert parent_path("corpus-a/Single") is None

    def test_to_wikilink_wraps(self) -> None:
        assert to_wikilink("corpus-a/foo") == "[[corpus-a/foo]]"

    def test_to_wikilink_passes_through_none(self) -> None:
        assert to_wikilink(None) is None


class TestCanonicalizeFile:
    def _write(self, path: Path, metadata: dict[str, object], body: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        post = frontmatter.Post(content=body, **metadata)
        path.write_text(frontmatter.dumps(post), encoding="utf-8")

    def test_flat_layout_minimal(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "BBT__Series__Overview.md"
        self._write(
            src,
            {
                "title": "The Big Bang Theory",
                "tags": ["series"],
                "source_repo": "reference-corpus-flat",
                "source_path": "BBT__Series__Overview.md",
                "fetched_at": "2026-04-26T00:00:00Z",
                "content_hash": "sha256:" + "0" * 64,
            },
            "Body content here.\n",
        )
        out = canonicalize_file(
            src,
            source_repo="corpus-a",
            layout="flat",
            corpus_root=tmp_path / "corpus",
        )
        fm = out.frontmatter_obj
        assert fm.canonical_path == "corpus-a/BBT/Series/Overview"
        assert fm.parent == "[[corpus-a/BBT/Series]]"
        assert fm.doc_id.startswith("doc_")
        assert "BBT__Series__Overview" in fm.aliases
        assert fm.content_hash.startswith("sha256:")
        assert isinstance(fm, CanonicalFrontmatter)

    def test_nested_layout_minimal(self, tmp_path: Path) -> None:
        src_root = tmp_path / "nested"
        src = src_root / "series" / "seasons" / "season_1.md"
        self._write(
            src,
            {
                "title": "Season 1",
                "tags": ["season"],
                "source_repo": "reference-corpus-nested",
                "source_path": "series/seasons/season_1.md",
                "fetched_at": "2026-04-26T00:00:00Z",
                "content_hash": "sha256:" + "1" * 64,
            },
            "Season 1 body.\n",
        )
        out = canonicalize_file(
            src,
            source_repo="corpus-b",
            layout="nested",
            corpus_root=tmp_path / "corpus",
            relative_to=src_root,
        )
        fm = out.frontmatter_obj
        assert fm.canonical_path == "corpus-b/series/seasons/season_1"
        assert fm.parent == "[[corpus-b/series/seasons]]"

    def test_missing_title_falls_back_to_leaf(self, tmp_path: Path) -> None:
        src = tmp_path / "Foo__Bar.md"
        self._write(src, {"tags": ["t"]}, "body")
        out = canonicalize_file(
            src, source_repo="corpus-a", layout="flat", corpus_root=tmp_path / "corpus"
        )
        assert out.frontmatter_obj.title == "Bar"

    def test_empty_body_rejected(self, tmp_path: Path) -> None:
        src = tmp_path / "Foo.md"
        self._write(src, {"title": "x", "tags": ["t"]}, "   \n  \n")
        with pytest.raises(CanonicalizationError, match="empty body"):
            canonicalize_file(
                src,
                source_repo="corpus-a",
                layout="flat",
                corpus_root=tmp_path / "corpus",
            )

    def test_invalid_layout(self, tmp_path: Path) -> None:
        src = tmp_path / "Foo.md"
        self._write(src, {"title": "x", "tags": ["t"]}, "body")
        with pytest.raises(CanonicalizationError, match="invalid layout"):
            canonicalize_file(
                src,
                source_repo="corpus-a",
                layout="bogus",
                corpus_root=tmp_path / "corpus",
            )


class TestCanonicalizeCorpus:
    def test_walk_writes_outputs(self, tmp_path: Path) -> None:
        flat = tmp_path / "flat"
        nested = tmp_path / "nested"
        corpus = tmp_path / "corpus"
        flat.mkdir()
        (flat / "Foo__Bar.md").write_text(
            "---\ntitle: Bar\ntags: [t]\n---\nBar body\n",
            encoding="utf-8",
        )
        (nested / "section").mkdir(parents=True)
        (nested / "section" / "leaf.md").write_text(
            "---\ntitle: Leaf\ntags: [t]\n---\nLeaf body\n",
            encoding="utf-8",
        )
        docs, errors = canonicalize_corpus(
            [(flat, "corpus-a", "flat"), (nested, "corpus-b", "nested")],
            corpus_root=corpus,
        )
        assert errors == []
        assert len(docs) == 2
        # Both output files exist on disk with the expected paths.
        assert (corpus / "corpus-a" / "Foo" / "Bar.md").exists()
        assert (corpus / "corpus-b" / "section" / "leaf.md").exists()

    def test_missing_dir_records_error(self, tmp_path: Path) -> None:
        docs, errors = canonicalize_corpus(
            [(tmp_path / "does-not-exist", "corpus-a", "flat")],
            corpus_root=tmp_path / "corpus",
        )
        assert docs == []
        assert any("does not exist" in e for e in errors)

    def test_doc_id_stable_across_runs(self, tmp_path: Path) -> None:
        src = tmp_path / "src" / "Foo__Bar.md"
        src.parent.mkdir()
        src.write_text(
            "---\ntitle: Bar\ntags: [t]\n---\nbody\n",
            encoding="utf-8",
        )
        a = canonicalize_file(
            src, source_repo="corpus-a", layout="flat", corpus_root=tmp_path / "out"
        )
        b = canonicalize_file(
            src, source_repo="corpus-a", layout="flat", corpus_root=tmp_path / "out"
        )
        assert a.frontmatter_obj.doc_id == b.frontmatter_obj.doc_id
