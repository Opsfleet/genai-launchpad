×
Opsfleet Agent Bootcamp · DataStream Corp
# Prototype to production.
You build the agent. The platform handles the cloud. Two phases, sixteen tasks, one executive assistant for CEO Alice Chen, from a local script to a governed, observable service on Amazon Bedrock AgentCore.
Start with setupSee the architecture
Phase 1 · local
## Build the agent
A Strands agent on your laptop: prompts, MCP tools, sessions, conversation windows, hooks, structured output and multi-agent routing.
9 tasks · about 3 hoursPhase 2 · AgentCore
## Ship it
One command per stage provisions identity, runtimes, Gateway, Memory, observability, evaluations and policy. You focus on the code that runs on them.
8 tasks + optional pages · about 3.5 hours
The story
## DataStream Corp needs an assistant, fast
DataStream Corp has 1,200+ employees, six departments and a CEO, **Alice Chen**, who is tired of waiting for reports. Every task starts with one of her problems: an agent that forgets her name, one that nearly deletes the database, one nobody can see inside. You solve each with one concept.
You're the developer, not the DevOps team. Infrastructure arrives with one command; your time goes into prompts, tools, memory, guardrails and testing.
## How it fits together
Phase 1 runs on your laptop. Phase 2 moves the same agent into your own AgentCore stack. Every model call, in both phases, goes through the Opsfleet LiteLLM gateway.
Solid arrows are requests, dashed arrows lead to optional tools, dotted arrows are telemetry. On a phone, scroll the diagram sideways.
## Quick start
Run these one line at a time. The full walkthrough, including Windows commands, is on Before you start.

terminal · macOS / Linux:
```bash
git clone https://github.com/Opsfleet/genai-launchpad.git datastream-bootcamp
cd datastream-bootcamp
aws configure --profile bootcamp
uv sync
cp .env.example .env
uv run bootcamp.py doctor
uv run bootcamp.py llm
uv run bootcamp.py phase1 t0
```

`aws configure` asks for the access key you create in the console after signing in with your invitation email. Before `doctor`, set `PARTICIPANT` in `.env` (`AWS_PROFILE=bootcamp` is already set). Before you start walks through each step, Windows included, and the browser workspace option.
Go to the setup task
### Your own data
Phase 1 uses a local SQLite file; in Phase 2 your MCP server reads its own copy from your S3 bucket, read-only. Nobody else touches your data.
### Your own budget
Keyless: the gateway knows you by your IAM role and bills your personal budget, $10 by default. No API key is ever handed out. It runs 08:00-22:00 Israel time (Asia/Jerusalem) every day. `uv run bootcamp.py llm models` lists your models with prices; switch with `MODEL_ID` when you need more reasoning.
### Your own stack
Everything you create is named `awsworkshop-<name>-*`, tagged `Participant=<name>` and isolated by IAM. `uv run bootcamp.py down` removes it all.
Partnerships
## Built with AWS
Opsfleet is an AWS Partner, recognised at the Premier Tier for services and with the AI Services Competency. This bootcamp runs end to end on AWS: Amazon Bedrock models behind the Opsfleet LiteLLM gateway, and Amazon Bedrock AgentCore for runtime, gateway, memory, identity, observability, evaluations and policy.
### AWS Premier Tier Services Partner
Opsfleet's partner tier in the AWS Partner Network.
### AWS AI Services Competency
Opsfleet holds the AWS AI Services Competency.
