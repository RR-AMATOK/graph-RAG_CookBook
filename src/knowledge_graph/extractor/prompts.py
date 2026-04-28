"""Prompt loader and version constant.

The prompt body lives at ``config/extraction_prompts/v<n>.txt`` so it can be
edited, diffed, and reviewed like code (mandatory rule #8 — prompt versioning).
Bumping the prompt requires bumping ``PROMPT_VERSION``; downstream cache keys
and graph metadata both depend on it, so older cached extractions don't
contaminate runs against a new prompt.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

PROMPT_VERSION = "v0"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_PROMPT_DIR = _REPO_ROOT / "config" / "extraction_prompts"


@lru_cache(maxsize=8)
def load_system_prompt(version: str = PROMPT_VERSION) -> str:
    """Return the system prompt body for the given version.

    Cached per-process; the prompt file is never edited mid-run.
    """
    path = _PROMPT_DIR / f"{version}.txt"
    if not path.exists():
        raise FileNotFoundError(
            f"extraction prompt not found at {path} — bump PROMPT_VERSION or "
            f"author config/extraction_prompts/{version}.txt"
        )
    return path.read_text(encoding="utf-8").strip()
