"""`bootcamp.py tools`: your Gateway's tools per target, and what semantic tool search saves in prompt tokens.

`tools --sql "..."` instead sends one `query_db` call straight to the Gateway, no model involved, so you see exactly
what the Gateway's Cedar policy (Task 7) and the database do with that SQL.

The tool list and the search result need no model and print first. Then, measured, not estimated: the same one-line
question goes to your LiteLLM model three times (no tools, every Gateway tool, only the tools the Gateway's search
returned) and each reply's `usage.prompt_tokens` is what that tool list costs on every single model call (a failed
model call prints a warning instead). A Gateway with hundreds of tools makes the difference obvious.
"""

import textwrap
from collections import defaultdict
from dataclasses import dataclass

import httpx

from bootcamp_cli import agentcore
from bootcamp_cli.checks import GATEWAY_TOOL

QUESTION = "What will the weather be like in Seattle tomorrow?"
DEFAULT_QUERY = "weather forecast for a US city"
DEFAULT_TOP_K = 1
"""Search ranks every tool with no cut-off; like the agent's specialists, keep only the best few."""
SCALE_TOOLS = 200
"""Tool count used to extrapolate the per-tool cost ("a Gateway in front of a whole company's APIs")."""
TARGET_SEPARATOR = "___"


@dataclass(frozen=True)
class Measurement:
    """Tool lists and prompt tokens for one question with no tools, every tool and the search result."""

    listed: list[str]
    found: list[str]
    no_tools: int
    every_tool: int
    searched: int

    def per_tool(self) -> float:
        """Average prompt tokens one tool schema adds."""
        return (self.every_tool - self.no_tools) / max(len(self.listed), 1)


def openai_tools(specs: list[dict]) -> list[dict]:
    """MCP tool specs in the OpenAI `tools` format LiteLLM expects."""
    return [
        {
            "type": "function",
            "function": {"name": s["name"], "description": s["description"], "parameters": s["inputSchema"]},
        }
        for s in specs
    ]


def prompt_tokens(client: httpx.Client, model: str, specs: list[dict]) -> int:
    """Prompt tokens LiteLLM bills for QUESTION when the model is given `specs` as tools (one tiny completion)."""
    body: dict = {"model": model, "messages": [{"role": "user", "content": QUESTION}], "max_tokens": 16}
    if specs:
        body["tools"] = openai_tools(specs)
    response = client.post("/v1/chat/completions", json=body, timeout=120).raise_for_status()
    return int(response.json()["usage"]["prompt_tokens"])


def discover(gateway: tuple[str, str], query: str, top_k: int) -> tuple[list[dict], list[dict]]:
    """Every Gateway tool (without the built-in search tool) and the best `top_k` matches for `query`; no model.

    Args:
        gateway: (Gateway URL, Cognito bearer token).
        query: What to ask the Gateway's semantic search for.
        top_k: How many of the best-ranked search results to keep.
    """
    every = [spec for spec in agentcore.tool_specs(*gateway) if spec["name"] != agentcore.SEARCH_TOOL]
    return every, agentcore.search_tools(*gateway, query)[:top_k]


def measure(client: httpx.Client, model: str, every: list[dict], found: list[dict]) -> Measurement:
    """Price three tool lists (none, every tool, the search result) with one tiny completion each.

    Args:
        client: httpx client on your LiteLLM gateway (keyless).
        model: LiteLLM model alias.
        every: Every Gateway tool spec (`discover`).
        found: The tool specs semantic search returned (`discover`).

    Returns:
        The tool names and the three prompt-token counts.
    """
    counts = [prompt_tokens(client, model, specs) for specs in ([], every, found)]
    return Measurement(names(every), names(found), *counts)


def names(specs: list[dict]) -> list[str]:
    """The tool names of MCP tool specs."""
    return [spec["name"] for spec in specs]


def by_target(names: list[str]) -> dict[str, list[str]]:
    """{target: [tool, ...]} from `<target>___<tool>` names."""
    groups: dict[str, list[str]] = defaultdict(list)
    for name in names:
        target, _, tool = name.rpartition(TARGET_SEPARATOR)
        groups[target or "(gateway)"].append(tool)
    return dict(groups)


def listing_lines(listed: list[str], found: list[str], query: str) -> list[str]:
    """The model-free part of the `tools` report: tools per target and what semantic search returned."""
    targets = [f"  {target}: {', '.join(tools)}" for target, tools in by_target(listed).items()]
    return [
        f"Gateway tools ({len(listed)}, plus the built-in {agentcore.SEARCH_TOOL}):",
        *targets,
        f'Semantic search "{query}" -> {", ".join(found) or "(nothing)"}',
    ]


def token_warning(model: str, error: Exception) -> str:
    """The line printed instead of the token comparison when the model call failed (the listing above stands).

    The reason is shortened at whole words only (`break_on_hyphens=False`), so a URL in httpx's message such as
    `https://developer.mozilla.org/en-US/...` is kept whole or dropped, never cut at its hyphen.
    """
    reason = textwrap.shorten(str(error), 200, break_on_hyphens=False)
    return (
        f"WARNING: could not measure prompt tokens on {model} ({type(error).__name__}: {reason}). "
        "The tool list above is complete; to compare token costs, set MODEL_ID in .env to another model from "
        "`uv run bootcamp.py llm models` and re-run `tools`."
    )


def token_lines(result: Measurement, model: str) -> list[str]:
    """Prompt tokens with no tools, every tool and the search result, plus what every tool would cost at scale."""
    every = f"every tool ({len(result.listed)})"
    searched = f"search, top {len(result.found)}"
    return [
        f'Prompt tokens for "{QUESTION}" on {model}:',
        f"  {'no tools':<18} {result.no_tools:>6}",
        f"  {every:<18} {result.every_tool:>6}  (+{result.every_tool - result.no_tools}, "
        f"~{result.per_tool():.0f} per tool)",
        f"  {searched:<18} {result.searched:>6}  (+{result.searched - result.no_tools})",
        f"At {SCALE_TOOLS} tools, loading every tool would add ~{result.per_tool() * SCALE_TOOLS:,.0f} tokens to every "
        "model call; with search the agent pays only for the few tools that match.",
    ]


def query_through_gateway(gateway: tuple[str, str], sql: str) -> str:
    """`tools --sql`: one `query_db` call through the Gateway, reported as ERROR (e.g. a Cedar denial) or OK.

    Args:
        gateway: (Gateway URL, Cognito bearer token).
        sql: The exact query to send.

    Returns:
        One line: the outcome, the tool and its reply text (rows as JSON, or the error message).
    """
    is_error, text = agentcore.call_tool(*gateway, GATEWAY_TOOL, {"query": sql})
    return f"{'ERROR' if is_error else 'OK'} {GATEWAY_TOOL}: {text}"
