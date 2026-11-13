Task 1 · 8 tasks
# MCP server on AgentCore Runtime
Your Phase 1 MCP server goes to the cloud behind JWT auth, read-only. You own its tools.
20 minMedium
Alice’s ask
## The “Tool Server Deployment” challenge
Alice's agent will run in the cloud, so its database tools must too. Take the MCP server from Phase 1 and host it on **AgentCore Runtime**, reachable only with a valid token.
Platform
## What the platform provisions for you

terminal:
```bash
uv run bootcamp.py up 1
```

- Your MCP server code from `phase2/app/mcp_server/`, packaged and deployed to AgentCore Runtime
- Inbound JWT auth wired to your Cognito pool from Task 0
- Your personal copy of the DataStream SQLite database, seeded into your S3 code bucket (`DB_BUCKET` / `DB_KEY`)
Adding this stage usually takes **~1.5 min**; the CLI prints progress (and full terraform output with `--verbose`).
**While you wait**
Read the server this stage deploys, `phase2/app/mcp_server/mcp_server.py`: where is the read-only guarantee? In the console: **AgentCore → Agents** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/agents?region=us-east-1): your MCP server runtime appears there.
You
## What you do as a developer
### Read the deployed server

phase2/app/mcp_server/mcp_server.py:
```python
def ensure_local_db() -> Path:
    """The local database path, downloaded first when this microVM has no copy yet."""
    if not LOCAL_DB.exists():
        download_db()
    return LOCAL_DB

def connect_read_only(path: Path) -> sqlite3.Connection:
    """A connection that can never write: opened read-only and with `query_only` on (covers ATTACHed files too)."""
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn

def run_sql(path: Path, query: str, params: tuple = ()) -> dict:
    """Run one statement read-only and return its rows as {"data": [...]}."""
    with closing(connect_read_only(path)) as conn:
        return {"data": [dict(row) for row in conn.execute(query, params).fetchall()]}

def execute(query: str, params: tuple = ()) -> str:
    """Run `query` (with optional `?` parameters) against the local copy; returns the tool's text result."""
    try:
        return json.dumps(run_sql(ensure_local_db(), query, params), default=str)
    except sqlite3.Error as error:
        if "readonly" in str(error) or "query_only" in str(error):
            return READ_ONLY_MESSAGE
        return f"Error executing query: {error}"

@mcp.tool()
def query_db(query: str) -> str:
    """Execute a read-only SQL query (SQLite dialect) on the DataStream Corp database and return the rows as JSON."""
    with lock:
        return execute(query)

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, stateless_http=True)
```

Same tool as Phase 1, with three changes. Each microVM downloads your database from your bucket into `/tmp` once, on first use. **Every query runs on a read-only connection** (`mode=ro` plus `PRAGMA query_only`), so a write comes back as `Error: the database is read-only; this tool can only run queries that read data.` And the transport is stateless streamable HTTP on port 8000, which AgentCore Runtime expects for the MCP protocol.
#### Why read-only?
The assistant answers questions; it has no business changing company data, and the database is a copy anyway. Making the server itself read-only is the guarantee that holds no matter what: the agent's guard (Task 4) and the Gateway's Cedar policy (Task 7) are extra layers in front of it. That's _defense in depth_, and in Task 7 you'll see why the last layer matters.
### Give the model a schema tool
Challenge
Models write better SQL when they know the schema. In `phase2/app/mcp_server/mcp_server.py`, add a second tool, `list_tables`, that returns the table names as JSON (like `query_db`), and tell the model in its docstring to call it before writing SQL.
**Where:** edit `phase2/app/mcp_server/mcp_server.py` in place, run `uv run bootcamp.py deploy` (~1.5 min), then check with `uv run bootcamp.py test --only 1`: the `[CHALLENGE]` line for `list_tables` turns from SKIP to PASS.
Docs
- FastMCP: tools (https://gofastmcp.com/servers/tools)
- AgentCore Runtime: deploy MCP servers (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-mcp.html)
#### Hint 1
Every `@mcp.tool()` function becomes a separate tool, and its docstring is what the model reads. SQLite lists its tables in `sqlite_master`.
#### Hint 2
Don't call `query_db` from another tool (decorated tools aren't plain functions). Reuse `execute(query, params=())`, which returns the JSON text, and take `lock` like `query_db` does.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Deploy and re-test

terminal:
```bash
uv run bootcamp.py deploy
uv run bootcamp.py test --only 1
```

Stages 1 to 4 each print one extra `[CHALLENGE] PASS|SKIP|FAIL` line after the normal checks. **SKIP** means you haven't added the extension yet (it never fails the run), **PASS** means it works, and **FAIL** means it is there but broken (that counts toward the exit code).

expected [CHALLENGE] line:
```text
[CHALLENGE] SKIP stage 1 list_tables tool: no list_tables tool on your MCP server yet
# after your change:
[CHALLENGE] PASS stage 1 list_tables tool: list_tables returned ['audit_log', 'departments', 'employees', 'helpdesk_tickets', 'project_assignments', 'projects', 'sqlite_sequence', 'user_preferences']
```

The required _mcp runtime tools + query_ check also calls every extra tool that takes no arguments and expects JSON rows back; its detail ends with `extra tools OK (rows): {'list_tables': 8}`.
**See it in the console:** **AgentCore → Agents** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/agents?region=us-east-1): your MCP server runtime, its versions (one per `deploy` that changed the code) and its endpoint.
### Experiments
- AgentCore starts a **fresh microVM per MCP session**. What does that mean for the `/tmp` copy, and for latency? (You'll measure it in Task 5.)
- Why is `stateless_http=True` a good fit for a runtime that may scale to many instances?
- Sharpen the `query_db` docstring (SQLite dialect, table names), redeploy, and compare the SQL your agent writes in Task 4.
#### What should I expect?
Every new session pays a cold start (download the database, start Python) and gets its own private `/tmp` copy. That's fine for a read-only copy: nothing has to be written back or kept in sync. Stateless HTTP means any instance can answer any request, so the runtime can add or recycle microVMs freely.
## Check your work

terminal:
```bash
uv run bootcamp.py test --only 1
```

Passes when `tools/list` returns your tools and a `SELECT` succeeds with a bearer token, followed by the `[CHALLENGE]` line for `list_tables`.
#### Under the hood
**AgentCore Runtime** runs your code in isolated, serverless micro-VMs. The CLI builds a Linux/arm64 zip of the folder with its dependencies, uploads it to a code bucket, and the runtime rolls whenever the zip hash changes, so no Docker is needed. The runtime is created with the _MCP_ protocol and a custom JWT authorizer (Cognito discovery URL plus allowed client id), so AgentCore rejects unauthenticated calls before your code runs.
