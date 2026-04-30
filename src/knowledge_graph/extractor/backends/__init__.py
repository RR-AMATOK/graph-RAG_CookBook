"""Pluggable LLM backends for the extractor.

The extractor itself is provider-agnostic: it builds the system prompt + tool
definition + user message, hands them to a :class:`LLMBackend`, and parses /
validates the response. Backends are selected by the ``backend`` field on
:class:`~knowledge_graph.extractor.extractor.ExtractorSettings`.

Supported backends:

- ``anthropic`` — direct Anthropic API. Best quality for the default
  ``claude-sonnet-4-7`` model. Requires ``ANTHROPIC_API_KEY``. Supports
  ephemeral system-prompt caching.
- ``openai`` — OpenAI-compatible endpoint. Works against:
  * OpenAI (``base_url=None`` or ``https://api.openai.com/v1``)
  * Ollama (``base_url=http://localhost:11434/v1``) — local, no key.
  * OpenRouter (``base_url=https://openrouter.ai/api/v1``) — multi-provider.
  * vLLM / LiteLLM / Anyscale / any other ``/v1/chat/completions`` server.
- ``mock`` — for tests; replays a canned ``BackendResponse``.
"""

from knowledge_graph.extractor.backends.base import (
    BackendError,
    BackendResponse,
    LLMBackend,
)

__all__ = [
    "BackendError",
    "BackendResponse",
    "LLMBackend",
    "make_backend",
]


def make_backend(backend: str, settings: object) -> LLMBackend:
    """Construct a backend instance by name.

    Args:
        backend: ``"anthropic"`` | ``"openai"`` | ``"mock"``.
        settings: An :class:`ExtractorSettings` instance (or anything providing
            the same attributes — duck-typed so this module doesn't import
            extractor and create a circular dependency).

    Raises:
        ValueError: When ``backend`` is unknown.
    """
    name = backend.strip().lower()
    if name == "anthropic":
        from knowledge_graph.extractor.backends.anthropic import AnthropicBackend

        return AnthropicBackend(settings)
    if name == "openai":
        from knowledge_graph.extractor.backends.openai_compat import OpenAIBackend

        return OpenAIBackend(settings)
    if name == "mock":
        from knowledge_graph.extractor.backends.mock import MockBackend

        return MockBackend()
    raise ValueError(f"unknown LLM backend: {backend!r} (valid: anthropic, openai, mock)")
