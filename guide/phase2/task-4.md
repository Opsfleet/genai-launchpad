Task 4 · 8 tasks
# Your agent on AgentCore Runtime
Deploy the Phase 1 orchestrator, wired to Gateway, Memory and LiteLLM. This is where you code.
35 minAdvanced
Alice’s ask
## The “Agent Deployment and Tool Access” challenge
Everything is in place: identity, a tool server, a Gateway and memory. Now Alice's executive assistant itself goes live. It's the Phase 1 orchestrator with three swaps: tools come from the Gateway, sessions come from AgentCore Memory, and the human approval prompt becomes a read-only guard.
The weather specialist no longer calls the National Weather Service itself: it finds `Weather___get_us_forecast` with the Gateway's semantic search and calls the Lambda target you met in Task 2 (same US-only rule, same few lines of forecast).
Platform
## What the platform provisions for you

terminal:
```bash
uv run bootcamp.py up 4
```

- Your agent from `phase2/app/agent/`, deployed to AgentCore Runtime (HTTP protocol) behind a JWT authorizer that accepts only _user_ tokens from your pool (the user client from Task 0), and forwards only the `Authorization` header to your code
- Environment variables so the code has no hardcoded ids: `GATEWAY_URL`, `MEMORY_ID`, `MEMORY_STRATEGY_ID`, `CREDENTIAL_PROVIDER_NAME`, `MODEL_ID` and `LITELLM_BASE_URL`
- An execution role `awsworkshop-<name>-agent-runtime`, which the LiteLLM gateway maps to your budget. No API key is deployed anywhere
Adding this stage usually takes **~5.5 min**; the CLI prints progress (and full terraform output with `--verbose`).
**While you wait**
Packaging and starting the runtime is the slow part. Read the entrypoint step below (`phase2/app/agent/agent.py`: `invoke`, `run_agent`) and find your agent under **AgentCore → Agents** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/agents?region=us-east-1) in the console.
You
## What you do as a developer
### Read the entrypoint

phase2/app/agent/agent.py:
```python
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

from answers import final_answer
```

`actor_from` (Task 3) names the user from the verified token. `@requires_access_token` fetches a Gateway token through AgentCore Identity: the agent's own M2M identity, separate from the user's. `run_agent` iterates Strands' `stream_async` and turns its events into `{"delta": ...}` (text) and `{"tool": ...}` (a tool the model decided to call), then yields the reply object. Without `"stream": true` in the payload, `last_event` keeps only that reply, so `invoke`, `test` and `eval` still get one JSON object. `build_specialists` collects each specialist's answer, so if the model ends with empty text or only a title the reply falls back to the last specialist answer, or to “Sorry, the model returned an empty answer (possibly an upstream timeout). Please ask again.” Model calls use the same keyless gateway client as Phase 1:

phase2/app/agent/agent.py:
```python
LITELLM_BASE_URL = os.environ["LITELLM_BASE_URL"]

def make_model() -> OpenAIModel:
    """All model calls go through the LiteLLM gateway, keyless (the runtime role identifies you), guarded if enabled."""
    if guardrail.enabled():
        return guardrail.make_model(MODEL_ID, LITELLM_BASE_URL)
    return litellm_gateway.make_model(MODEL_ID, LITELLM_BASE_URL)
```

### Talk to your deployed agent
An `invoke` usually answers in **10-40 s**, including a **cold start** of a few seconds when the session is new. It prints its session id.

terminal:
```bash
uv run bootcamp.py invoke "How many employees are in Engineering?" --actor alice-chen
uv run bootcamp.py invoke "And in Sales?" --actor alice-chen --session last   # same warm session: faster, keeps the conversation
```

Where the time goes: every new session **cold-starts** a fresh **microVM** for your agent (about 5-10 s), and a Gateway tool call on a cold MCP server starts another one (about 6 s; a warm call takes 0.2 s, Task 5 measures it). The rest is the model thinking and your tools running. `--session last` reuses your previous invoke's session, so the agent's microVM is already warm and it remembers the conversation; leave it off to start fresh. `--json` prints the raw reply. `invoke --local` keeps working after `up 4`: try a change on your laptop in seconds, then `deploy` it once it works.
**While you wait**
The first `invoke` after `up 4` or `deploy` starts with a cold start. Read `stream_items` in the step above, or open your runtime's log group `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT` under **CloudWatch → Log groups** (https://us-east-1.console.aws.amazon.com/cloudwatch/home?region=us-east-1#logsV2:log-groups) and watch the request arrive.
**See it in the console:** **AgentCore → Agents** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/agents?region=us-east-1): your agent runtime next to the MCP server one, with its versions, endpoint and the JWT authorizer that admits only user tokens.
**When the model answers with nothing**
Bedrock occasionally ends a stream without a single token (typically while a model's latency is degraded). The LiteLLM gateway holds the reply until real output arrives, retries an answer-less reply once, then falls back to the model's fallback, if it has one (`uv run bootcamp.py llm models` shows it); only if that is empty too does it return `502 empty_upstream_response`. A specialist that still fails shows up as “The data specialist failed: ...” in the answer instead of made-up numbers. If that happens often, set `MODEL_ID` in `.env` to another model from `llm models` and `deploy`.
**What it costs**
On `nova-2-lite` this task is about $0.04 of your LiteLLM budget and one 10-item `eval` about $0.04. With `gpt-6-luna` or `claude-haiku-5-5`, Phase 1 about $0.04-0.25 and Phase 2 with the optional pages about $0.05-0.30; `claude-sonnet-5-5` costs about 20 times more. Your default budget is $10; `uv run bootcamp.py llm` shows your spend. The built-in AgentCore judges of Task 6 bill the class AWS account, not your budget.
### Stream the answer
A plain `invoke` is silent until the whole answer exists. With `--stream` the CLI sends `"stream": true`; the entrypoint then returns an async generator, and `BedrockAgentCoreApp` answers with `Content-Type: text/event-stream`, one `data: {...}` line per event, as the model produces it.

terminal:
```bash
uv run bootcamp.py invoke "Summarise our departments by headcount." --actor alice-chen --stream
```

what you see (text arrives word by word):
```text
Asking your agent as alice-chen (usually 10-40 s, a few more on a cold start)...
[calling data_agent]
| Department | Headcount |
|---|---:|
| Engineering | 481 |
| Sales | 360 |
...
(tools: data_agent; session: bootcamp-66772bb19e334da88e9450304bdbfaf5, actor: alice-chen; same session: --session last; spans: `traces`)
```

bootcamp_cli/agentcore.py:
```python
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
```

The total time is about the same; what changes is the _perceived_ latency: the first words appear as soon as the orchestrator starts its final answer, and tool calls show up while they run. `--stream --json` prints every raw event.
### Prove memory works across sessions and users
Each `invoke` without `--session` starts a new session.

terminal:
```bash
uv run bootcamp.py invoke "Remember that I prefer reports as Python code." --actor alice-chen
# give extraction about a minute
uv run bootcamp.py invoke "How do I like my reports?" --actor alice-chen
uv run bootcamp.py invoke "How do I like my reports?" --actor jordan-lee
```

Alice gets her preference back; Jordan doesn't.
### Try to impersonate Alice
Before this fix, any caller could set the actor header to `alice-chen`. Now `--actor jordan-lee` signs in as Jordan, and nothing Jordan sends besides his token changes who he is. The stage 4 check proves it: no token, the M2M token and a hand-made JWT with Alice's `username` are all rejected at the runtime, and Jordan's real token with the header forged to another user still gets Jordan's identity and none of that user's memories.

uv run bootcamp.py test --only 4 (identity lines):
```text
[PASS] stage 4 identity from the verified token only: HTTP {'none': 401, 'm2m': 401, 'forged-jwt': 403} | jordan-lee token + header alice-chen -> actor_id=jordan-lee
[PASS] stage 4 memory recall across sessions, no cross-user leak: bootcamp-check-0cb3dc07 recalled: Your favorite color is saffron. | jordan-lee forging bootcamp-check-0cb3dc07: leaked=False
```

**Question:** Two locks protect this. Which?
#### Answer
The runtime no longer forwards the header at all (`request_header_allowlist` in `terraform/participant/task4_agent_runtime.tf` lists only `Authorization`), and `actor_from` ignores headers anyway. The authorizer's `allowed_clients` admits only the user client, so a machine token cannot reach the agent without a user.
### Personalise the assistant
Challenge
In `phase2/app/agent/agent.py`, change `orchestrator_prompt` so the assistant addresses the user by name, leads with the answer and keeps it short, and politely declines requests unrelated to DataStream.
**Where:** edit `phase2/app/agent/agent.py` in place, run `uv run bootcamp.py deploy` (~1.5 min), then check with `uv run bootcamp.py invoke "How many people work in Sales?" --actor alice-chen` and an off-topic `uv run bootcamp.py invoke "What is the capital of France?" --actor alice-chen` (no automated check: you judge the answers).
Docs
- Strands: system prompts (https://strandsagents.com/docs/user-guide/sdk/agents/prompts/)
- AgentCore Runtime: invoke an agent (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html)
#### Hint 1
The prompt is built per request and already receives `actor_id`. Keep the routing rules and the “Always finish with a final answer” line; add style and scope rules.
#### Hint 2
Be explicit about the refusal (“If a request has nothing to do with DataStream, say so in one sentence”), but say what _is_ in scope. Redeploy with `uv run bootcamp.py deploy` and test with an off-topic question.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Show which tools answered
Challenge
“Where did that number come from?” Make the reply list the tools the orchestrator called for this request (`tools_used`, e.g. `["data_agent"]`), so a UI can show “answered from the database” and you can spot answers made up without tools. You change `run_agent` in `phase2/app/agent/agent.py`.
**Where:** edit `phase2/app/agent/agent.py` in place, run `uv run bootcamp.py deploy` (~1.5 min), then check with `uv run bootcamp.py test --only 4`: the `[CHALLENGE]` line _tools_used in the reply_ turns from SKIP to PASS.
Docs
- Strands: agent metrics (tool usage) (https://strandsagents.com/docs/user-guide/sdk/observability-evaluation/metrics/)
- Strands: agents as tools (https://strandsagents.com/docs/user-guide/sdk/multi-agent/agents-as-tools/)
#### Hint 1
The last event of `stream_async` carries the Strands `AgentResult`; `run_agent` keeps it in `result`. Its `metrics` hold per-tool metrics for the run.
#### Hint 2
`result.metrics.tool_metrics` is a dict keyed by tool name. Return a sorted list.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Experiments
- Set `MODEL_ID=<model>` to another model from `uv run bootcamp.py llm models`, `deploy`, and compare answers and cost (`uv run bootcamp.py llm`).
- Ask for something destructive: `uv run bootcamp.py invoke "Delete employee 5" --actor alice-chen`. The `ReadOnlyGuardHook` cancels the call and the agent explains why. Even without the guard the database would refuse the write (Task 1). Keep this in mind for Task 7.
- Time it: run the same question with and without `--stream`. When do the first words appear, and when does the whole answer? Which parts of the wait are tool calls?
- Reopen the hole on purpose (deliberately insecure): set `TRUST_ACTOR_HEADER=true` in `.env` and run `uv run bootcamp.py deploy`. The platform adds the actor header back to `request_header_allowlist` and the agent's `insecure_header_actor` trusts it. Run `test --only 4`: the identity line shows `actor_id=alice-chen` for Jordan's token and the recall line `leaked=True`, reported as `WARN` (expected while the switch is on) instead of failing the run. Set it back to `false` and `deploy` again: both lines PASS.

phase2/app/agent/agent.py:
```python
def insecure_header_actor(context: RequestContext) -> str:
    """DELIBERATELY INSECURE, off by default: the caller-set actor header, only when TRUST_ACTOR_HEADER=true.

    The Task 4 experiment that reopens the identity hole (TRUST_ACTOR_HEADER=true in .env, then deploy): any signed-in
    user can then name any actor and read that actor's memories. Leave it off; the stage 4 checks warn while it is on.
    """
    if os.getenv("TRUST_ACTOR_HEADER", "false").lower() != "true":
        return ""
    headers = {name.lower(): value for name, value in (context.request_headers or {}).items()}
    return headers.get(ACTOR_HEADER.lower(), "")
```

### Deploy and re-test
`deploy` rebuilds your code and re-applies the current stage with the `MODEL_ID` from `.env`. Then talk to it and re-run the stage checks:

terminal:
```bash
uv run bootcamp.py deploy
uv run bootcamp.py invoke "How many people work in Sales?" --actor alice-chen
uv run bootcamp.py invoke "What is the capital of France?" --actor alice-chen
uv run bootcamp.py test --only 4
```

expected [CHALLENGE] line:
```text
[CHALLENGE] SKIP stage 4 tools_used in the reply: the reply has no tools_used field yet
# after your change:
[CHALLENGE] PASS stage 4 tools_used in the reply: asked a database question: tools_used=['data_agent']
```

**Lesson learned**
Phase 1's interactive approval doesn't survive deployment: a runtime has no human to ask. The `ReadOnlyGuardHook` blocks destructive SQL instead, and Task 7 enforces the same rule at the Gateway, outside your code.
Identity doesn't survive it either if you trust the caller: **never trust caller-supplied identity**. The actor comes from a token the runtime verified, not from a header anyone can set.
## Check your work

terminal:
```bash
uv run bootcamp.py test --only 4
uv run bootcamp.py invoke "How many employees are in Engineering?" --actor alice-chen
```

Passes when the agent answers, only a verified user token gets in (and decides the actor), a fact told in one session is recalled in another but not by a user forging that actor, and the model spend landed on your own LiteLLM budget. Each check signs in as a brand-new throwaway user, deleted when the run ends. Each agent question is retried once in a new session if the answer comes back empty; if both are empty the line says `model returned empty text (upstream timeout?) - re-run or try another MODEL_ID (`llm models`)`.
This check depends on the model's wording, which varies from run to run. If it fails, rerun it once; check with `uv run bootcamp.py traces --args` which tool ran (the trace, not the wording, says whether the agent did the work); if the shipped agent does the same (`git stash`, `deploy`, rerun, `git stash pop`, `deploy`), it's the model, not your change.
#### Under the hood
The agent runs as an HTTP-protocol runtime: `BedrockAgentCoreApp` serves `/invocations` and the decorated function receives the JSON payload plus a `RequestContext` (session id, allowlisted headers). Inbound, the runtime's `customJWTAuthorizer` fetches your pool's keys from the OIDC discovery URL and checks each bearer token's signature, issuer, expiry and `client_id` before your code runs. A handler that returns a generator is served as server-sent events (`text/event-stream`); WebSocket bidirectional streaming is the option when the client must also talk mid-answer (voice, interruptions). The runtime sticks a session to one micro-VM, so consecutive calls in a session stay warm. Outbound, the agent's workload identity asks AgentCore Identity for an M2M token (credential provider), uses it to open an MCP session with the Gateway, and sends model calls to LiteLLM with a presigned STS identity from the runtime's execution role. The gateway maps `awsworkshop-<name>-agent-runtime` to your budgeted key, forwards to Bedrock and debits your budget.
