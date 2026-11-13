Phase 2 · Ship to AgentCore
# Ship the agent
You build the agent. The platform handles the cloud. Each stage is one command. `up N` provisions everything up to task N; a lower N switches later tasks off again. Your work is the app: agent code, prompts, tools, memory use, config and tests.
0 of 8 tasks complete
**How Phase 2 works**
- `uv run bootcamp.py up N` deploys a working reference for each stage; read its code on the task page.
- The hands-on part is the **challenges**: edit the real files under `phase2/` in place (no starter copies; `git diff` shows your changes, `git checkout -- <file>` resets one).
- Ship with `uv run bootcamp.py deploy`, then check with `test --only N` (its `[CHALLENGE]` lines), `invoke` or `traces`. Each challenge says which file, and which check.
- Then the **Experiments** on each page and the optional add-ons. Experiments that change infrastructure are `.env` switches (`MODEL_ID`, `MEMORY_EPISODIC`, `ENABLE_GUARDRAILS`, ...) followed by `deploy`.
## Your toolbox

the whole Phase 2 toolbox:
```bash
uv run bootcamp.py deploy               # ship your edited agent / MCP code
uv run bootcamp.py status               # ids: POOL_ID, GATEWAY_ID, MEMORY_ID, ...
uv run bootcamp.py test --only 4        # check one stage (or: test 4 for 0..4)
uv run bootcamp.py invoke "Hi" --actor alice-chen   # usually 10-40 s
uv run bootcamp.py invoke "And?" --session last     # reuse the warm session (--json: raw reply)
uv run bootcamp.py invoke "Hi" --stream # print the answer as it is generated
uv run bootcamp.py tools --search "weather"         # Gateway tools; semantic search, stage 2+
uv run bootcamp.py memory --actor alice-chen        # short- and long-term memory, stage 3+
uv run bootcamp.py traces [SESSION_ID]  # span tree of your latest invoke (--args: tool inputs), stage 5+
uv run bootcamp.py scores               # online-evaluation results (UTC, actor), stage 6+
uv run bootcamp.py eval                 # offline: golden questions with ground truth (--last: saved run)
uv run bootcamp.py token                # bearer token for manual calls (--actor: a user's)
uv run bootcamp.py llm                  # gateway URL, models, budget spent / max
uv run bootcamp.py down                 # remove your whole stack (~10.5 min)
```

Every command runs from your clone, `datastream-bootcamp/`. `test N` checks stages 0 to N; `test --only N` just one. Add `--verbose` anywhere on the command line (or `BOOTCAMP_VERBOSE=1` in `.env`) for the full terraform output and debug logs. A new `invoke` session cold-starts your agent's microVM (and each Gateway tool call another one for the MCP server); `--session last` skips that and keeps the conversation.
**Budget**
With `gpt-6-luna` or `claude-haiku-5-5`, Phase 1 about $0.04-0.25 and Phase 2 with the optional pages about $0.05-0.30; `claude-sonnet-5-5` costs about 20 times more. All well within the $5 default; on `nova-2-lite` Task 4 is about $0.04 and one 10-item `eval` about $0.04 for its rubric judge (`uv run bootcamp.py llm models` shows prices). AgentCore's built-in evaluators bill the class AWS account, not your LiteLLM budget. Check your spend with `uv run bootcamp.py llm budget`.
## Stages at a glance
StageThe platform provisions`up` timeCheckWhat passing proves
0Cognito: M2M client, user client and the story users~6 min`test --only 0`M2M token is issued; alice-chen and jordan-lee sign in; keyless LiteLLM identity works; direct Bedrock is denied
1MCP server on AgentCore Runtime, JWT inbound~1.5 min`test --only 1`tools/list, a SELECT and any extra no-argument tool work
2AgentCore Gateway: MCP target, weather Lambda target, OAuth provider, semantic search~1 min`test --only 2`Gateway lists both targets' tools; a query and the weather tool work; search ranks the weather tool first
3AgentCore Memory: facts, preferences, summaries~11 min`test --only 3`Memory is ACTIVE with three strategies
4Agent runtime (user-token JWT authorizer, streaming) wired to Gateway, Memory, LiteLLM~5.5 min`test --only 4`Agent answers; the actor comes only from the verified token; recall across sessions, no cross-user leak
5Observability (traces in CloudWatch)~0.5 min`test --only 5`Spans arrive (can take ~10 min)
6Online evaluations and the `exact_numbers` and `rubric_judge` code evaluators (offline: `eval` adds your golden dataset and batch evaluations)~1 min`test --only 6`Online config and custom evaluators are ACTIVE; the rubric judge scores a sample turn through LiteLLM
7Cedar policy on the Gateway~4.5 min`test --only 7`SELECTs allowed, DELETE denied, disguised writes blocked; the weather tool is still permitted
**Fell behind?**
Run `uv run bootcamp.py up N` to land at the start of task N+1 with everything before it in place.
## Tasks
0
### Identity with Cognito
Two kinds of identity: a machine-to-machine token for your services, and signed-in users for people.
The “Enterprise Readiness” challenge
15 minEasy1
### MCP server on AgentCore Runtime
Your Phase 1 MCP server goes to the cloud behind JWT auth, read-only. You own its tools.
The “Tool Server Deployment” challenge
20 minMedium2
### AgentCore Gateway
One governed front door for every tool: two target types, and semantic search to find the right tool.
The “Tool Discovery” challenge
35 minMedium3
### AgentCore Memory
Long-term, per-user memory that learns facts across sessions and keeps users apart.
The “Remember Me, Not Jordan” crisis
15 minEasy4
### Your agent on AgentCore Runtime
Deploy the Phase 1 orchestrator, wired to Gateway, Memory and LiteLLM. This is where you code.
The “Agent Deployment and Tool Access” challenge
35 minAdvanced5
### Observability
See every model call, tool call and millisecond your agent spends, without adding code.
The “Black Box” panic
20 minEasy6
### Online and offline evaluations
Score live traffic with LLM-as-a-judge, regression-test every change against ground truth, then add your own evaluator and A/B two prompts.
The “Quality Crisis” panic
35 minMedium7
### Cedar policy on the Gateway
Enforce read-only queries at the Gateway, and find out why a string policy alone is not the guarantee.
The “Runaway Query” nightmare
25 minMedium
## Optional add-ons
For fast finishers: switch on an AgentCore built-in tool with one `.env` flag and teach your agent to use it.
0 of 3 optional add-ons complete
+
### Optional: Code Interpreter
Give the agent a sandboxed Python environment so it computes answers instead of guessing at arithmetic.
The “Numbers, Not Prose” request
25 minAdvanced+
### Optional: Browser
Let the agent read public web pages through a managed, sandboxed headless browser.
The “What Are Competitors Doing?” request
25 minAdvanced+
### Optional: Guardrails and prompt injection
Make the agent leak employee emails with a prompt injection, typed or hidden in a helpdesk ticket, then stop it with a Bedrock Guardrail, tool-output screening and a hardened prompt, and mask personal data in answers.
The “Who Wrote That Ticket?” incident
35 minAdvanced
## Finish
Done for the day? Tear your stack down (about 10.5 minutes) and confirm nothing is left.
+
### Clean up
Remove everything you provisioned, and confirm nothing is left running on your name.
The “Leave No Trace” finish
10 minEasy
