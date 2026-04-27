"""Sprint 1 smoke tests — verify scaffolding imports and basic config load."""

from __future__ import annotations

from pathlib import Path

from knowledge_graph import __version__
from knowledge_graph.config import Settings


def test_package_version_is_set() -> None:
    assert isinstance(__version__, str)
    assert len(__version__) > 0


def test_settings_load_with_defaults() -> None:
    settings = Settings()
    assert settings.graph_db.port == 6390
    assert settings.vector_db.port == 6333
    assert settings.llm.extraction_model.startswith("claude-")


def test_subpackages_importable() -> None:
    """All component packages from SPEC §6.2 must import without error."""
    import importlib

    for module in (
        "knowledge_graph.canonicalizer",
        "knowledge_graph.chunker",
        "knowledge_graph.emitter",
        "knowledge_graph.exporter",
        "knowledge_graph.extractor",
        "knowledge_graph.graph",
        "knowledge_graph.mcp_server",
        "knowledge_graph.publisher",
        "knowledge_graph.scrapers",
        "knowledge_graph.staleness",
        "knowledge_graph.vector",
    ):
        assert importlib.import_module(module) is not None


def test_project_root_layout(project_root: Path) -> None:
    """Critical files exist at expected locations."""
    assert (project_root / "SPEC.md").exists()
    assert (project_root / "CLAUDE.md").exists()
    assert (project_root / "pyproject.toml").exists()
    assert (project_root / "Makefile").exists()
    assert (project_root / "docker-compose.yml").exists()
    assert (project_root / "config" / "default.yaml").exists()
