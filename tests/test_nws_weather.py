"""The weather specialist's NWS tool: two calls, a few trimmed lines, clear errors, US-only (no network)."""

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
import nws_weather  # noqa: E402

FORECAST_URL = "https://api.weather.gov/gridpoints/SEW/125,68/forecast"
POINT = {
    "properties": {
        "forecast": FORECAST_URL,
        "relativeLocation": {"properties": {"city": "Seattle", "state": "WA"}},
    }
}
PERIOD = {
    "temperature": 69,
    "temperatureUnit": "F",
    "windSpeed": "5 mph",
    "windDirection": "NW",
    "shortForecast": "Partly Sunny",
    "detailedForecast": "A long paragraph the model never needs. " * 20,
}
FORECAST = {"properties": {"periods": [{**PERIOD, "name": f"Period {index}"} for index in range(14)]}}


def _serve(monkeypatch: pytest.MonkeyPatch, handler) -> list[httpx.Request]:
    """Route the tool's HTTP client through `handler`; return the list of requests it receives."""
    seen: list[httpx.Request] = []
    real_client = nws_weather.make_client

    def recording(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    def client() -> httpx.Client:
        configured = real_client()
        return httpx.Client(
            base_url=configured.base_url, headers=configured.headers, transport=httpx.MockTransport(recording)
        )

    monkeypatch.setattr(nws_weather, "make_client", client)
    return seen


def _nws(request: httpx.Request) -> httpx.Response:
    """A minimal NWS: the Seattle point and its forecast."""
    if request.url.path.startswith("/points/"):
        return httpx.Response(200, json=POINT)
    return httpx.Response(200, json=FORECAST)


def test_forecast_is_a_few_short_lines(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _serve(monkeypatch, _nws)
    answer = nws_weather.get_us_forecast(47.60621, -122.33207)
    assert answer.splitlines() == [
        "NWS forecast for Seattle, WA:",
        *[f"Period {index}: 69°F, wind 5 mph NW, Partly Sunny" for index in range(nws_weather.FORECAST_PERIODS)],
    ]
    assert "long paragraph" not in answer
    assert [str(request.url) for request in seen] == ["https://api.weather.gov/points/47.6062,-122.3321", FORECAST_URL]


def test_requests_identify_the_application(monkeypatch: pytest.MonkeyPatch) -> None:
    seen = _serve(monkeypatch, _nws)
    nws_weather.get_us_forecast(47.6, -122.3)
    assert all(request.headers["User-Agent"] == nws_weather.USER_AGENT for request in seen)


def test_point_outside_the_us_says_us_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _serve(monkeypatch, lambda request: httpx.Response(404, json={"title": "Data Unavailable For Requested Point"}))
    answer = nws_weather.get_us_forecast(51.5074, -0.1278)
    assert answer.startswith("Error:")
    assert nws_weather.US_ONLY_REPLY in answer


def test_timeout_is_a_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def slow(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _serve(monkeypatch, slow)
    assert "did not answer within" in nws_weather.get_us_forecast(47.6, -122.3)


@pytest.mark.parametrize(
    "response",
    [httpx.Response(500, text="boom"), httpx.Response(200, json={"unexpected": True})],
    ids=["server-error", "unexpected-body"],
)
def test_other_failures_are_clear_errors(monkeypatch: pytest.MonkeyPatch, response: httpx.Response) -> None:
    _serve(monkeypatch, lambda request: response)
    assert nws_weather.get_us_forecast(47.6, -122.3).startswith("Error: the National Weather Service request failed")


def test_prompt_gives_the_exact_us_only_reply() -> None:
    assert nws_weather.US_ONLY_REPLY == "I can only look up US weather (National Weather Service)."
    assert nws_weather.US_ONLY_REPLY in nws_weather.WEATHER_PROMPT
    assert "get_us_forecast" in nws_weather.WEATHER_PROMPT


def test_tool_schema_takes_coordinates() -> None:
    schema = nws_weather.get_us_forecast.tool_spec["inputSchema"]["json"]
    assert set(schema["required"]) == {"latitude", "longitude"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
