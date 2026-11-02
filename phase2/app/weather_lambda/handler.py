"""The weather tools as an AgentCore Gateway Lambda target (Phase 2, Task 2).

The Gateway invokes this function with the tool's arguments as the event; the tool it was called as arrives in
`context.client_context.custom["bedrockAgentCoreToolName"]` as `<target>___<tool>` (e.g. `Weather___get_us_forecast`).
Every tool in TOOLS needs a schema in tools.json: Terraform turns that file into the target's inline tool schema
(what the Gateway lists and indexes for semantic search) and into the Cedar permit of Task 7. The NWS logic itself
is shared/nws_weather.py, the same code Phase 1's weather specialist calls in-process.
"""

from collections.abc import Callable
from typing import Any

import nws_weather

TOOL_NAME_KEY = "bedrockAgentCoreToolName"
TARGET_SEPARATOR = "___"


def get_us_forecast(arguments: dict[str, Any]) -> str:
    """The next few NWS forecast periods for a US latitude/longitude (compact text, US-only reply elsewhere)."""
    return nws_weather.get_us_forecast(float(arguments["latitude"]), float(arguments["longitude"]))


TOOLS: dict[str, Callable[[dict[str, Any]], str]] = {"get_us_forecast": get_us_forecast}
"""Tool name (as in tools.json) -> implementation."""


def tool_name(context: Any) -> str:
    """The bare tool name the Gateway called (`Weather___get_us_forecast` -> `get_us_forecast`), or ""."""
    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    return str(custom.get(TOOL_NAME_KEY, "")).split(TARGET_SEPARATOR)[-1]


def mcp_text(text: str, is_error: bool = False) -> dict[str, Any]:
    """An MCP tool result. The Gateway passes `content` through as is; a bare string would reach the model
    JSON-quoted, with every newline escaped."""
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    """Lambda entry point: run the requested tool; problems come back as an `Error: ...` text the model can read.

    Args:
        event: The tool's arguments, as the model sent them through the Gateway.
        context: The Lambda context; carries the Gateway's tool name.

    Returns:
        The tool's answer as an MCP tool result.
    """
    name = tool_name(context)
    tool = TOOLS.get(name)
    if tool is None:
        return mcp_text(f"Error: unknown tool {name!r}; this target serves {sorted(TOOLS)}.", is_error=True)
    try:
        return mcp_text(tool(event))
    except (KeyError, TypeError, ValueError) as error:
        return mcp_text(f"Error: bad arguments for {name} ({type(error).__name__}: {error}).", is_error=True)
