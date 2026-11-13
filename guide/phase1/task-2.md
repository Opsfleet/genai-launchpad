Task 2 · 8 tasks
# Tools over MCP
Give the agent a key to the company database: a query_db tool served by an MCP server over stdio.
25 minMedium
Alice’s ask
## The “Hidden Vault” problem
Alice is impressed, but the real department data is locked in a SQLite database. Prompts can't keep up with 1,200 employees. The agent needs a tool, and you'll expose it the standard way: through the **Model Context Protocol**.
You
## Build it
### Expose the database as an MCP tool
Challenge
Finish the FastMCP server's one tool, `query_db(query: str) -> str`, so it runs SQL against `DB_PATH`, and write its description for the model: what it runs, what it returns, and the schema (tables, key columns, and the lowercase status values such as `'active'`).
Work in `phase1/starter/mcp_server.py`; the starter agent in the next step launches it. Reference: `phase1/mcp_server.py`.
Docs
- FastMCP: quickstart (https://gofastmcp.com/getting-started/quickstart)
- FastMCP: tools (https://gofastmcp.com/servers/tools)
- MCP specification: tools (https://modelcontextprotocol.io/specification/latest/server/tools)
#### Hint 1
FastMCP turns a typed, documented function into a tool with `@mcp.tool()`. The docstring becomes the description the model reads, so write it for the model: without the table and column names it has to guess them or spend calls looking them up. See FastMCP quickstart (https://gofastmcp.com/getting-started/quickstart).
#### Hint 2
Open the DB with `sqlite3.connect`, return `str(...fetchall())`, and return errors as text rather than raising, so the model can read and retry. Run it with `mcp.run(transport="stdio")`.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Connect the agent to it
Challenge
Start your server over stdio and give its tools to the agent.
Work in `phase1/starter/t2_mcp_tools.py` (look for `TODO`; an unfinished one prints `[starter] TODO …`) and run it with `uv run bootcamp.py phase1 t2 --starter`. The reference solution is `phase1/t2_mcp_tools.py`; `uv run bootcamp.py phase1 t2` runs it.
Docs
- Strands: connect your agent to MCP tools (https://strandsagents.com/docs/user-guide/sdk/tools/mcp-tools/)
#### Hint 1
Strands' `MCPClient` wraps an MCP transport. `make_mcp_client()` from `common.py` already builds one; in a `--starter` run it launches your server. See Strands: MCP tools (https://strandsagents.com/docs/user-guide/sdk/tools/mcp-tools/).
#### Hint 2
The client must be open while the agent runs: use it as a context manager and pass `mcp_client.list_tools_sync()` as `tools`.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Run it

terminal · your starter file:
```bash
uv run bootcamp.py phase1 t2 --starter "What tables are in the database?"
uv run bootcamp.py phase1 t2 --starter "Describe the employees table"
uv run bootcamp.py phase1 t2 --starter "How many employees are in Engineering?"
```

terminal · reference solution:
```bash
uv run bootcamp.py phase1 t2 "What tables are in the database?"
uv run bootcamp.py phase1 t2 "Describe the employees table"
uv run bootcamp.py phase1 t2 "How many employees are in Engineering?"
```

### Experiments
- Watch the tool calls. How many queries does the agent need for a count question? Does it look up the schema first?
- Remove the table list and the status line from your docstring and ask the Engineering question again. Does it need more calls? Does it still filter `status = 'active'`, or does it count the two terminated engineers (483)?
- This is _your_ copy of the DB, so try a write: “Add a department called Legal”. Nothing stops it. Task 5 fixes that.
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
“How many employees are in Engineering?” shows a `[tool] query_db: SELECT COUNT(*) ...` line whose SQL filters `status = 'active'`, and the answer is **481** (483 means it counted the terminated engineers: check the status line of your docstring). “What tables are in the database?” names departments, employees, projects, project_assignments, user_preferences and audit_log, either from a `sqlite_master` query or straight from the tool description (then without a `[tool]` line). “Describe the employees table” lists columns such as employee_id, first_name, last_name, job_title, department_id and status.
Failed? Run the same prompt on the reference (drop `--starter`). If the reference fails too, it's the model: rerun or try another `MODEL_ID` (`uv run bootcamp.py llm models`).
#### Under the hood
MCP separates _who has the tools_ from _who uses them_. Here the transport is stdio: `make_mcp_client()` spawns `mcp_server.py` (yours in a `--starter` run) with the same Python and talks JSON-RPC over its stdin/stdout. Strands converts each MCP tool schema into a tool spec the model can call. In Phase 2 the same server moves to AgentCore Runtime and the transport becomes streamable HTTP.
