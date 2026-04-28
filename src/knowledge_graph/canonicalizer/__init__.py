"""Canonicalizer — walks source repos, parses ``__`` hierarchy, normalizes
frontmatter, writes ``corpus/``.

Entry points:
- :func:`canonicalize_file` — single-file API used by tests and by the orchestrator.
- :func:`canonicalize_corpus` — directory-walk API used by ``kg ingest``.

(SPEC §6.2, FR-2)
"""

from knowledge_graph.canonicalizer.canonicalizer import (
    CanonicalDoc,
    CanonicalizationError,
    canonicalize_corpus,
    canonicalize_file,
)
from knowledge_graph.canonicalizer.schema import (
    CanonicalFrontmatter,
    InputFrontmatter,
)

__all__ = [
    "CanonicalDoc",
    "CanonicalFrontmatter",
    "CanonicalizationError",
    "InputFrontmatter",
    "canonicalize_corpus",
    "canonicalize_file",
]
