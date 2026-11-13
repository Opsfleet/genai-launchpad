Task 5 · 8 tasks
# Observability
See every model call, tool call and millisecond your agent spends, without adding code.
20 minEasy
Alice’s ask
## The “Black Box” panic
“This agent serves 1,200 people and I have no idea what happens inside it!” Before something breaks, Alice wants traces: which tools ran, how long each step took, where tokens went.
Platform
## What the platform provisions for you

terminal:
```bash
uv run bootcamp.py up 5
```

- Nothing new to create: tracing has been on since Task 4 (the agent runs under `opentelemetry-instrument`) and its log group already exists
- Stage 5 switches on the check that your spans arrive in Transaction Search
Adding this stage usually takes **~0.5 min**; the CLI prints progress (and full terraform output with `--verbose`).
Transaction Search is an account-wide switch; your instructor turned it on once for everyone.
**While you wait**
Read the “Look at a trace” step and open **AgentCore → Observability** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/observability?region=us-east-1).
You
## What you do as a developer
### Generate some traffic

terminal:
```bash
uv run bootcamp.py invoke "Which department has the most employees?" --actor trace-test
uv run bootcamp.py invoke "Headcount in Sales and the weather in Chicago?" --actor trace-test
```

Why a fresh `--actor trace-test`? `alice-chen`'s long-term memory already holds what she asked in earlier tasks. Asked as Alice, the agent could answer the headcount from memory with no `query_db` call, and there would be no Gateway span to time in the challenge below. Any name works: the CLI creates it as a test user in your pool.
**While you wait**
Spans arrive 2-10 minutes after an invoke. Read “Under the hood” at the end of this page, or open **AgentCore → Observability** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/observability?region=us-east-1) and watch your agent's sessions appear.
### Look at a trace
Two ways, same data. From the terminal (by default your latest `invoke` on this machine, or pass the session id `invoke` printed):

terminal:
```bash
uv run bootcamp.py traces
uv run bootcamp.py traces SESSION_ID
uv run bootcamp.py traces --args   # also each tool call's input, e.g. the SQL sent to query_db
```

It prints a span tree with durations and token counts. `--args` adds each tool call's input, read from your runtime's log group (it lags a few minutes too).
**See it in the console:** **AgentCore → Observability** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/observability?region=us-east-1): pick your agent, then a session and its trace: the same spans as a timeline, with the model and tool calls side by side.
### Find where the time goes
Challenge
For the second question, find the slowest span and decide what dominates latency: model calls, the Gateway tool calls (database and weather Lambda), or the weather API behind the Lambda.
**Where:** a terminal exercise, no file edits and no deploy. Read the span tree with `uv run bootcamp.py traces` (or the trace in **AgentCore → Observability** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/observability?region=us-east-1)).
Docs
- AgentCore Observability: view traces and metrics (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-view.html)
- AgentCore Observability: concepts (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-telemetry.html)
- Strands: traces (https://strandsagents.com/docs/user-guide/sdk/observability-evaluation/traces/)
#### Hint 1
Expand the `data_agent` and `weather_agent` tool spans: each contains the specialist's own model calls. Compare those with the Gateway `query_db` spans inside.
#### Hint 2
Look at the duration of each individual Gateway tool call. Is it what you'd expect for a SQLite query on a small file? Think back to the Task 1 experiment about microVMs.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Experiments
Switch `MODEL_ID` in `.env`, `deploy`, send the same prompts and compare latency and token counts in the traces.
#### What should I expect?
A larger model (for example a Claude Sonnet) tends to route with fewer, better tool calls but each call is slower and pricier; a small model is faster per call but may need extra round-trips. Fewer tool calls also means fewer cold starts. Measure, don't guess.
**Lesson learned**
Per-session isolation has a price. Because every MCP session gets a fresh microVM, a tool call that does milliseconds of work costs seconds of cold start. Traces make that visible, and the levers are architectural: fewer tool calls per answer (a `describe_table` up front instead of trial and error), reusing an MCP session where the client allows it, or moving hot, cheap tools closer to the agent.
## Check your work

terminal:
```bash
uv run bootcamp.py test --only 5
```

Spans can take about 10 minutes to appear. A `WARN` here just means “not yet”; re-run later.
#### Under the hood
AgentCore Runtime ships the AWS Distro for OpenTelemetry. Strands emits OpenTelemetry spans for agent cycles, model calls and tool calls, and the runtime exports them to X-Ray. With **Transaction Search** enabled, spans land in the account-wide `aws/spans` log group, where the GenAI Observability dashboards, `bootcamp.py traces` and the evaluations in Task 6 read them. Spans carry metadata (names, timings, token counts), not your prompts or answers. Application logs go to `/aws/bedrock-agentcore/runtimes/<runtime-id>-DEFAULT`; your role can only read your own `awsworkshop_<you>_*` log groups, so another participant's logs return `AccessDenied` by design.
