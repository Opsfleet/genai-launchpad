# CLAUDE.md — DataStream Corp bootcamp (participant helper)

You are helping a **workshop participant** operate the DataStream Corp
bootcamp, debug their agent, and build features on it. Participants are
developers; the **platform (instructor) owns the infrastructure**.

## Ground rules

- Always run from the repository root (the folder with `bootcamp.py`) with `uv run` (`uv run bootcamp.py ...`,
  `uv run python ...`). Never bare `python`, `pip` or `terraform`.
- **Never edit `terraform/` or `bootcamp_cli/`.** Change
  behaviour only through `.env`, `phase1/` and `phase2/app/`. Avoid editing
  `shared/litellm_gateway.py`. If a fix needs infra, tell the participant to
  ask the instructor.
- The participant runs as role `bootcamp-participant-<name>` (tag-isolated):
  they can only touch `awsworkshop-<name>-*` resources. AccessDenied on
  someone else's resource, on IAM, or on direct Bedrock is by design.
- No direct Bedrock: every model call goes through the Opsfleet LiteLLM
  gateway, keyless, against a per-participant budget (default $5). Models:
  whatever the instructor enabled (real Bedrock names); `uv run bootcamp.py llm
  models` lists them with prices, the class default, suggestions and quirks.
  `MODEL_ID` in `.env` is optional (empty = class default). Never hardcode or request API keys. The gateway lets participants call only model routes
  (`/v1/chat/completions`, `/v1/models`, ...) and `/key/info`; anything else is a 403 by design. The gateway runs
  08:00-22:00 Israel time (Asia/Jerusalem); outside those hours every model call answers 503.
- Each participant has their own DB copy (Phase 1: `phase1/datastream_corp.db`;
  Phase 2: SQLite in their own S3 code bucket, which the MCP server copies to
  `/tmp` and queries **read-only**; writes return `Error: the database is read-only`).
- Optional agent capabilities (stage >= 4, set in `.env`, then `deploy`): `ENABLE_CODE_INTERPRETER`,
  `ENABLE_BROWSER`, `ENABLE_GUARDRAILS` (the participant's own Bedrock guardrail, passed per call through LiteLLM;
  `ToolOutputGuard` in `phase2/app/agent/guardrail.py` screens tool output, a database result row by row).
  Experiments, also `.env` + `deploy`: `GUARDRAIL_PROMPT_ATTACK_STRENGTH` (`NONE|LOW|MEDIUM|HIGH`, default `MEDIUM`)
  and `GUARDRAIL_PII_TYPES` (default `EMAIL,PHONE`; keep `EMAIL` for the stage-4 check), `MEMORY_EPISODIC=true`
  (adds an `Episodes` strategy, stage >= 3), `TRUST_ACTOR_HEADER=true` (deliberately insecure Task 4 demo; stage 4
  shows WARN; set it back to `false` and `deploy`).
- Phase 2 challenges (`[CHALLENGE] ... SKIP` lines) are for the participant to
  solve: give hints first, full solutions only when asked.
- Do not run `down` or other destructive commands without the participant's OK.
- Mind the budget: prefer `test --only N` over full `test`.
- **Evaluations bill the class AWS account.** AgentCore's built-in judges (`Builtin.*`, used by `eval` and by the
  stage-6 online evaluation, which scores 100% of live traffic) are billed per token to the workshop's AWS account,
  not the LiteLLM budget, and cannot be routed through LiteLLM. Must-follow:
  - Run evaluations **only** via `uv run bootcamp.py eval` (and the online evaluation the platform sets up). Never
    call AgentCore evaluation APIs directly (`StartBatchEvaluation`, `Evaluate`, `CreateOnlineEvaluationConfig`, ...
    via boto3, the AWS CLI or any SDK), and never write scripts or loops that do: that bypasses the run limits.
  - Keep golden datasets small (the provided ~11 items; at most 50 in the file) and runs small (default `--limit` 10,
    at most 25 answers per run, `--limit` x `--variants`); `eval` refuses anything bigger. Re-run only after a change
    worth measuring; never run `eval` in a loop; never load-test the deployed agent.
  - When iterating, prefer `--evaluators exact_numbers` (no model) or `rubric_judge` (on the LiteLLM budget).

## Core loop

```bash
uv run bootcamp.py doctor        # pre-flight: tools, .env, role, gateway, network (before day 1; creates nothing)
uv run bootcamp.py up N          # provision stages 0..N
uv run bootcamp.py deploy        # after editing phase2/app code (or MODEL_ID)
uv run bootcamp.py test --only N # verify one stage
uv run bootcamp.py invoke "..." --actor alice-chen   # signs in as that Cognito user; 20s-2m, up to ~5 min
uv run bootcamp.py invoke "..." --stream             # print the answer as it is generated (SSE), tool calls inline
uv run bootcamp.py invoke "..." --session last       # reuse the warm session (faster, keeps the conversation)
uv run bootcamp.py invoke "..." --json               # raw JSON reply (default: answer + one line per extra field)
uv run bootcamp.py invoke "..." --local              # agent.py on this machine against your real Memory/Gateway (stage 3+), no deploy; log: .build/local-agent/agent.log
uv run bootcamp.py traces [SESSION_ID]   # span tree of your latest invoke (stage 5+, 2-10 min lag)
uv run bootcamp.py traces --args         # plus tool inputs, e.g. the SQL actually sent to query_db
uv run bootcamp.py tools [--search Q]    # Gateway tools per target; prompt tokens: every tool vs semantic search
uv run bootcamp.py scores                # online-eval results, UTC + actor column (stage 6+, 15-30 min lag)
uv run bootcamp.py eval [--limit N]      # offline eval vs ground truth in phase2/evals/golden.yaml (11 items, default
                                         # --limit 10, max 25 answers/run; fails below --min-pass 0.8; --last reprints)
uv run bootcamp.py eval --evaluators all --variants A,B   # + custom evaluators; A/B of prompt_variants.py (stage 6+)
uv run bootcamp.py memory [--actor X]    # short-term sessions/events + long-term records per strategy namespace
uv run bootcamp.py status | llm | token [--actor X] | down   # add --verbose anywhere for full output
uv run bootcamp.py forget [--force]              # after an instructor `reset`: drop the stale local state
```

Latency: every new session cold-starts the agent's runtime microVM (and each Gateway tool call one for the MCP
server), so suggest `--session last` for follow-ups. Reliability: the gateway retries answer-less model replies and
falls back to the model's fallback, if `llm models` lists one; a specialist that still fails answers "The data specialist failed:
..." (never made-up numbers). When testing prompt changes, use a fresh `--actor`: long-term memory can hide a
regression. `eval` already uses a fresh actor and session per golden item, so run it after a prompt change worth measuring.
Custom evaluators (stage 6+), both code-based Lambdas: `exact_numbers` (`phase2/app/code_evaluator/handler.py`) and
`rubric_judge` (`phase2/app/rubric_judge/handler.py`: grades a rubric of `phase2/evals/evaluators.yaml` with a judge
model called through LiteLLM; each scored turn bills the participant's key; `TF_VAR_judge_rubric` / `TF_VAR_judge_model`).
Never suggest AgentCore's managed LLM-as-a-judge evaluators or direct Bedrock access: models only through LiteLLM.
Prompt variants for A/B: `phase2/app/agent/prompt_variants.py`.
Identity: the agent takes the actor only from the verified user token (Cognito `username` claim); never suggest
reading identity from a header or the payload (the `TRUST_ACTOR_HEADER` experiment shows why). `--actor
<any-new-name>` creates a test user in the pool; the pages use fresh ones (`trace-test`, `online-eval`, `mallory`).

## Skills (`.claude/skills/`)

| Skill | Use when |
|---|---|
| `bootcamp-operator` | How to run phases/stages/commands, read `status`, find logs, tear down |
| `bootcamp-debugger` | A `[FAIL]` line, HTTP 424, LiteLLM 401/429, AccessDenied, DNS, Cedar denials |
| `agent-feature-builder` | Add a Strands tool / specialist, change prompts, memory, switch models |
| `mcp-tool-author` | Add a tool to `phase2/app/mcp_server/mcp_server.py` or the Gateway's `Weather` Lambda target |
| `litellm-usage` | Call the gateway from scripts/notebooks, check budget, pick a model |
