"""Offline, conservative token estimator.

We need a deterministic token count to drive chunk boundaries. The Anthropic
SDK's official ``count_tokens`` is an API call (cost + latency we don't want
inside the chunker), and shipping ``tiktoken`` adds a heavy compiled dep that
isn't even Claude's tokenizer. Sprint 2 ships the simplest thing that works:
a character-rate heuristic biased to **overestimate**, so a chunk that the
estimator thinks is 1500 tokens is at most ~1500 actual Claude tokens (and
usually fewer). This keeps us safely under the soft cap without API calls.

Sprint 3+ can plug in Anthropic's offline tokenizer when one exists; the
estimator is centralized here for that swap.
"""

from __future__ import annotations

# Empirical: English markdown averages ~4 chars/token on Claude's tokenizer.
# We use 3.5 to bias toward overestimation. Whitespace runs collapse to ~1 token
# regardless, so we don't strip them — they pad the estimate slightly, which
# is safe.
_CHARS_PER_TOKEN = 3.5


def estimate_tokens(text: str) -> int:
    """Return a conservative upper-ish estimate of Claude tokens for ``text``.

    >>> estimate_tokens("") == 0
    True
    >>> estimate_tokens("hello world") >= 2
    True
    """
    if not text:
        return 0
    n_chars = len(text)
    return max(1, int(n_chars / _CHARS_PER_TOKEN) + 1)
