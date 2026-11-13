Task 7 · 8 tasks
# Cedar policy on the Gateway
Enforce read-only queries at the Gateway, and find out why a string policy alone is not the guarantee.
25 minMedium
Alice’s ask
## The “Runaway Query” nightmare
“What if someone talks the agent into deleting every record?” Your guard hook helps, but it lives in code anyone can edit. Alice wants a rule enforced _outside_ the agent, at the Gateway.
Platform
## What the platform provisions for you

terminal:
```bash
uv run bootcamp.py up 7
```

- A Cedar policy engine attached to your Gateway
- A `safe_query_policy` that only permits read-looking SQL on `DataStreamDatabase___query_db`
- A `schema_tools` permit for `list_tables` / `describe_table`, if your MCP server defines them
Adding this stage usually takes **~4.5 min**; the CLI prints progress (and full terraform output with `--verbose`).
**While you wait**
Read the two Cedar policies in the first step below and guess which of the Experiments queries they deny. Most of the wait is the policy engine: watch it appear under **AgentCore → Policy** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/policy?region=us-east-1).
You
## What you do as a developer
### Read the policies

terraform/participant/safe_query_policy.cedar:
```cedar
permit(
  principal,
  action == AgentCore::Action::"${action}",
  resource == AgentCore::Gateway::"${gateway_arn}"
)
when {
  (
    context.input.query like "SELECT *" || context.input.query like "SELECT\n*" || context.input.query like "SELECT\t*" || context.input.query like "SELECT\r*" ||
    context.input.query like "select *" || context.input.query like "select\n*" || context.input.query like "select\t*" || context.input.query like "select\r*" ||
    context.input.query like "Select *" || context.input.query like "Select\n*" || context.input.query like "Select\t*" || context.input.query like "Select\r*" ||
    context.input.query like "WITH *" || context.input.query like "WITH\n*" || context.input.query like "WITH\t*" || context.input.query like "WITH\r*" ||
    context.input.query like "with *" || context.input.query like "with\n*" || context.input.query like "with\t*" || context.input.query like "with\r*" ||
    context.input.query like "With *" || context.input.query like "With\n*" || context.input.query like "With\t*" || context.input.query like "With\r*" ||
    context.input.query like "EXPLAIN *" || context.input.query like "EXPLAIN\n*" || context.input.query like "EXPLAIN\t*" || context.input.query like "EXPLAIN\r*" ||
    context.input.query like "explain *" || context.input.query like "explain\n*" || context.input.query like "explain\t*" || context.input.query like "explain\r*" ||
    context.input.query like "Explain *" || context.input.query like "Explain\n*" || context.input.query like "Explain\t*" || context.input.query like "Explain\r*" ||
    ((context.input.query like "PRAGMA table_info(*" || context.input.query like "pragma table_info(*" || context.input.query like "Pragma table_info(*") &&
     !(context.input.query like "*=*" || context.input.query like "*;*"))
  ) &&
  !(context.input.query like "*--*" || context.input.query like "*/\**") &&
  !(context.input.query like "*INSERT *" || context.input.query like "*INSERT\t*" || context.input.query like "*INSERT\n*" || context.input.query like "*INSERT\r*") &&
  !(context.input.query like "*insert *" || context.input.query like "*insert\t*" || context.input.query like "*insert\n*" || context.input.query like "*insert\r*") &&
  !(context.input.query like "*Insert *" || context.input.query like "*Insert\t*" || context.input.query like "*Insert\n*" || context.input.query like "*Insert\r*") &&
  !(context.input.query like "*UPDATE *" || context.input.query like "*UPDATE\t*" || context.input.query like "*UPDATE\n*" || context.input.query like "*UPDATE\r*") &&
  !(context.input.query like "*update *" || context.input.query like "*update\t*" || context.input.query like "*update\n*" || context.input.query like "*update\r*") &&
  !(context.input.query like "*Update *" || context.input.query like "*Update\t*" || context.input.query like "*Update\n*" || context.input.query like "*Update\r*") &&
  !(context.input.query like "*DELETE *" || context.input.query like "*DELETE\t*" || context.input.query like "*DELETE\n*" || context.input.query like "*DELETE\r*") &&
  !(context.input.query like "*delete *" || context.input.query like "*delete\t*" || context.input.query like "*delete\n*" || context.input.query like "*delete\r*") &&
  !(context.input.query like "*Delete *" || context.input.query like "*Delete\t*" || context.input.query like "*Delete\n*" || context.input.query like "*Delete\r*") &&
  !(context.input.query like "*REPLACE *" || context.input.query like "*REPLACE\t*" || context.input.query like "*REPLACE\n*" || context.input.query like "*REPLACE\r*") &&
  !(context.input.query like "*replace *" || context.input.query like "*replace\t*" || context.input.query like "*replace\n*" || context.input.query like "*replace\r*") &&
  !(context.input.query like "*Replace *" || context.input.query like "*Replace\t*" || context.input.query like "*Replace\n*" || context.input.query like "*Replace\r*") &&
  !(context.input.query like "*DROP *" || context.input.query like "*DROP\t*" || context.input.query like "*DROP\n*" || context.input.query like "*DROP\r*") &&
  !(context.input.query like "*drop *" || context.input.query like "*drop\t*" || context.input.query like "*drop\n*" || context.input.query like "*drop\r*") &&
  !(context.input.query like "*Drop *" || context.input.query like "*Drop\t*" || context.input.query like "*Drop\n*" || context.input.query like "*Drop\r*")
};
```

Cedar is default-deny: anything not explicitly permitted is refused. This permit lets `query_db` through only when the query starts with `SELECT`, `WITH` or `EXPLAIN` (UPPER, lower or Title case) followed by a space, newline, tab or carriage return, or is `PRAGMA table_info(...)` with no `=` or `;` (so `PRAGMA writable_schema=...` and every other pragma stay denied); contains no SQL comment (`--` or `/*`); and has none of `INSERT UPDATE DELETE REPLACE DROP` (in those three casings) followed by a space, tab, newline or carriage return. The platform fills in `${action}` and `${gateway_arn}`.
**What string patterns cannot do**
Cedar's `like` can neither lower-case text nor parse SQL, so some harmless reads stay denied: mixed case (`sElEcT 1`), a query with leading whitespace, a column such as `last_update` followed by a space (it matches `update `), or `LIKE '%delete %'`. Rewrite such a query (normal casing, other column alias, no keyword in the literal). The read-only database is what really stops writes.

terraform/participant/schema_tools_policy.cedar:
```cedar
permit(
  principal,
  action in [${actions}],
  resource == AgentCore::Gateway::"${gateway_arn}"
);
```

The second permit covers `DataStreamDatabase___list_tables` and `DataStreamDatabase___describe_table`, but only the ones your `mcp_server.py` defines (Cedar rejects permits for tools the Gateway doesn't have). **At stage 7 any other tool without a permit disappears from `tools/list`**: default deny hides it from the agent entirely. The weather tools get a third permit from the same template, one action per tool in `phase2/app/weather_lambda/tools.json`, so a tool you add there (Task 2 Part B) stays visible. The Gateway's own `x_amz_bedrock_agentcore_search` drops out of `tools/list` at stage 7 but still answers, which is all your specialists need.
**See it in the console:** **AgentCore → Policy** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/policy?region=us-east-1): your policy engine, the policies in it as the platform rendered them, and the Gateway it is attached to.
### Prove defense in depth
Challenge
Show that the Gateway blocks a delete even when your own code doesn't. Disable the agent-side guard in `phase2/app/agent/agent.py`, redeploy, and send a delete to the Gateway exactly as an unguarded agent would.
**Where:** edit `phase2/app/agent/agent.py` in place, run `uv run bootcamp.py deploy` (~1.5 min), then check with `uv run bootcamp.py tools --sql "DELETE FROM employees WHERE 1 = 0"` (expect `Tool Execution Denied`) and `uv run bootcamp.py test --only 7`.
Docs
- Policy in AgentCore: authorization flow (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-authorization-flow.html)
- Policy in AgentCore: core concepts (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-core-concepts.html)
- Strands: hooks (https://strandsagents.com/docs/user-guide/sdk/agents/hooks/)
#### Hint 1
The guard is a hook attached to the data specialist in `build_specialists`.
#### Hint 2
Remove it from the specialist's `hooks` list (don't delete the class) and `deploy`. The model may still refuse a delete on its own (`query_db` says it is read-only), so the Gateway never sees it: send the SQL with `tools --sql`, which calls `query_db` through the Gateway with no model in between.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Find a write that Cedar lets through
Challenge
Cedar's `like` is string pattern matching, not a SQL parser. With the guard still disabled, find a write that the policy permits, then watch the database refuse it anyway.
**Where:** a terminal exercise, no file edits and no deploy. Send your SQL with `uv run bootcamp.py tools --sql "..."`, then run `uv run bootcamp.py test --only 7`.
Docs
- Cedar: the like operator (https://docs.cedarpolicy.com/policies/syntax-operators.html#operators-string-like)
- Policy in AgentCore: policy conditions (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/policy-conditions.html)
#### Hint 1
Look at which casings of each keyword the policy lists. SQL keywords are case-insensitive; `like` is not.
#### Hint 2
A statement may start with `WITH`. Send your exact SQL with `tools --sql`: through the agent, models like to “fix” odd casing or refuse.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Experiments: test some hypotheses
String patterns cut both ways. Treat these as hypotheses, not facts, and test each one with `tools --sql` or `invoke` (your database is a read-only copy, so it's safe):
- A harmless SELECT that mentions a write keyword (“How many audit_log entries mention a delete?”) might be denied.
- A query that starts with a space, or separates `SELECT` from the rest with a tab, might be refused even though it only reads.
- A column called `updated_at` might trip the `UPDATE` pattern. And `last_update`?

terminal:
```bash
uv run bootcamp.py tools --sql "WITH t AS (SELECT 1) SELECT * FROM t"
uv run bootcamp.py tools --sql "SELECT updated_at FROM employees LIMIT 1"
uv run bootcamp.py tools --sql "PRAGMA table_info(projects)"
uv run bootcamp.py invoke "How many audit_log entries mention a delete?" --actor alice-chen
uv run bootcamp.py test --only 7
```

Where should the real guarantee live: the policy, the tool (a read-only connection), or both?
### Deploy and re-test
Put `ReadOnlyGuardHook()` back into `hooks`, then:

terminal:
```bash
uv run bootcamp.py deploy
uv run bootcamp.py test --only 7
```

**Lesson learned**
Every layer has a gap: the agent guard lives in editable code, and the Cedar policy matches strings, so an odd casing slips past it. The layer that cannot be talked around is the one closest to the data: a read-only connection. Denials come back as MCP protocol errors (“Tool Execution Denied”), not as a tool result, so your agent should handle tool errors gracefully. Cedar policy names are unique per account, which is why the platform prefixes yours with your participant id.
## Check your work

terminal:
```bash
uv run bootcamp.py test --only 7
```

Passes when SELECTs through the Gateway are allowed (including one on `updated_at`), a DELETE is denied, and disguised writes are blocked (by Cedar or by the read-only database), and `Weather___get_us_forecast` still answers (its permit comes from `tools.json`).
#### Under the hood
**AgentCore Policy** evaluates Cedar policies on every Gateway tool call. The principal is the caller, the action is the tool (`Target___tool`), the resource is the Gateway, and `context.input` holds the tool arguments, so policies can reason about the SQL text itself. Policies are validated against the Gateway's tool schemas when created. Enforcement happens before the request ever reaches your MCP runtime, and `tools/list` only shows tools the caller is permitted to call.
