"""Content-addressable cache for extraction results.

Cache key is ``hash(prompt_version + chunk_content)`` per FR-3.5. Cached
entries are JSON files under ``cache_root/<key[:2]>/<key>.json``. The
two-character shard prevents one giant directory.

Bumping the prompt version invalidates every cached entry by construction —
the keys live in a different namespace.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def cache_key(prompt_version: str, chunk_text: str) -> str:
    """Stable cache key. Bump ``prompt_version`` to invalidate."""
    digest = hashlib.sha256(f"{prompt_version}\x00{chunk_text}".encode()).hexdigest()
    return digest


@dataclass(frozen=True)
class ExtractionCache:
    """Filesystem cache. Thread-/process-safe at write because writes are atomic via rename."""

    cache_root: Path

    def __post_init__(self) -> None:
        self.cache_root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        return self.cache_root / key[:2] / f"{key}.json"

    def get(self, key: str) -> dict[str, Any] | None:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            with path.open("r", encoding="utf-8") as fh:
                value: dict[str, Any] = json.load(fh)
                return value
        except (OSError, json.JSONDecodeError):
            # Corrupt entry — treat as a miss, the run will repopulate.
            return None

    def put(self, key: str, value: dict[str, Any]) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(value, fh, sort_keys=True, ensure_ascii=False)
        tmp.replace(path)
