"""Project configuration via pydantic-settings + YAML.

Sprint 1 ships the typed shell only — components in Sprint 2+ extend ``Settings``
with their own typed sub-sections. Reads from ``config/default.yaml`` plus env
overrides (prefix ``KG_``).
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "default.yaml"


class GraphDBSettings(BaseModel):
    """FalkorDB connection (DEC-002).

    Default host port is 6390 (not the Redis default 6379) to avoid clashes
    with other Redis-based services on developer machines. The FalkorDB
    container internally speaks Redis on 6379; the docker-compose mapping
    is ``6390:6379``.
    """

    host: str = "localhost"
    port: int = 6390
    database: str = "graph_rag"


class VectorDBSettings(BaseModel):
    """Qdrant connection."""

    host: str = "localhost"
    port: int = 6333
    grpc_port: int = 6334


class LLMSettings(BaseModel):
    """LLM provider settings."""

    extraction_model: str = "claude-sonnet-4-7"
    categorization_model: str = "claude-haiku-4-5"
    embedding_model: str = "voyage-3-large"


class PathSettings(BaseModel):
    """Project paths (all relative to PROJECT_ROOT)."""

    corpus_dir: Path = Field(default=PROJECT_ROOT / "corpus")
    vault_dir: Path = Field(default=PROJECT_ROOT / "vault")
    publish_dir: Path = Field(default=PROJECT_ROOT / "publish")
    cache_dir: Path = Field(default=PROJECT_ROOT / "cache")
    runs_dir: Path = Field(default=PROJECT_ROOT / "runs")


class Settings(BaseSettings):
    """Top-level project settings."""

    model_config = SettingsConfigDict(
        env_prefix="KG_",
        env_nested_delimiter="__",
        case_sensitive=False,
    )

    graph_db: GraphDBSettings = Field(default_factory=GraphDBSettings)
    vector_db: VectorDBSettings = Field(default_factory=VectorDBSettings)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    paths: PathSettings = Field(default_factory=PathSettings)
