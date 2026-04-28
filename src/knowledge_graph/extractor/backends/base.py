"""Backend protocol and shared types.

The ``LLMBackend`` protocol is intentionally narrow: one method, four
inputs, one structured response. Provider-specific concerns (API shape,
prompt caching, model pricing) live inside the backend implementation;
the extractor never sees them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


class BackendError(Exception):
    """Raised by a backend for any failure during ``call``.

    Subclass this for retriable vs. terminal distinctions if needed; the
    extractor's tenacity retry catches the base class.
    """


@dataclass(frozen=True)
class BackendResponse:
    """Normalized tool-use response across providers.

    ``tool_input`` is the parsed dict of arguments the model passed to the
    extraction tool — exactly the shape declared by ``record_extractions_tool``.
    Token counts are best-effort; backends that don't surface a particular
    counter (e.g., OpenAI's cache-read tokens) report ``0``.

    ``cost_usd`` is the backend's own estimate based on its pricing knowledge.
    For unknown / local models (Ollama) this is ``0.0`` — callers should treat
    a zero as "unknown", not "free".
    """

    tool_input: dict[str, Any]
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    cost_usd: float = 0.0


@runtime_checkable
class LLMBackend(Protocol):
    """One-call extraction backend interface.

    Implementations:
    - Build a provider-specific request from the four inputs.
    - Force the model to call the supplied tool exactly once.
    - Return the parsed tool input + usage + cost in a :class:`BackendResponse`.
    - Raise :class:`BackendError` for anything else.
    """

    def call(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tool: dict[str, Any],
        max_tokens: int,
    ) -> BackendResponse: ...
