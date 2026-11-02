"""US weather for the weather specialist: one small tool over the National Weather Service API (api.weather.gov).

The NWS answers `/points/{lat},{lon}` with a forecast URL, and that forecast with ~14 periods of GeoJSON. Handing
those raw documents to a model costs 8K-75K input tokens per question; `get_us_forecast` makes both calls itself and
returns a few short lines instead (~100 tokens). The NWS only covers the United States: a point outside it is
answered with `US_ONLY_REPLY`, which the specialist prompt also tells the model to use for non-US places.
Used by Phase 1 Task 7 and copied into every Phase 2 app zip by bootcamp_cli.build, so both agents behave the same.
In Phase 2 it runs behind the AgentCore Gateway as a Lambda target (phase2/app/weather_lambda); that zip ships httpx
but not Strands, so there `tool` falls back to a no-op decorator and `get_us_forecast` stays a plain function.
"""

from collections.abc import Callable
from typing import Any

import httpx

try:
    from strands import tool
except ImportError:

    def tool(function: Callable[..., str]) -> Callable[..., str]:
        """Without Strands (the Gateway Lambda) a tool is just the function itself."""
        return function


NWS_BASE_URL = "https://api.weather.gov"
USER_AGENT = "DataStreamCorp-AgentCore-Bootcamp/1.0 (+https://www.opsfleet.com)"
"""The NWS rejects requests without a User-Agent that identifies the application and a contact."""
TIMEOUT_SECONDS = 10.0
FORECAST_PERIODS = 4
"""How many forecast periods (e.g. "Tonight", "Friday", "Friday Night", "Saturday") the tool returns."""
US_ONLY_REPLY = "I can only look up US weather (National Weather Service)."

WEATHER_PROMPT = f"""You are a weather specialist for US locations only, using the National Weather Service.
- For a place in the United States, call get_us_forecast with its latitude and longitude in decimal degrees,
  then answer concisely from the forecast periods it returns.
- For any place outside the United States, do not call the tool; reply exactly: {US_ONLY_REPLY}
- If the tool returns an error, say that the forecast is unavailable; never guess the weather."""


class NotUsLocationError(LookupError):
    """The NWS has no forecast for this point (it only covers the United States)."""


def make_client() -> httpx.Client:
    """HTTP client for the NWS: identifying User-Agent, GeoJSON accept header, timeout, redirects followed."""
    headers = {"User-Agent": USER_AGENT, "Accept": "application/geo+json"}
    return httpx.Client(base_url=NWS_BASE_URL, headers=headers, timeout=TIMEOUT_SECONDS, follow_redirects=True)


def fetch_json(client: httpx.Client, url: str) -> dict[str, Any]:
    """GET a NWS document.

    Args:
        client: Client from `make_client`.
        url: Absolute URL or a path relative to NWS_BASE_URL.

    Returns:
        The decoded JSON body.

    Raises:
        NotUsLocationError: the NWS answered 404 (no data for this point).
        httpx.HTTPError: timeouts, connection errors and other non-2xx answers.
    """
    response = client.get(url)
    if response.status_code == 404:
        raise NotUsLocationError(url)
    response.raise_for_status()
    return response.json()


def point_forecast(client: httpx.Client, latitude: float, longitude: float) -> tuple[str, list[dict[str, Any]]]:
    """Resolve a point to its place name and forecast periods (two NWS calls).

    Args:
        client: Client from `make_client`.
        latitude: Decimal degrees.
        longitude: Decimal degrees.

    Returns:
        ("City, ST", forecast periods in time order).
    """
    point = fetch_json(client, f"/points/{latitude:.4f},{longitude:.4f}")["properties"]
    place = point.get("relativeLocation", {}).get("properties", {})
    name = ", ".join(part for part in (place.get("city"), place.get("state")) if part)
    periods = fetch_json(client, point["forecast"])["properties"]["periods"]
    return name or f"{latitude:.4f},{longitude:.4f}", periods


def format_period(period: dict[str, Any]) -> str:
    """One forecast period as `Tonight: 54°F, wind 5 mph NW, Mostly Cloudy`."""
    wind = " ".join(str(part) for part in (period.get("windSpeed"), period.get("windDirection")) if part)
    temperature = f"{period.get('temperature')}°{period.get('temperatureUnit', '')}"
    return f"{period.get('name')}: {temperature}, wind {wind or 'n/a'}, {period.get('shortForecast')}"


@tool
def get_us_forecast(latitude: float, longitude: float) -> str:
    """Get the National Weather Service forecast for a location in the United States (next few periods).

    Args:
        latitude: Latitude of the US location in decimal degrees, e.g. 47.6062 for Seattle.
        longitude: Longitude of the US location in decimal degrees, e.g. -122.3321 for Seattle.
    """
    try:
        with make_client() as client:
            place, periods = point_forecast(client, latitude, longitude)
    except NotUsLocationError:
        return f"Error: no NWS forecast for {latitude},{longitude}. {US_ONLY_REPLY}"
    except httpx.TimeoutException:
        return f"Error: the National Weather Service did not answer within {TIMEOUT_SECONDS:g}s; try again."
    except (httpx.HTTPError, KeyError, ValueError) as error:
        return f"Error: the National Weather Service request failed ({type(error).__name__}: {error})."
    lines = [format_period(period) for period in periods[:FORECAST_PERIODS]]
    return "\n".join([f"NWS forecast for {place}:", *lines])
