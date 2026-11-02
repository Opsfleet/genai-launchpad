"""Clients for the deployed pieces: Cognito M2M token, agent runtime invoke, MCP tools over HTTP."""

import asyncio
import json
import logging
import sys
import time
import urllib.parse
import uuid
from collections.abc import Awaitable, Callable, Iterator

import boto3
import requests
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.shared.exceptions import MCPError

log = logging.getLogger(__name__)
logging.getLogger("client").setLevel(logging.ERROR)
"""mcp's ClientSession logger ("client") warns on every call to the Gateway's search tool at stage 7, where Cedar
hides that tool from tools/list but still answers it."""

FORGED_ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"
"""The header older versions of the agent trusted for the actor; checks now send it forged to prove it is ignored."""
SESSION_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id"
WORKLOAD_TOKEN_HEADER = "WorkloadAccessToken"
"""Where `BedrockAgentCoreApp` reads the workload access token the runtime normally injects (`invoke --local`)."""
SEARCH_TOOL = "x_amz_bedrock_agentcore_search"
"""The built-in tool a Gateway with semantic search (`search_type = "SEMANTIC"`) adds to its tool list."""
INVOKE_READ_SECONDS = 300
"""Server-side runs were observed up to ~215s (plus a cold start), so one answer may take up to 5 minutes."""
INVOKE_TIMEOUT = (10, INVOKE_READ_SECONDS)
"""(connect, read) seconds for every agent call, shared by `invoke` and the stage checks."""
SESSION_PREFIX = "bootcamp-"
CHECK_SESSION_PREFIX = "bootcamp-check-"
"""Sessions opened by `test` start with this, so `traces` can skip them and default to your own `invoke`."""
SYNC_POLL_SECONDS = 5
SYNC_MAX_POLLS = 36


def get_token(outputs: dict[str, str]) -> str:
    """Client-credentials access token for the participant's Cognito app client."""
    response = requests.post(
        outputs["token_url"],
        auth=(outputs["client_id"], outputs["client_secret"]),
        data={"grant_type": "client_credentials", "scope": outputs["oauth_scope"]},
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


def new_session_id(prefix: str = SESSION_PREFIX) -> str:
    """A fresh runtime session id (AgentCore requires at least 33 characters).

    Args:
        prefix: SESSION_PREFIX for participant invokes, CHECK_SESSION_PREFIX for smoke checks.

    Returns:
        `prefix` followed by 32 random hex characters.
    """
    return f"{prefix}{uuid.uuid4().hex}"


def is_check_session(session_id: str) -> bool:
    """Whether a session was opened by a stage check rather than by the participant."""
    return session_id.startswith(CHECK_SESSION_PREFIX)


def invoke_agent(outputs: dict[str, str], token: str, prompt: str, session_id: str) -> str:
    """Call the HTTP agent runtime with a user's bearer token and return its text response."""
    body = invoke_agent_body(outputs, token, prompt, session_id)
    return str(body.get("response", body))


def runtime_url(outputs: dict[str, str]) -> str:
    """The participant's agent runtime (DEFAULT endpoint), or the local agent when `local_agent_url` is set."""
    if outputs.get("local_agent_url"):
        return f"{outputs['local_agent_url']}/invocations"
    arn = urllib.parse.quote(outputs["agent_runtime_arn"], safe="")
    return f"https://bedrock-agentcore.{outputs['region']}.amazonaws.com/runtimes/{arn}/invocations?qualifier=DEFAULT"


def local_headers(outputs: dict[str, str]) -> dict[str, str]:
    """For a local agent: the workload access token the runtime would otherwise pass it (none for the runtime)."""
    token = outputs.get("local_workload_token")
    return {WORKLOAD_TOKEN_HEADER: token} if token else {}


def invoke_headers(token: str, session_id: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    """Bearer token (the caller's identity), session id and any `extra` headers for one invocation."""
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", SESSION_HEADER: session_id}
    return headers | (extra or {})


def invoke_agent_body(
    outputs: dict[str, str],
    token: str,
    prompt: str,
    session_id: str,
    extra_headers: dict[str, str] | None = None,
    extra_payload: dict | None = None,
) -> dict:
    """Call the HTTP agent runtime and return its whole JSON reply (non-object replies wrapped as "response").

    `extra_payload` adds keys next to the prompt, e.g. `{"variant": "B"}` for an A/B comparison (`eval --variants`).

    Raises:
        RuntimeError: The runtime answered with a non-2xx status.
    """
    headers = invoke_headers(token, session_id, extra_headers) | local_headers(outputs)
    payload = {"prompt": prompt} | (extra_payload or {})
    response = requests.post(runtime_url(outputs), json=payload, headers=headers, timeout=INVOKE_TIMEOUT)
    if not response.ok:
        raise RuntimeError(f"agent returned HTTP {response.status_code}: {response.text[:300]}")
    body = response.json()
    return body if isinstance(body, dict) else {"response": str(body)}


def stream_agent(outputs: dict[str, str], token: str, prompt: str, session_id: str) -> Iterator[dict]:
    """Ask with `"stream": true` and yield each server-sent event as it arrives (the last one is the reply object).

    An agent that does not stream yet answers with plain JSON, which is yielded as a single event.

    Raises:
        RuntimeError: The runtime answered with a non-2xx status.
    """
    payload = {"prompt": prompt, "stream": True}
    headers = invoke_headers(token, session_id) | local_headers(outputs)
    url = runtime_url(outputs)
    with requests.post(url, json=payload, headers=headers, timeout=INVOKE_TIMEOUT, stream=True) as response:
        if not response.ok:
            raise RuntimeError(f"agent returned HTTP {response.status_code}: {response.text[:300]}")
        if "text/event-stream" not in response.headers.get("Content-Type", ""):
            yield response.json()
            return
        yield from sse_events(response.iter_lines(decode_unicode=True))


def sse_events(lines: Iterator[str]) -> Iterator[dict]:
    """The JSON objects of `data: ...` lines in a server-sent event stream (non-object data wrapped as "delta")."""
    for line in lines:
        if not line or not line.startswith("data:"):
            continue
        event = json.loads(line.removeprefix("data:").strip())
        yield event if isinstance(event, dict) else {"delta": str(event)}


def invoke_status(outputs: dict[str, str], token: str | None) -> int:
    """HTTP status of an invocation with `token` (None: no Authorization header), for the identity checks."""
    headers = invoke_headers(token or "", new_session_id(CHECK_SESSION_PREFIX))
    if token is None:
        headers.pop("Authorization")
    response = requests.post(runtime_url(outputs), json={"prompt": "hi"}, headers=headers, timeout=INVOKE_TIMEOUT)
    return response.status_code


def list_tools(url: str, token: str) -> list[str]:
    """Names of the tools an MCP endpoint (runtime or gateway) exposes."""
    return list(list_tool_schemas(url, token))


def list_tool_schemas(url: str, token: str) -> dict[str, dict]:
    """Tool name -> JSON input schema for every tool an MCP endpoint exposes."""
    return asyncio.run(_mcp(url, token, _tool_schemas))


def call_tool(url: str, token: str, name: str, arguments: dict) -> tuple[bool, str]:
    """Call one MCP tool; returns (is_error, text). Gateway policy denials arrive as MCPError."""
    return asyncio.run(_mcp(url, token, lambda session: _call(session, name, arguments)))


def tool_specs(url: str, token: str) -> list[dict]:
    """Every tool an MCP endpoint lists, as `{name, description, inputSchema}`: what a model is given per tool."""
    return asyncio.run(_mcp(url, token, _specs))


def search_tools(url: str, token: str, query: str) -> list[dict]:
    """The tools a Gateway's semantic search (SEARCH_TOOL) returns for `query`, shaped like `tool_specs`.

    Raises:
        RuntimeError: The search call failed (e.g. semantic search is off, or a policy denied it).
    """
    is_error, text = call_tool(url, token, SEARCH_TOOL, {"query": query})
    if is_error:
        raise RuntimeError(f"{SEARCH_TOOL} failed: {text[:200]}")
    return [_spec(tool) for tool in json.loads(text).get("tools", [])]


def _spec(tool: dict) -> dict:
    """Just the parts of a tool definition a model receives."""
    return {
        "name": tool["name"],
        "description": tool.get("description") or "",
        "inputSchema": tool.get("inputSchema") or {},
    }


async def _specs(session: ClientSession) -> list[dict]:
    tools = (await session.list_tools()).tools
    return [_spec({"name": t.name, "description": t.description, "inputSchema": t.input_schema}) for t in tools]


async def _tool_schemas(session: ClientSession) -> dict[str, dict]:
    return {tool.name: tool.input_schema or {} for tool in (await session.list_tools()).tools}


async def _call(session: ClientSession, name: str, arguments: dict) -> tuple[bool, str]:
    try:
        result = await session.call_tool(name, arguments)
    except MCPError as error:
        return True, str(error)
    return bool(result.is_error), " ".join(getattr(part, "text", "") for part in result.content)


async def _mcp[T](url: str, token: str, action: Callable[[ClientSession], Awaitable[T]]) -> T:
    """Open one MCP session to `url` with a bearer token and run `action` on it."""
    http_client = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
    async with streamable_http_client(url, http_client=http_client, terminate_on_close=False) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            return await action(session)


def synchronize_gateway(session, gateway_id: str, target_ids: list[str] | None = None) -> None:
    """Make the Gateway re-read its MCP targets' tool lists and wait until they are READY.

    A Gateway caches each MCP target's tools when the target is created; it does not notice that the MCP server
    behind it was redeployed with new tools (e.g. list_tables), so `deploy` must ask it to synchronize. Lambda
    targets carry their tool schema inline, so Terraform passes only the MCP target's id.

    Args:
        session: boto3 session.
        gateway_id: The Gateway to synchronize.
        target_ids: Targets to synchronize; None means every target of the Gateway.
    """
    control = session.client("bedrock-agentcore-control")
    if target_ids is None:
        target_ids = [item["targetId"] for item in control.list_gateway_targets(gatewayIdentifier=gateway_id)["items"]]
    if not target_ids:
        return
    log.info("Synchronizing the Gateway's tool list with your MCP server")
    control.synchronize_gateway_targets(gatewayIdentifier=gateway_id, targetIdList=target_ids)
    for target_id in target_ids:
        _wait_target_ready(control, gateway_id, target_id)


def _wait_target_ready(control, gateway_id: str, target_id: str) -> None:
    """Poll one gateway target until it leaves SYNCHRONIZING.

    Raises:
        RuntimeError: The target ended in a failed state or did not settle in time.
    """
    for _ in range(SYNC_MAX_POLLS):
        target = control.get_gateway_target(gatewayIdentifier=gateway_id, targetId=target_id)
        if target["status"] == "READY":
            return
        if target["status"] != "SYNCHRONIZING":
            raise RuntimeError(f"gateway target {target_id} is {target['status']}: {target.get('statusReasons')}")
        time.sleep(SYNC_POLL_SECONDS)
    raise RuntimeError(f"gateway target {target_id} still synchronizing after {SYNC_POLL_SECONDS * SYNC_MAX_POLLS}s")


def main(argv: list[str]) -> int:
    """`python -m bootcamp_cli.agentcore sync-gateway <gateway_id> [target_id ...]`: run by Terraform after the MCP
    server changes."""
    if len(argv) < 2 or argv[0] != "sync-gateway":
        print("usage: python -m bootcamp_cli.agentcore sync-gateway <gateway_id> [target_id ...]", file=sys.stderr)
        return 2
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    synchronize_gateway(boto3.Session(), argv[1], argv[2:] or None)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
