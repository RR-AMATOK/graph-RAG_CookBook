"""Test/demo backend — replays a canned response.

Useful for unit tests that exercise the extractor pipeline without a network
call, and for manually wiring fixture extractions into the full pipeline
(e.g., to demo the graph builder before the user has any LLM access).
"""

from __future__ import annotations

from typing import Any

from knowledge_graph.extractor.backends.base import (
    BackendError,
    BackendResponse,
    LLMBackend,
)


class MockBackend(LLMBackend):
    """Backend that returns canned responses keyed by chunk text or sequentially.

    Two modes:
    - ``set_response(payload)`` — every call returns the same canned payload.
    - ``set_responses_by_text({text: payload, ...})`` — return per-chunk
      based on exact match of the user message; falls through to ``default``.
    """

    def __init__(self) -> None:
        self._default: dict[str, Any] | None = None
        self._by_text: dict[str, dict[str, Any]] = {}
        self.calls = 0

    def set_response(self, payload: dict[str, Any]) -> None:
        self._default = payload

    def set_responses_by_text(
        self, mapping: dict[str, dict[str, Any]], default: dict[str, Any] | None = None
    ) -> None:
        self._by_text = dict(mapping)
        if default is not None:
            self._default = default

    def call(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tool: dict[str, Any],
        max_tokens: int,
    ) -> BackendResponse:
        self.calls += 1
        payload = self._by_text.get(user_message, self._default)
        if payload is None:
            raise BackendError("MockBackend: no response configured")
        return BackendResponse(
            tool_input=payload,
            input_tokens=10,
            output_tokens=5,
            cost_usd=0.0,
        )
