"""The Gateway Lambda target: tool dispatch by the Gateway's tool name, schemas in sync, no Strands needed."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
LAMBDA_DIR = ROOT / "phase2" / "app" / "weather_lambda"
sys.path.insert(0, str(ROOT / "shared"))
SCHEMA_TYPES = {"string", "number", "integer", "boolean", "array", "object"}


def load(name: str, path: Path) -> ModuleType:
    """Import `path` as a fresh module called `name` (never the copy other tests imported)."""
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handler = load("weather_lambda_handler", LAMBDA_DIR / "handler.py")
TOOLS_JSON = json.loads((LAMBDA_DIR / "tools.json").read_text())


def gateway_context(tool: str) -> SimpleNamespace:
    """A Lambda context as the Gateway sends it: the tool name in the client context."""
    return SimpleNamespace(client_context=SimpleNamespace(custom={handler.TOOL_NAME_KEY: tool}))


def test_dispatches_the_gateway_tool_name(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(handler.nws_weather, "get_us_forecast", lambda lat, lon: calls.append((lat, lon)) or "ok")
    answer = handler.handler({"latitude": "47.6", "longitude": -122.3}, gateway_context("Weather___get_us_forecast"))
    assert answer == {"content": [{"type": "text", "text": "ok"}], "isError": False} and calls == [(47.6, -122.3)]


def text_of(result: dict) -> str:
    assert result["isError"] is True
    return result["content"][0]["text"]


def test_unknown_tool_and_bad_arguments_are_readable_errors() -> None:
    assert "unknown tool 'nope'" in text_of(handler.handler({}, gateway_context("Weather___nope")))
    assert "unknown tool ''" in text_of(handler.handler({}, SimpleNamespace(client_context=None)))
    answer = text_of(handler.handler({"latitude": 47.6}, gateway_context("Weather___get_us_forecast")))
    assert answer.startswith("Error: bad arguments for get_us_forecast (KeyError")


def test_tools_json_matches_the_handler() -> None:
    assert sorted(tool["name"] for tool in TOOLS_JSON) == sorted(handler.TOOLS)
    for tool in TOOLS_JSON:
        schema = tool["inputSchema"]
        assert tool["description"] and schema["type"] == "object"
        assert set(schema.get("required", [])) <= set(schema["properties"])
        assert {prop["type"] for prop in schema["properties"].values()} <= SCHEMA_TYPES


def test_nws_weather_imports_without_strands(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "strands", None)
    module = load("nws_weather_without_strands", ROOT / "shared" / "nws_weather.py")
    assert callable(module.get_us_forecast) and not hasattr(module.get_us_forecast, "tool_spec")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
