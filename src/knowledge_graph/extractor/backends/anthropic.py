"""Anthropic backend — direct API, prompt-caching enabled.

This backend talks to ``api.anthropic.com`` via the official ``anthropic``
SDK. It is the highest-quality option for the default Claude Sonnet model
and the only path that supports ephemeral system-prompt caching out of the
box.

Pricing (USD per million tokens, Claude Sonnet 4.7, 2026-04):
- input: $3.00
- output: $15.00
- cache read: $0.30
"""

from __future__ import annotations

import os
from typing import Any

from knowledge_graph.extractor.backends.base import (
    BackendError,
    BackendResponse,
    LLMBackend,
)

_PRICE_PER_M_INPUT_USD = 3.00
_PRICE_PER_M_OUTPUT_USD = 15.00
_PRICE_PER_M_CACHE_READ_USD = 0.30


class AnthropicBackend(LLMBackend):
    """Anthropic SDK backend.

    Tests substitute the underlying client via :meth:`inject_client`.
    """

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._client: Any | None = None

    def inject_client(self, client: Any) -> None:
        """Test seam — replace the ``anthropic.Anthropic`` instance with a stub."""
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from anthropic import Anthropic

        api_key = getattr(self.settings, "api_key", None) or os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise BackendError("ANTHROPIC_API_KEY not set; export it or pass settings.api_key")
        self._client = Anthropic(api_key=api_key)
        return self._client

    def call(
        self,
        *,
        system_prompt: str,
        user_message: str,
        tool: dict[str, Any],
        max_tokens: int,
    ) -> BackendResponse:
        client = self._get_client()
        try:
            response = client.messages.create(
                model=getattr(self.settings, "model", "claude-sonnet-4-7"),
                max_tokens=max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=[tool],
                tool_choice={"type": "tool", "name": tool["name"]},
                messages=[
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": user_message}],
                    }
                ],
            )
        except Exception as exc:
            raise BackendError(f"anthropic call failed: {exc}") from exc

        tool_block = next(
            (block for block in response.content if getattr(block, "type", None) == "tool_use"),
            None,
        )
        if tool_block is None or getattr(tool_block, "name", None) != tool["name"]:
            raise BackendError(f"model did not call tool {tool['name']!r}")

        raw_input = getattr(tool_block, "input", {}) or {}
        raw_usage = getattr(response, "usage", None)
        input_tokens = int(getattr(raw_usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(raw_usage, "output_tokens", 0) or 0)
        cache_read = int(getattr(raw_usage, "cache_read_input_tokens", 0) or 0)
        cache_create = int(getattr(raw_usage, "cache_creation_input_tokens", 0) or 0)

        cost = (
            input_tokens / 1_000_000 * _PRICE_PER_M_INPUT_USD
            + output_tokens / 1_000_000 * _PRICE_PER_M_OUTPUT_USD
            + cache_read / 1_000_000 * _PRICE_PER_M_CACHE_READ_USD
        )

        return BackendResponse(
            tool_input=dict(raw_input),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cache_creation_tokens=cache_create,
            cost_usd=cost,
        )
