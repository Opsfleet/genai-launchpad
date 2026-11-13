Task 2 · 8 tasks
# AgentCore Gateway
One governed front door for every tool: two target types, and semantic search to find the right tool.
35 minMedium
Alice’s ask
## The “Tool Discovery” challenge
Today there's one tool server. Tomorrow there'll be ten, each with its own auth. Alice's agent should talk to _one_ endpoint that knows every tool and handles credentials for it.
Part A puts your database tools behind the Gateway. Part B moves the weather tool there too, as a different kind of target (a Lambda function), and shows how an agent finds the right tool among many without loading them all.
Platform
## What the platform provisions for you

terminal:
```bash
uv run bootcamp.py up 2
```

- An AgentCore Gateway (MCP) with inbound JWT auth and **semantic tool search** enabled
- An OAuth credential provider, so the Gateway can get its own token to call your MCP runtime
- A target named `DataStreamDatabase` pointing at your MCP runtime (an _MCP server_ target)
- A Lambda function `awsworkshop-<name>-weather` (Python 3.13, arm64) built from `phase2/app/weather_lambda/` and `shared/nws_weather.py`, and a second target named `Weather` in front of it (a _Lambda_ target; the Gateway's IAM role invokes it)
Adding this stage usually takes **~1 min**; the CLI prints progress (and full terraform output with `--verbose`).
From now on, every `deploy` that changes your MCP server also re-synchronises the Gateway's tool list (about 10-20 s), so new tools show up without any extra step. A changed Lambda or `tools.json` is re-applied by the same `deploy`.
**While you wait**
Read `phase2/app/weather_lambda/handler.py` and `tools.json` (the Lambda target), then open **AgentCore → Gateways** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/toolsAndGateways?region=us-east-1) in the console to see the targets appear, and **AWS Lambda → Functions** (https://us-east-1.console.aws.amazon.com/lambda/home?region=us-east-1#/functions) for your `awsworkshop-<name>-weather` function.
You
## What you do as a developer
### Find your tools through the Gateway
Through the Gateway every tool is named `<target>___<tool>` (target name, three underscores, tool name): `DataStreamDatabase___query_db` from your MCP runtime and `Weather___get_us_forecast` from the Lambda. If you added `list_tables` in Task 1 it appears as `DataStreamDatabase___list_tables`. The Gateway also lists one tool of its own, `x_amz_bedrock_agentcore_search` (more on that below).

terminal:
```bash
uv run bootcamp.py test --only 2
```

**See it in the console:** **AgentCore → Gateways** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/toolsAndGateways?region=us-east-1): your Gateway, its two targets (`DataStreamDatabase`, `Weather`) and their tools.
### Read the code: a guard that survives the rename
The agent's read-only guard (you deploy it in Task 4) must recognise the database tool whether it is called directly or through the Gateway:

phase2/app/agent/agent.py:
```python
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
```

**Question:** Why `endswith("query_db")` and not `== "query_db"`?
#### Answer
Behind the Gateway the tool is called `DataStreamDatabase___query_db`. An equality check would never match, and the guard would silently let every query through. A suffix check works in both places.
### Describe a table through the Gateway
Challenge
The Gateway is the single front door to your tools: add a tool on the MCP server and the agent discovers it through the Gateway without any agent change. In `phase2/app/mcp_server/mcp_server.py`, add `describe_table(table_name)`, which returns the columns (name, type) of one table and, for short text columns, their values (`projects.status` holds `'active'`, `'planning'`, `'completed'`: SQLite compares text case-sensitively, so a model that guesses `WHERE status = 'Active'` counts zero). Confirm the Gateway exposes it as `DataStreamDatabase___describe_table`.
**Where:** edit `phase2/app/mcp_server/mcp_server.py` in place, run `uv run bootcamp.py deploy` (~1.5 min), then check with `uv run bootcamp.py test --only 2` (the `[CHALLENGE]` line for `describe_table`) or `uv run bootcamp.py tools`.
Docs
- AgentCore Gateway: MCP server targets (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-target-MCPservers.html)
- AgentCore Gateway: how tools are named (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html)
#### Hint 1
SQLite's `pragma_table_info('<table>')` table-valued function returns one row per column (`name`, `type`, ...).
#### Hint 2
Never paste `table_name` into the SQL string. Pass it as a parameter: `execute("... (?)", (table_name,))`. Identifiers can't be parameters, so for the values query use only the table and column names `pragma_table_info` returned (an unknown table returns no columns), in double quotes. `deploy` refreshes the Gateway's tool list for you; the Gateway caches tools per target.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Part B: Gateway target types
A Gateway target is anything the Gateway can turn into MCP tools. Your agent never sees the difference: every target's tools arrive in the same `tools/list`, called the same way.
Target typeWrapsTool schema fromOutbound authHere
MCP server (AgentCore Runtime or any HTTPS MCP)An MCP server you runListed by the server; snapshot at create/syncOAuth2 (credential provider) or none`DataStreamDatabase` (Task 1 runtime)
LambdaA function you write; the event is the tool's argumentsInline JSON schema (or a file in S3)Gateway IAM role (`lambda:InvokeFunction`)`Weather` (this task)
OpenAPIAn existing REST API, one tool per operationOpenAPI 3 spec (inline or S3)API key or OAuth2 credential providerno: see “Why Lambda?”
SmithyAn AWS-style API described by a Smithy modelSmithy model (inline or S3)Gateway IAM role (SigV4)no
API Gateway REST APIA stage of an existing API Gateway APIFiltered/overridden operationsIAM, API key or noneno
Connectors and integrationsManaged tools (e.g. web search) and templates for SaaS APIsProvidedPer connectorno
The weather tool used to run inside the agent (`tools=[nws_weather.get_us_forecast]`). Now it is a Lambda target: the same `shared/nws_weather.py` code, but deployed once, governed by the Gateway (auth, Cedar policy in Task 7, traces) and reusable by any agent that can reach the Gateway.
#### Why Lambda and not an OpenAPI target for api.weather.gov?
An OpenAPI target would expose the raw NWS operations. A forecast takes _two_ calls (`/points/{lat},{lon}`, then the forecast URL it returns), the NWS requires an identifying `User-Agent`, and each raw GeoJSON answer costs the model 8K-75K input tokens. OpenAPI targets also authenticate outbound with an API-key or OAuth credential provider, and the NWS has neither. A small Lambda does both calls and returns about 100 tokens of text. Use OpenAPI targets for APIs whose operations already are the tools you want.
### Read the code: a Lambda target
The Gateway invokes the function with the tool's arguments as the event, and passes the tool it was called as in the Lambda context:

phase2/app/weather_lambda/handler.py:
```python
TOOL_NAME_KEY = "bedrockAgentCoreToolName"

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
```

The tool schemas the Gateway lists (and indexes for search) come from one file, which Terraform turns into the target's inline schema and, in Task 7, into the Cedar permit for these tools:

phase2/app/weather_lambda/tools.json:
```json
[
  {
    "name": "get_us_forecast",
    "description": "Get the National Weather Service forecast (next few periods: temperature, wind, conditions) for a location in the United States. US only.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "latitude": {
          "type": "number",
          "description": "Latitude of the US location in decimal degrees, e.g. 47.6062 for Seattle."
        },
        "longitude": {
          "type": "number",
          "description": "Longitude of the US location in decimal degrees, e.g. -122.3321 for Seattle."
        }
      },
      "required": ["latitude", "longitude"]
    }
  }
]
```

**Question:** Why does `handler` return `{"content": [...]}` instead of the forecast string?
#### Answer
The Gateway JSON-encodes whatever the function returns. A bare string reaches the model as `"NWS forecast for Seattle, WA:\nToday: ..."`, quoted and with every newline escaped. An MCP tool result (`content` with a text block) is passed through as is, so the model reads the same clean lines as in Phase 1.
### Semantic tool search: find, don't load
Every tool schema an agent is given is sent to the model on _every_ call. With two targets that's cheap; a Gateway in front of a company's APIs can hold hundreds of tools, and loading them all costs tokens on every turn and makes the model pick the wrong tool more often. With `search_type = "SEMANTIC"` the Gateway adds `x_amz_bedrock_agentcore_search`: give it a description of what you need and it returns the matching tools, best match first. Your specialists use it instead of `list_tools_sync()`:

phase2/app/agent/agent.py:
```python
SEARCH_TOOL = "x_amz_bedrock_agentcore_search"
"""The Gateway's built-in semantic tool search (`search_type = "SEMANTIC"`, terraform/participant/task2_gateway.tf)."""

DATA_TOOLS = ("Run read-only SQL on the DataStream company database: employees, departments, projects, tables", 3)

WEATHER_TOOLS = ("Weather forecast for a location in the United States", 1)
"""(what the specialist asks the Gateway's tool search for, how many of the best-ranked tools it keeps).

Search ranks every tool, best match first, and has no cut-off: the specialist decides how many it needs (query_db
plus the list_tables/describe_table challenge tools; one weather tool)."""

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
```

Measure it: `tools` lists your Gateway's tools per target, runs one search and sends the same question to your model three times (no tools, every tool, the search result), printing the prompt tokens LiteLLM billed for each.

terminal:
```bash
uv run bootcamp.py tools
uv run bootcamp.py tools --search "employee headcount by department"
```

example output:
```text
$ uv run bootcamp.py tools
Gateway tools (3, plus the built-in x_amz_bedrock_agentcore_search):
  DataStreamDatabase: query_db
  Weather: get_us_alerts, get_us_forecast
Semantic search "weather forecast for a US city" -> Weather___get_us_forecast
Prompt tokens for "What will the weather be like in Seattle tomorrow?" on gpt-6-luna:
  no tools               16
  every tool (3)        212  (+196, ~65 per tool)
  search, top 1         123  (+107)
At 200 tools, loading every tool would add ~13,067 tokens to every model call; with search the agent pays only for the few tools that match.

$ uv run bootcamp.py tools --search "employee headcount by department"
Semantic search "employee headcount by department" -> Weather___get_us_alerts
  ...
```

**Question:** Why does each specialist keep only the top few results?
#### Answer
Search ranks every tool and has no relevance cut-off, so “weather forecast” still returns `query_db`, just last. The specialist decides how many it needs: the data specialist keeps three (room for `list_tables` and `describe_table`), the weather specialist one.
### Add a Lambda tool: weather alerts
Challenge
Alice travels a lot: in `phase2/app/weather_lambda/handler.py` and `tools.json`, add a second tool to the `Weather` target, `get_us_alerts(area)`, that returns the active NWS alerts (warnings, watches, advisories) for a US state such as `CA`, and confirm the Gateway exposes `Weather___get_us_alerts`. No Terraform and no IAM change: the target, its schema and (in Task 7) its Cedar permit all follow `tools.json`.
**Where:** edit `phase2/app/weather_lambda/handler.py` and `phase2/app/weather_lambda/tools.json` in place, run `uv run bootcamp.py deploy` (~1.5 min), then check with `uv run bootcamp.py test --only 2` (the `[CHALLENGE]` line for `get_us_alerts`) or `uv run bootcamp.py tools`. Once your memory exists (Task 3), also raise the weather specialist's search results to two in `phase2/app/agent/agent.py` and try it with `invoke --local`.
Docs
- AgentCore Gateway: Lambda function targets (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-add-target-lambda.html)
- AgentCore Gateway: how tools are named (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/gateway-tool-naming.html)
#### Hint 1
Two files: a function in `TOOLS` in `phase2/app/weather_lambda/handler.py`, and its schema in `tools.json` (same `name`). The NWS endpoint is `/alerts/active?area=CA`; its `features[].properties.headline` is one line per alert.
#### Hint 2
Reuse `nws_weather.make_client()` (it sets the User-Agent the NWS requires) and `nws_weather.fetch_json`. Return a few short lines, not the GeoJSON: every character is model input. From Task 3 on, let the weather specialist keep two search results so it gets the new tool too, and ask a weather question with `invoke --local`.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Experiments
- Run `tools --search` with a few needs (“employee headcount by department”, “who works on which project?”, “is it going to rain in Denver?”). How often is the right tool first? Sharpen a vague docstring or `tools.json` description, deploy, and search again: descriptions are what search indexes.
- Multiply the per-tool cost `tools` printed by 200 tools and by the number of model calls in one `invoke` (Task 5 shows them). What does loading every tool cost per question?
- Inbound auth (agent to Gateway) and outbound auth (Gateway to target) are separate. Which outbound mode does each of your two targets use, and why is that split useful for third-party APIs?
#### What should I expect?
Search matches the need against each tool's _description_, not its data. `query_db`'s docstring says “SQL query on the DataStream Corp database” but never “employees” or “departments”, so in the dry run “employee headcount by department” ranked `Weather___get_us_alerts` first. Name the tables in the docstring, `deploy`, and it comes first. Vague needs (“help me”) rank by accident. The per-tool cost is roughly the length of its description and schema; at a few hundred tools that's tens of thousands of input tokens on every model call, before the question is even read. The database target authenticates with OAuth (a Cognito client-credentials token from the credential provider); the Lambda target with the Gateway's own IAM role. The agent only ever holds a token for the Gateway.
### Deploy and re-test

terminal:
```bash
uv run bootcamp.py deploy
uv run bootcamp.py test --only 2
```

expected [CHALLENGE] line:
```text
[CHALLENGE] SKIP stage 2 describe_table via the Gateway: no DataStreamDatabase___describe_table on your Gateway yet
# after your change:
[CHALLENGE] PASS stage 2 describe_table via the Gateway: DataStreamDatabase___describe_table(employees) -> 14 rows, updated_at column found=True
```

## Check your work

terminal:
```bash
uv run bootcamp.py test --only 2
```

Passes when the Gateway lists both targets' tools and a query through `DataStreamDatabase___query_db` works, `Weather___get_us_forecast` answers with an NWS forecast through the Lambda, and semantic search ranks the weather tool first for a weather need. Then the `[CHALLENGE]` lines for `describe_table` and `get_us_alerts`.
#### Under the hood
**AgentCore Gateway** is a managed MCP endpoint that aggregates targets (MCP servers, Lambda functions, OpenAPI or Smithy APIs, API Gateway stages, connectors) into one tool catalogue. It validates inbound JWTs, then authenticates each outbound call the way its target needs: an _OAuth2 credential provider_ from AgentCore Identity fetches a client-credentials token for your MCP runtime, and the Gateway's IAM role invokes your Lambda. Semantic search adds a built-in search tool backed by embeddings of the tool descriptions, which is another reason docstrings matter.
An MCP target _snapshots_ the server's tool list when it is created or synchronised. The platform re-synchronises it after every MCP redeploy (`python -m bootcamp_cli.agentcore sync-gateway`), which is why a new tool appears after `deploy`. A Lambda target has no server to ask: its tool list _is_ the inline schema (`tools.json`), updated by the same `deploy`.
