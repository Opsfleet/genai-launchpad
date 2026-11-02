"""Client-side empty-response guard of the shared gateway model."""

import asyncio
import sys
from collections.abc import AsyncGenerator
from pathlib import Path

import pytest
from strands.models.openai import OpenAIModel

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
import litellm_gateway as gw  # noqa: E402

START = {"messageStart": {"role": "assistant"}}
STOP = {"messageStop": {"stopReason": "end_turn"}}


def _usage(output_tokens: int) -> dict:
    return {"metadata": {"usage": {"inputTokens": 5, "outputTokens": output_tokens, "totalTokens": 5}, "metrics": {}}}


def _collect(monkeypatch: pytest.MonkeyPatch, events: list[dict]) -> list[dict]:
    """Run GatewayModel.stream over scripted upstream events and return what it yields."""

    async def scripted(self, *args, **kwargs) -> AsyncGenerator[dict]:
        for event in events:
            yield event

    monkeypatch.setattr(OpenAIModel, "stream", scripted)
    model = gw.GatewayModel("https://gateway.example", api_key="sk-test", model_id="m")

    async def drain() -> list[dict]:
        return [event async for event in model.stream([])]

    return asyncio.run(drain())


def test_text_reply_streams_through(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [START, {"contentBlockDelta": {"delta": {"text": "42"}}}, STOP, _usage(3)]
    assert _collect(monkeypatch, events) == events


def test_tool_call_counts_as_output(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [START, {"contentBlockStart": {"start": {"toolUse": {"name": "t", "toolUseId": "1"}}}}, STOP]
    assert _collect(monkeypatch, events) == events


def test_reasoning_only_reply_with_tokens_is_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    events = [START, STOP, _usage(17)]
    assert _collect(monkeypatch, events) == events


@pytest.mark.parametrize("events", [[START, STOP], [START, STOP, _usage(0)]], ids=["no_usage", "zero_tokens"])
def test_empty_reply_raises(monkeypatch: pytest.MonkeyPatch, events: list[dict]) -> None:
    with pytest.raises(gw.EmptyModelResponseError):
        _collect(monkeypatch, events)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))


HISTORY = [
    {"role": "user", "content": [{"text": "How many in Sales?"}]},
    {"role": "assistant", "content": [{"toolUse": {"toolUseId": "t1", "name": "query_db", "input": {"sql": "1"}}}]},
    {"role": "user", "content": [{"toolResult": {"toolUseId": "t1", "content": [{"text": "360"}]}}]},
]


def test_a_tool_less_request_carries_its_tool_history_as_text() -> None:
    """Summarization calls send no tools; Bedrock would reject raw tool blocks there ("toolConfig must be defined")."""
    model = gw.GatewayModel("http://gateway", api_key="sk-test", model_id="m")
    sent = str(model.format_request(HISTORY)["messages"])
    assert "tool_calls" not in sent and "query_db" in sent and "360" in sent
    with_tools = model.format_request(HISTORY, [{"name": "query_db", "description": "d", "inputSchema": {"json": {}}}])
    assert any(message.get("tool_calls") for message in with_tools["messages"])


def test_model_unavailable_explains_bedrock_outages_only() -> None:
    outage = (
        'litellm.ServiceUnavailableError: BedrockException - {"message":"Bedrock is unable to process your request."}'
    )
    hint = gw.model_unavailable("gpt-6-luna", outage)
    assert hint and "gpt-6-luna" in hint and "llm models" in hint
    assert gw.model_unavailable("gpt-6-luna", "budget_exceeded: over budget") is None


def test_gateway_down_explains_503_only() -> None:
    assert "daily hours" in gw.gateway_down(503)
    assert gw.gateway_down(502) is None and gw.gateway_down(None) is None
