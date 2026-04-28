"""OpenAI-compatible backend — works against any ``/v1/chat/completions`` endpoint.

The same backend handles:

- **OpenAI**: leave ``base_url`` as ``None`` (or set ``https://api.openai.com/v1``).
- **Ollama**: ``base_url=http://localhost:11434/v1``, ``api_key`` is required by
  the SDK but unused. Models like ``llama3.1:70b``, ``qwen2.5:32b``,
  ``mistral-large`` etc. that support function calling.
- **OpenRouter**: ``base_url=https://openrouter.ai/api/v1``. Routes to many
  providers including Claude (``anthropic/claude-sonnet-4-7``).
- **vLLM / LiteLLM / Anyscale**: any OpenAI-shape server.

The backend translates the Anthropic-shape tool dict (``{name, description,
input_schema}``) into OpenAI's function-call shape (``{type: function,
function: {name, description, parameters}}``) at call time, and parses the
response accordingly.
"""

from __future__ import annotations

import json
import os
from typing import Any

from knowledge_graph.extractor.backends.base import (
    BackendError,
    BackendResponse,
    LLMBackend,
)

# Built-in pricing for popular OpenAI / OpenRouter models. USD per million
# tokens. Unknown models report 0.0 (callers should treat as "unknown").
_PRICING_USD_PER_M: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o": (2.50, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4.1": (2.00, 8.00),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1-nano": (0.10, 0.40),
    "o3-mini": (1.10, 4.40),
    # OpenRouter aliases for Claude (best quality if subscription-bound users
    # want Sonnet without an Anthropic account; OpenRouter bills its own credits).
    "anthropic/claude-sonnet-4-7": (3.00, 15.00),
    "anthropic/claude-haiku-4-5": (0.80, 4.00),
}


class OpenAIBackend(LLMBackend):
    """OpenAI Chat Completions backend, also used for Ollama / OpenRouter."""

    def __init__(self, settings: Any) -> None:
        self.settings = settings
        self._client: Any | None = None

    def inject_client(self, client: Any) -> None:
        """Test seam — replace the ``openai.OpenAI`` instance with a stub."""
        self._client = client

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        from openai import OpenAI

        api_key_env = getattr(self.settings, "api_key_env", None) or "OPENAI_API_KEY"
        api_key = getattr(self.settings, "api_key", None) or os.getenv(api_key_env) or "unused"
        base_url = getattr(self.settings, "base_url", None)
        kwargs: dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
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
        oai_tool = _translate_tool(tool)
        try:
            response = client.chat.completions.create(
                model=getattr(self.settings, "model", "gpt-4o"),
                max_tokens=max_tokens,
                tools=[oai_tool],
                tool_choice={"type": "function", "function": {"name": tool["name"]}},
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            )
        except Exception as exc:
            raise BackendError(f"openai-compat call failed: {exc}") from exc

        choices = getattr(response, "choices", None) or []
        if not choices:
            raise BackendError("response had no choices")
        message = choices[0].message
        tool_calls = getattr(message, "tool_calls", None) or []
        if not tool_calls:
            raise BackendError(f"model did not call tool {tool['name']!r}")
        first = tool_calls[0]
        fn = getattr(first, "function", None)
        if fn is None or getattr(fn, "name", None) != tool["name"]:
            raise BackendError(f"model called wrong tool: {getattr(fn, 'name', '?')!r}")
        try:
            tool_input = json.loads(fn.arguments or "{}")
        except json.JSONDecodeError as exc:
            raise BackendError(f"tool arguments are not valid JSON: {exc}") from exc

        usage = getattr(response, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        # OpenAI exposes prompt-cache hit count via prompt_tokens_details.cached_tokens
        # on supported accounts; treat absence as 0.
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cache_read = int(getattr(prompt_details, "cached_tokens", 0) or 0) if prompt_details else 0

        model = getattr(self.settings, "model", "")
        prices = _PRICING_USD_PER_M.get(model)
        cost = (
            input_tokens / 1_000_000 * prices[0] + output_tokens / 1_000_000 * prices[1]
            if prices
            else 0.0
        )

        return BackendResponse(
            tool_input=tool_input,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read_tokens=cache_read,
            cost_usd=cost,
        )


def _translate_tool(tool: dict[str, Any]) -> dict[str, Any]:
    """Anthropic shape → OpenAI shape. Same JSON Schema body, different wrapper."""
    return {
        "type": "function",
        "function": {
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool["input_schema"],
        },
    }
