"""`bootcamp.py tools`: Gateway tools by target, three measured prompt-token counts and the report (no network)."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import agentcore, tool_search  # noqa: E402

WEATHER = {"name": "Weather___get_us_forecast", "description": "forecast", "inputSchema": {"type": "object"}}
DATABASE = {"name": "DataStreamDatabase___query_db", "description": "sql", "inputSchema": {"type": "object"}}
SEARCH = {"name": agentcore.SEARCH_TOOL, "description": "search", "inputSchema": {"type": "object"}}


def fake_litellm(request: httpx.Request) -> httpx.Response:
    """Bills 100 prompt tokens for the question plus 50 per tool."""
    tools = httpx.Request("POST", request.url, content=request.content).read()
    count = tools.count(b'"type":"function"')
    return httpx.Response(200, json={"usage": {"prompt_tokens": 100 + 50 * count}})


def test_measure_prices_no_tools_every_tool_and_the_search_result(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agentcore, "tool_specs", lambda url, token: [SEARCH, DATABASE, WEATHER])
    monkeypatch.setattr(agentcore, "search_tools", lambda url, token, query: [WEATHER, DATABASE])
    client = httpx.Client(base_url="https://litellm.test", transport=httpx.MockTransport(fake_litellm))
    every, found = tool_search.discover(("https://gw.test/mcp", "token"), "weather", 1)
    result = tool_search.measure(client, "gpt-6-luna", every, found)
    assert result.listed == [DATABASE["name"], WEATHER["name"]] and result.found == [WEATHER["name"]]
    assert (result.no_tools, result.every_tool, result.searched) == (100, 200, 150)
    assert result.per_tool() == 50


def test_openai_tools_keep_name_description_and_schema() -> None:
    assert tool_search.openai_tools([WEATHER]) == [
        {
            "type": "function",
            "function": {"name": WEATHER["name"], "description": "forecast", "parameters": {"type": "object"}},
        }
    ]


def test_by_target_groups_gateway_names() -> None:
    names = [DATABASE["name"], "DataStreamDatabase___list_tables", WEATHER["name"], "plain"]
    assert tool_search.by_target(names) == {
        "DataStreamDatabase": ["query_db", "list_tables"],
        "Weather": ["get_us_forecast"],
        "(gateway)": ["plain"],
    }


def test_report_lists_targets_and_search_then_tokens() -> None:
    listing = "\n".join(tool_search.listing_lines([DATABASE["name"], WEATHER["name"]], [WEATHER["name"]], "weather"))
    assert "Weather: get_us_forecast" in listing and '"weather" -> Weather___get_us_forecast' in listing
    result = tool_search.Measurement([DATABASE["name"], WEATHER["name"]], [WEATHER["name"]], 100, 200, 150)
    text = "\n".join(tool_search.token_lines(result, "gpt-6-luna"))
    assert "(+100, ~50 per tool)" in text and "(+50)" in text and "~10,000 tokens" in text


def test_a_failed_model_call_becomes_a_warning() -> None:
    line = tool_search.token_warning("nova-2-lite", RuntimeError("empty response on every attempt"))
    assert line.startswith("WARNING:") and "nova-2-lite" in line and "llm models" in line


def test_the_warning_never_cuts_a_url_mid_word() -> None:
    help_url = "https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/403"
    error = RuntimeError(
        "Client error '403 Forbidden' for url 'https://llm.bootcamp.labs.sandbox.aws.dev.opsfleet.com/v1/chat/completions'\n"
        f"For more information check: {help_url}"
    )
    line = tool_search.token_warning("nonexistent-model", error)
    assert len(str(error)) > 200 and "en- " not in line and "en-US" not in line.replace(help_url, "")


def test_search_tools_parses_the_gateway_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    reply = '{"tools": [{"name": "Weather___get_us_forecast", "description": "forecast", "inputSchema": {}}]}'
    monkeypatch.setattr(agentcore, "call_tool", lambda url, token, name, arguments: (False, reply))
    assert agentcore.search_tools("u", "t", "weather") == [
        {"name": "Weather___get_us_forecast", "description": "forecast", "inputSchema": {}}
    ]
    monkeypatch.setattr(agentcore, "call_tool", lambda url, token, name, arguments: (True, "denied"))
    with pytest.raises(RuntimeError, match="denied"):
        agentcore.search_tools("u", "t", "weather")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


@pytest.mark.parametrize(
    ("reply", "line"),
    [
        ((True, "Tool Execution Denied"), "ERROR DataStreamDatabase___query_db: Tool Execution Denied"),
        ((False, '[{"n": 1201}]'), 'OK DataStreamDatabase___query_db: [{"n": 1201}]'),
    ],
)
def test_query_through_gateway_sends_the_exact_sql(
    monkeypatch: pytest.MonkeyPatch, reply: tuple[bool, str], line: str
) -> None:
    sent: list[tuple] = []
    monkeypatch.setattr(agentcore, "call_tool", lambda *call: sent.append(call) or reply)
    assert tool_search.query_through_gateway(("https://gw.test/mcp", "token"), "DELETE FROM t") == line
    assert sent == [("https://gw.test/mcp", "token", DATABASE["name"], {"query": "DELETE FROM t"})]
