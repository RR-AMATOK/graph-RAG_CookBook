"""Tests for the LLM backend implementations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import pytest

from knowledge_graph.extractor.backends import (
    BackendError,
    BackendResponse,
    LLMBackend,
)
from knowledge_graph.extractor.backends.anthropic import AnthropicBackend
from knowledge_graph.extractor.backends.mock import MockBackend
from knowledge_graph.extractor.backends.openai_compat import (
    OpenAIBackend,
    _translate_tool,
)
from knowledge_graph.extractor.extractor import ExtractorSettings
from knowledge_graph.extractor.schemas import record_extractions_tool

_SAMPLE_PAYLOAD: dict[str, Any] = {
    "entities": [{"name": "Sheldon", "type": "Character"}],
    "relationships": [],
}


# ─────────────────────────────────────────────────────────────────────
# Anthropic backend stubs
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeAnthropicUsage:
    input_tokens: int = 100
    output_tokens: int = 50
    cache_read_input_tokens: int = 20
    cache_creation_input_tokens: int = 10


@dataclass
class _FakeAnthropicBlock:
    type: str
    name: str | None = None
    input: dict[str, Any] | None = None


@dataclass
class _FakeAnthropicResponse:
    content: list[_FakeAnthropicBlock]
    usage: _FakeAnthropicUsage


class _FakeAnthropicMessages:
    def __init__(self, payload: dict[str, Any], tool_name: str = "record_extractions") -> None:
        self.payload = payload
        self.tool_name = tool_name
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _FakeAnthropicResponse:
        self.last_kwargs = kwargs
        return _FakeAnthropicResponse(
            content=[_FakeAnthropicBlock(type="tool_use", name=self.tool_name, input=self.payload)],
            usage=_FakeAnthropicUsage(),
        )


class _FakeAnthropicClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.messages = _FakeAnthropicMessages(payload)


class TestAnthropicBackend:
    def test_call_returns_normalized_response(self) -> None:
        backend = AnthropicBackend(ExtractorSettings(api_key="test"))
        backend.inject_client(_FakeAnthropicClient(_SAMPLE_PAYLOAD))
        result = backend.call(
            system_prompt="sys",
            user_message="user",
            tool=record_extractions_tool(),
            max_tokens=1024,
        )
        assert isinstance(result, BackendResponse)
        assert result.tool_input == _SAMPLE_PAYLOAD
        assert result.input_tokens == 100
        assert result.output_tokens == 50
        assert result.cache_read_tokens == 20
        # cost = 100 * 3.00/M + 50 * 15.00/M + 20 * 0.30/M
        assert result.cost_usd > 0

    def test_call_passes_cache_control_in_system(self) -> None:
        client = _FakeAnthropicClient(_SAMPLE_PAYLOAD)
        backend = AnthropicBackend(ExtractorSettings(api_key="test"))
        backend.inject_client(client)
        backend.call(
            system_prompt="long system prompt",
            user_message="user",
            tool=record_extractions_tool(),
            max_tokens=1024,
        )
        kwargs = client.messages.last_kwargs
        assert kwargs["system"][0]["cache_control"] == {"type": "ephemeral"}
        assert kwargs["tool_choice"]["name"] == "record_extractions"

    def test_call_raises_when_no_tool_use_block(self) -> None:
        class _NoToolClient:
            class _M:
                def create(self, **_: Any) -> Any:
                    return _FakeAnthropicResponse(
                        content=[_FakeAnthropicBlock(type="text")],
                        usage=_FakeAnthropicUsage(),
                    )

            messages = _M()

        backend = AnthropicBackend(ExtractorSettings(api_key="test"))
        backend.inject_client(_NoToolClient())
        with pytest.raises(BackendError, match="did not call tool"):
            backend.call(
                system_prompt="sys",
                user_message="user",
                tool=record_extractions_tool(),
                max_tokens=1024,
            )


# ─────────────────────────────────────────────────────────────────────
# OpenAI backend stubs
# ─────────────────────────────────────────────────────────────────────


@dataclass
class _FakeOpenAIFn:
    name: str
    arguments: str


@dataclass
class _FakeOpenAIToolCall:
    function: _FakeOpenAIFn


@dataclass
class _FakeOpenAIMessage:
    tool_calls: list[_FakeOpenAIToolCall]


@dataclass
class _FakeOpenAIChoice:
    message: _FakeOpenAIMessage


@dataclass
class _FakeOpenAIPromptDetails:
    cached_tokens: int = 0


@dataclass
class _FakeOpenAIUsage:
    prompt_tokens: int = 200
    completion_tokens: int = 80
    prompt_tokens_details: _FakeOpenAIPromptDetails | None = None


@dataclass
class _FakeOpenAIResponse:
    choices: list[_FakeOpenAIChoice]
    usage: _FakeOpenAIUsage


class _FakeOpenAIChatCompletions:
    def __init__(self, payload: dict[str, Any], tool_name: str = "record_extractions") -> None:
        self.payload = payload
        self.tool_name = tool_name
        self.last_kwargs: dict[str, Any] = {}

    def create(self, **kwargs: Any) -> _FakeOpenAIResponse:
        self.last_kwargs = kwargs
        return _FakeOpenAIResponse(
            choices=[
                _FakeOpenAIChoice(
                    message=_FakeOpenAIMessage(
                        tool_calls=[
                            _FakeOpenAIToolCall(
                                function=_FakeOpenAIFn(
                                    name=self.tool_name,
                                    arguments=json.dumps(self.payload),
                                )
                            )
                        ]
                    )
                )
            ],
            usage=_FakeOpenAIUsage(
                prompt_tokens_details=_FakeOpenAIPromptDetails(cached_tokens=10)
            ),
        )


class _FakeOpenAIChat:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.completions = _FakeOpenAIChatCompletions(payload)


class _FakeOpenAIClient:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.chat = _FakeOpenAIChat(payload)


class TestOpenAIBackend:
    def test_call_returns_normalized_response(self) -> None:
        backend = OpenAIBackend(ExtractorSettings(model="gpt-4o", api_key="test"))
        backend.inject_client(_FakeOpenAIClient(_SAMPLE_PAYLOAD))
        result = backend.call(
            system_prompt="sys",
            user_message="user",
            tool=record_extractions_tool(),
            max_tokens=1024,
        )
        assert result.tool_input == _SAMPLE_PAYLOAD
        assert result.input_tokens == 200
        assert result.output_tokens == 80
        assert result.cache_read_tokens == 10
        # gpt-4o pricing: 200 * 2.50/M + 80 * 10.00/M
        assert result.cost_usd > 0

    def test_call_translates_tool_to_function_shape(self) -> None:
        client = _FakeOpenAIClient(_SAMPLE_PAYLOAD)
        backend = OpenAIBackend(ExtractorSettings(model="gpt-4o", api_key="test"))
        backend.inject_client(client)
        backend.call(
            system_prompt="sys",
            user_message="user",
            tool=record_extractions_tool(),
            max_tokens=1024,
        )
        kwargs = client.chat.completions.last_kwargs
        assert kwargs["tools"][0]["type"] == "function"
        assert kwargs["tools"][0]["function"]["name"] == "record_extractions"
        assert kwargs["tool_choice"]["type"] == "function"
        # System + user as separate messages.
        roles = [m["role"] for m in kwargs["messages"]]
        assert roles == ["system", "user"]

    def test_call_zero_cost_for_unknown_model(self) -> None:
        backend = OpenAIBackend(ExtractorSettings(model="some-local-llama", api_key="test"))
        backend.inject_client(_FakeOpenAIClient(_SAMPLE_PAYLOAD))
        result = backend.call(
            system_prompt="sys",
            user_message="user",
            tool=record_extractions_tool(),
            max_tokens=1024,
        )
        assert result.cost_usd == 0.0
        assert result.input_tokens == 200  # tokens still tracked

    def test_call_raises_when_no_tool_call(self) -> None:
        class _NoToolCallClient:
            class _Chat:
                class _C:
                    def create(self, **_: Any) -> Any:
                        return _FakeOpenAIResponse(
                            choices=[_FakeOpenAIChoice(message=_FakeOpenAIMessage(tool_calls=[]))],
                            usage=_FakeOpenAIUsage(),
                        )

                completions = _C()

            chat = _Chat()

        backend = OpenAIBackend(ExtractorSettings(model="gpt-4o", api_key="test"))
        backend.inject_client(_NoToolCallClient())
        with pytest.raises(BackendError, match="did not call tool"):
            backend.call(
                system_prompt="sys",
                user_message="user",
                tool=record_extractions_tool(),
                max_tokens=1024,
            )


class TestTranslateTool:
    def test_anthropic_to_openai_shape(self) -> None:
        anth = record_extractions_tool()
        oai = _translate_tool(anth)
        assert oai["type"] == "function"
        assert oai["function"]["name"] == anth["name"]
        assert oai["function"]["description"] == anth["description"]
        # Same JSON-schema body, different wrapper.
        assert oai["function"]["parameters"] == anth["input_schema"]


class TestMockBackend:
    def test_default_response(self) -> None:
        backend = MockBackend()
        backend.set_response(_SAMPLE_PAYLOAD)
        out = backend.call(
            system_prompt="s", user_message="u", tool=record_extractions_tool(), max_tokens=10
        )
        assert out.tool_input == _SAMPLE_PAYLOAD
        assert backend.calls == 1

    def test_per_text_routing(self) -> None:
        backend = MockBackend()
        backend.set_responses_by_text(
            {"alpha": {"entities": [{"name": "A", "type": "Concept"}], "relationships": []}},
            default={"entities": [], "relationships": []},
        )
        a = backend.call(
            system_prompt="s", user_message="alpha", tool=record_extractions_tool(), max_tokens=10
        )
        b = backend.call(
            system_prompt="s", user_message="beta", tool=record_extractions_tool(), max_tokens=10
        )
        assert a.tool_input["entities"][0]["name"] == "A"
        assert b.tool_input["entities"] == []

    def test_uninitialized_raises(self) -> None:
        backend = MockBackend()
        with pytest.raises(BackendError):
            backend.call(
                system_prompt="s", user_message="u", tool=record_extractions_tool(), max_tokens=10
            )

    def test_satisfies_protocol(self) -> None:
        backend: LLMBackend = MockBackend()
        backend.set_response(_SAMPLE_PAYLOAD)  # type: ignore[attr-defined]
        out = backend.call(
            system_prompt="s", user_message="u", tool=record_extractions_tool(), max_tokens=10
        )
        assert isinstance(out, BackendResponse)
