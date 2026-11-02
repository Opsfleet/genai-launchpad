"""DataStream executive assistant on AgentCore Runtime (Phase 2, Task 4).

Every resource ID comes from environment variables that the platform sets on the runtime,
so the same code works for every participant. Models: the Opsfleet LiteLLM gateway (keyless,
budgeted per participant). Tools: AgentCore Gateway via the OAuth2 credential provider (M2M).
Conversation + long-term memory: AgentCore Memory. Optional (per .env flags): AgentCore Code Interpreter and
Browser tools, see sandbox_tools.py.

Identity: the caller signs in as an end user (Cognito user pool) and sends that user's access token; the runtime's
JWT authorizer validates it before this code runs, and the actor (whose memories are read) is the token's
`username` claim, never a caller-chosen header. Replies: one JSON object, or, with `"stream": true` in the payload,
a stream of server-sent events (text deltas and tool calls as they happen, then the same JSON object).
"""

import base64
import json
import os
import uuid
from collections.abc import AsyncIterator

from answers import final_answer
from bedrock_agentcore import BedrockAgentCoreApp, RequestContext
from bedrock_agentcore.identity import requires_access_token
from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig, RetrievalConfig
from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client
from mcp.types import Tool as McpTool
from strands import Agent, tool
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry
from strands.models.openai import OpenAIModel
from strands.tools.mcp import MCPAgentTool, MCPClient

import guardrail
import litellm_gateway
import nws_weather
import sql_guard
from prompt_variants import apply_variant, variant_name
from sandbox_tools import optional_tools, prompt_hints

REGION = os.environ["AWS_REGION"]
MODEL_ID = os.environ["MODEL_ID"]
LITELLM_BASE_URL = os.environ["LITELLM_BASE_URL"]
GATEWAY_URL = os.environ["GATEWAY_URL"]
MEMORY_ID = os.environ["MEMORY_ID"]
MEMORY_STRATEGY_ID = os.environ["MEMORY_STRATEGY_ID"]
MEMORY_PREFERENCE_STRATEGY_ID = os.environ["MEMORY_PREFERENCE_STRATEGY_ID"]
MEMORY_SUMMARY_STRATEGY_ID = os.environ["MEMORY_SUMMARY_STRATEGY_ID"]
CREDENTIAL_PROVIDER_NAME = os.environ["CREDENTIAL_PROVIDER_NAME"]
OAUTH_SCOPE = os.environ["OAUTH_SCOPE"]
ACTOR_CLAIM = "username"
"""Cognito puts the signed-in user's name in this claim of its access tokens (M2M client tokens have none)."""
ACTOR_HEADER = "X-Amzn-Bedrock-AgentCore-Runtime-Custom-Actor-Id"
"""The caller-chosen actor header of the original guide; trusted only by the insecure TRUST_ACTOR_HEADER experiment."""
MEMORY_RELEVANCE_SCORE = 0.3
"""Minimum relevance a long-term fact or past-session summary needs to be retrieved into the conversation."""
ALWAYS = 0.0
"""No relevance threshold: preferences (language, format, units) apply to every question, whatever it is."""
SPECIALIST_FAILED = "The {specialist} specialist failed: {reason}. No data is available from it for this question."
"""Returned to the orchestrator instead of "" so a failed specialist is reported, never filled in with guesses."""
DATA_PROMPT = """You are a data specialist. Query the database (SQLite) to answer questions.

Tables (key columns):
- departments (id, name, description, manager_id, budget)
- employees (id, employee_id, first_name, last_name, email, phone, job_title, department_id -> departments.id,
  manager_id -> employees.id, salary, hire_date, status)
- projects (id, name, description, status, start_date, end_date, budget, department_id, project_manager_id)
- project_assignments (employee_id -> employees.id, project_id -> projects.id, role, allocation_percentage)
- helpdesk_tickets (id, opened_by, subject, body, status, opened_at)
Text values are lowercase (employees.status 'active'; projects.status 'planning', 'active' or 'completed'); department
names are capitalized ('Engineering'). Answer with one query when you can."""
"""The schema saves the specialist 3-5 exploratory queries per question (columns guessed, errors, retries)."""
SEARCH_TOOL = "x_amz_bedrock_agentcore_search"
"""The Gateway's built-in semantic tool search (`search_type = "SEMANTIC"`, terraform/participant/task2_gateway.tf)."""
DATA_TOOLS = ("Run read-only SQL on the DataStream company database: employees, departments, projects, tables", 3)
WEATHER_TOOLS = ("Weather forecast for a location in the United States", 1)
"""(what the specialist asks the Gateway's tool search for, how many of the best-ranked tools it keeps).

Search ranks every tool, best match first, and has no cut-off: the specialist decides how many it needs (query_db
plus the list_tables/describe_table challenge tools; one weather tool)."""

app = BedrockAgentCoreApp()


class ReadOnlyGuardHook(HookProvider):
    """Blocks destructive SQL. Replaces Phase 1's interactive approval: a runtime has no human to ask.

    shared/sql_guard.py decides: only SELECT / EXPLAIN / read-only WITH queries pass.
    """

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Run `guard` before every tool call."""
        registry.add_callback(BeforeToolCallEvent, self.guard)

    def guard(self, event: BeforeToolCallEvent) -> None:
        """Cancel any `query_db` call (direct or via the gateway target) that may write; trim the rest.

        Models often start SQL with a newline or indentation; the Gateway's Cedar policy matches queries that
        begin with SELECT/WITH, so an untrimmed read would be denied and retried.
        """
        if not event.tool_use.get("name", "").endswith("query_db"):
            return
        query = str(event.tool_use.get("input", {}).get("query", ""))
        if sql_guard.is_write(query):
            event.cancel_tool = "Destructive SQL requires human approval and is blocked in production."
        else:
            event.tool_use["input"]["query"] = query.strip()


def actor_from(context: RequestContext) -> str:
    """The signed-in user, from the verified token: never trust caller-supplied identity (a header anyone can set).

    Raises:
        PermissionError: The token names no user (e.g. a machine-to-machine client token).
    """
    actor = insecure_header_actor(context) or token_claims(context).get(ACTOR_CLAIM)
    if not actor:
        raise PermissionError(f"the bearer token has no '{ACTOR_CLAIM}' claim: sign in as a user")
    return str(actor)


def insecure_header_actor(context: RequestContext) -> str:
    """DELIBERATELY INSECURE, off by default: the caller-set actor header, only when TRUST_ACTOR_HEADER=true.

    The Task 4 experiment that reopens the identity hole (TRUST_ACTOR_HEADER=true in .env, then deploy): any signed-in
    user can then name any actor and read that actor's memories. Leave it off; the stage 4 checks warn while it is on.
    """
    if os.getenv("TRUST_ACTOR_HEADER", "false").lower() != "true":
        return ""
    headers = {name.lower(): value for name, value in (context.request_headers or {}).items()}
    return headers.get(ACTOR_HEADER.lower(), "")


def token_claims(context: RequestContext) -> dict:
    """The claims of the request's bearer token ({} when there is none).

    Decoding without checking the signature is safe only because the runtime's JWT authorizer already verified the
    signature, issuer, expiry and client before the request reached this code.
    """
    headers = {name.lower(): value for name, value in (context.request_headers or {}).items()}
    token = headers.get("authorization", "").split(" ")[-1]
    try:
        payload = token.split(".")[1]
        return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (IndexError, ValueError):
        return {}


def make_model() -> OpenAIModel:
    """All model calls go through the LiteLLM gateway, keyless (the runtime role identifies you), guarded if enabled."""
    if guardrail.enabled():
        return guardrail.make_model(MODEL_ID, LITELLM_BASE_URL)
    return litellm_gateway.make_model(MODEL_ID, LITELLM_BASE_URL)


def long_term_retrieval() -> dict[str, RetrievalConfig]:
    """Which long-term records to search before each model call: one namespace prefix per strategy, per actor.

    The session manager fills in {actorId}; a namespace is a path prefix, so the summary entry covers every past
    session of this actor (`.../sessions/<id>`).
    """
    return {
        f"/strategies/{MEMORY_STRATEGY_ID}/actors/{{actorId}}": RetrievalConfig(
            top_k=5, relevance_score=MEMORY_RELEVANCE_SCORE
        ),
        f"/strategies/{MEMORY_PREFERENCE_STRATEGY_ID}/actors/{{actorId}}": RetrievalConfig(
            top_k=5, relevance_score=ALWAYS
        ),
        f"/strategies/{MEMORY_SUMMARY_STRATEGY_ID}/actors/{{actorId}}": RetrievalConfig(
            top_k=2, relevance_score=MEMORY_RELEVANCE_SCORE
        ),
    }


def memory_session_manager(session_id: str, actor_id: str) -> AgentCoreMemorySessionManager:
    """Short-term: this session's turns (events). Long-term: this actor's facts, preferences and session summaries."""
    config = AgentCoreMemoryConfig(
        memory_id=MEMORY_ID, session_id=session_id, actor_id=actor_id, retrieval_config=long_term_retrieval()
    )
    return AgentCoreMemorySessionManager(agentcore_memory_config=config, region_name=REGION)


def search_tools(gateway: MCPClient, need: tuple[str, int]) -> list[MCPAgentTool]:
    """The best-ranked Gateway tools for `need` (query, how many), found by the Gateway's semantic search.

    Only these tools' schemas go into the specialist's context, not every tool behind the Gateway: each schema costs
    input tokens on every model call, and a long tool list makes the model pick the wrong tool more often.
    """
    query, top_k = need
    result = gateway.call_tool_sync(f"search-{uuid.uuid4().hex[:12]}", SEARCH_TOOL, {"query": query})
    if result.get("status") != "success":
        raise RuntimeError(f"Gateway tool search failed: {result.get('content')}")
    found = json.loads("".join(part.get("text", "") for part in result.get("content", []))).get("tools", [])
    ranked = [spec for spec in found if spec.get("name") != SEARCH_TOOL][:top_k]
    return [MCPAgentTool(McpTool.model_validate(spec), gateway) for spec in ranked]


def build_specialists(gateway: MCPClient, results: list[str]) -> list:
    """The data and weather specialists as tools; each searches the Gateway for its tools, then records its answer."""

    @tool
    def data_agent(query: str) -> str:
        """Query and analyze the DataStream Corp database (employees, departments, projects).

        Args:
            query: A database or data analysis question.
        """
        agent = Agent(
            model=make_model(),
            system_prompt=f"{DATA_PROMPT}\n{guardrail.prompt_hint()}",
            tools=search_tools(gateway, DATA_TOOLS),
            hooks=[ReadOnlyGuardHook(), *guardrail.hooks()],
            callback_handler=None,
        )
        return consult(agent, query, "data")

    @tool
    def weather_agent(query: str) -> str:
        """Get the weather forecast for a US location (National Weather Service); says so for non-US places.

        Args:
            query: A weather-related question, including the place.
        """
        agent = Agent(
            model=make_model(),
            system_prompt=nws_weather.WEATHER_PROMPT,
            hooks=guardrail.hooks(),
            tools=search_tools(gateway, WEATHER_TOOLS),
            callback_handler=None,
        )
        return consult(agent, query, "weather")

    def consult(agent: Agent, query: str, specialist: str) -> str:
        """Ask a specialist; an exception (e.g. the gateway's 502 after its retries) becomes an explicit failure."""
        try:
            answer = str(agent(query))
        except Exception as error:
            answer = SPECIALIST_FAILED.format(specialist=specialist, reason=f"{type(error).__name__}: {error}")
        return remember(answer, specialist)

    def remember(answer: str, specialist: str = "requested") -> str:
        """Record a specialist's answer for `final_answer`; an empty one is recorded as an explicit failure."""
        answer = answer.strip() or SPECIALIST_FAILED.format(specialist=specialist, reason="it returned an empty answer")
        results.append(answer)
        return answer

    return [data_agent, weather_agent]


def orchestrator_prompt(actor_id: str, sandbox_tools: list) -> str:
    """System prompt for the orchestrator, plus one hint per enabled optional sandbox tool."""
    return (
        f"You are CEO Alice's executive assistant at DataStream Corp, talking to {actor_id}.\n"
        "Route database questions to data_agent and weather questions to weather_agent; "
        "answer simple company questions directly.\n"
        "<user_context> holds what you remember about the user: facts, preferences and summaries of earlier "
        "sessions. Use it only for who the user is and how they like answers; always follow their stated preferences "
        "(language, format, units) in your final answer. Company data (headcounts, budgets, projects, people) always "
        "comes from data_agent, never from memory or earlier conversations, even when <user_context> mentions it.\n"
        "weather_agent covers US locations only; when it says it can only look up US weather, pass that on "
        "unchanged.\n"
        "Always finish with a final answer for the user that combines the specialists' results.\n"
        "If a specialist reports that it failed, tell the user which part could not be answered; never invent "
        "numbers or use placeholders such as [count].\n"
        f"{prompt_hints(sandbox_tools)}"
        f"\n{guardrail.prompt_hint()}"
    ).strip()


@app.entrypoint
@requires_access_token(scopes=[OAUTH_SCOPE], provider_name=CREDENTIAL_PROVIDER_NAME, auth_flow="M2M")
async def invoke(payload: dict, context: RequestContext, access_token: str) -> dict | AsyncIterator[dict]:
    """`{"prompt": ...}` -> one JSON reply; with `"stream": true`, the events of `run_agent` as server-sent events.

    An optional `"variant"` picks a prompt variant (prompt_variants.py) for A/B comparison; default: the control.
    """
    actor_id, session_id = actor_from(context), context.session_id or "default_session"
    variant = variant_name(payload.get("variant"))
    events = run_agent(str(payload.get("prompt", "")), session_id, actor_id, access_token, variant)
    return events if payload.get("stream") else await last_event(events)


async def run_agent(
    prompt: str, session_id: str, actor_id: str, access_token: str, variant: str = ""
) -> AsyncIterator[dict]:
    """Stream `{"delta": text}` and `{"tool": name}` events as the orchestrator works, then the reply object."""
    specialist_results: list[str] = []
    result = None
    with gateway_client(access_token) as gateway:
        orchestrator = build_orchestrator(gateway, session_id, actor_id, specialist_results)
        variant = apply_variant(orchestrator, variant)
        async for event in orchestrator.stream_async(prompt):
            for item in stream_items(event):
                yield item
            result = event.get("result", result)
    answer = final_answer(str(result or ""), specialist_results)
    yield {"response": answer, "actor_id": actor_id, "session_id": session_id, "variant": variant}


def gateway_client(access_token: str) -> MCPClient:
    """MCP client for the AgentCore Gateway, authorized with the M2M token from the credential provider."""
    headers = {"Authorization": f"Bearer {access_token}"}
    return MCPClient(lambda: streamable_http_client(GATEWAY_URL, http_client=create_mcp_http_client(headers=headers)))


def build_orchestrator(gateway: MCPClient, session_id: str, actor_id: str, specialist_results: list[str]) -> Agent:
    """The orchestrator with both specialists, any enabled sandbox tools and this actor's memory."""
    sandbox_tools = optional_tools()
    return Agent(
        name="Executive Assistant",
        model=make_model(),
        system_prompt=orchestrator_prompt(actor_id, sandbox_tools),
        hooks=guardrail.hooks(),
        tools=[*build_specialists(gateway, specialist_results), *sandbox_tools],
        session_manager=memory_session_manager(session_id, actor_id),
        callback_handler=None,
    )


def stream_items(event: dict) -> list[dict]:
    """What a streaming client sees of one Strands event: text deltas, and the tools the model decided to call."""
    if "data" in event:
        return [{"delta": event["data"]}]
    message = event.get("message") or {}
    if message.get("role") != "assistant":
        return []
    return [{"tool": block["toolUse"]["name"]} for block in message.get("content", []) if "toolUse" in block]


async def last_event(events: AsyncIterator[dict]) -> dict:
    """Drain a stream and keep only its final event (the reply object)."""
    reply: dict = {}
    async for event in events:
        reply = event
    return reply


if __name__ == "__main__":
    app.run()
