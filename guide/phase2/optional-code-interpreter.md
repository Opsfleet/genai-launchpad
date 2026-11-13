Optional add-on
# Optional: Code Interpreter
Give the agent a sandboxed Python environment so it computes answers instead of guessing at arithmetic.
25 minAdvanced
Alice’s ask
## The “Numbers, Not Prose” request
Alice wants more than counts: “What's the average and median team size per department?” SQL gets the rows; models are unreliable at arithmetic. AgentCore **Code Interpreter** runs model-written Python in an isolated sandbox, so the agent can compute without touching your runtime.
Platform
## What the platform provisions for you

.env:
```bash
ENABLE_CODE_INTERPRETER=true
```

terminal:
```bash
uv run bootcamp.py deploy
```

- Session permissions for your agent role on the AWS-managed `aws.codeinterpreter.v1`
- The `run_python` tool, handed to your orchestrator automatically
Flags default to `false` and need stage 4 or higher. `uv run bootcamp.py status` shows `CODE_INTERPRETER_ENABLED` and `BROWSER_ENABLED`.
You
## What you do as a developer
### Read the tool

phase2/app/agent/sandbox_tools.py:
```python
@tool
def run_python(code: str) -> str:
    """Execute Python code in a secure AgentCore Code Interpreter sandbox and return its output.

    Use it for calculations, statistics and data transformations. print() every value you need to see.

    Args:
        code: Python source code to run.
    """
    with code_session(REGION, identifier=CODE_INTERPRETER_ID) as client:
        return stream_text(client.execute_code(code))[:OUTPUT_LIMIT]
```

One call, one fresh sandbox session: `code_session` from `bedrock_agentcore.tools` starts it and stops it when the block exits.

terminal:
```bash
uv run bootcamp.py invoke "Use the code interpreter to compute the mean and median of 3, 5, 10 and 22." --actor alice-chen
```

### Add a data-analysis specialist
Challenge
The orchestrator can call `run_python`, but it has no data. In `phase2/app/agent/agent.py`, add an `analysis_agent` specialist that fetches rows through the Gateway and then computes with `run_python`, and register it with the orchestrator.
**Where:** edit `phase2/app/agent/agent.py` in place, run `uv run bootcamp.py deploy` (~1.5 min), then check with `uv run bootcamp.py invoke "What is the average and median team size per department?" --actor alice-chen --stream`: the tool line shows `[calling analysis_agent]`.
Docs
- AgentCore Code Interpreter (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html)
- AgentCore Code Interpreter with Strands (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-using-strands.html)
- Strands: agents as tools (https://strandsagents.com/docs/user-guide/sdk/multi-agent/agents-as-tools/)
#### Hint 1
It's the agents-as-tools pattern again. Look at `data_agent` in `build_specialists`: a `@tool` that builds an `Agent`. AgentCore Code Interpreter docs (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-interpreter-tool.html).
#### Hint 2
Import `run_python` from `sandbox_tools` and give the specialist `tools=[*search_tools(gateway, DATA_TOOLS), run_python]`. Tell it: query first, then compute, print every result, report numbers rather than code. Return it from `build_specialists`.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Deploy and ask for analysis

terminal:
```bash
uv run bootcamp.py deploy
uv run bootcamp.py invoke "What is the average and median team size per department?" --actor alice-chen
```

### Experiments
- Look at the trace (`uv run bootcamp.py traces`): how many `run_python` calls did one question take, and how long did each sandbox session last?
- Each call gets a fresh session. What does that mean for code that builds on a previous call's variables?
- What could go wrong if model-written code ran inside your runtime instead?
**See it in the console:** **AgentCore → Observability** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/observability?region=us-east-1): the trace of that question, with each `run_python` span and its duration.
## Check your work
With the flag on, `test --only 4` adds a _code interpreter tool_ check. It sends exactly this prompt:

terminal · the check's prompt, to try by hand:
```bash
uv run bootcamp.py invoke 'DataStream analytics needs an exact checksum for the quarterly report: use the run_python tool to run `print(sum(range(12345)) % 65521)` and reply with the checksum it prints.' --actor alice-chen
```

It passes when the answer contains **57938** (thousands separators such as `57,938` are fine): a number the model can't produce reliably without running the code.

terminal:
```bash
uv run bootcamp.py test --only 4
```

expected output (abridged):
```text
[PASS] stage 4 ...
[PASS] stage 4 code interpreter tool: The script prints 57938.
```

The check asks as a fresh actor in a fresh session and retries once on an empty answer. The prompt is framed as DataStream work so a Task 4 “decline off-topic requests” prompt keeps it; if your prompt still refuses it, loosen the scope rule.
This check depends on the model's wording, which varies from run to run. If it fails, rerun it once; check with `uv run bootcamp.py traces --args` which tool ran (the trace, not the wording, says whether the agent did the work); if the shipped agent does the same (`git stash`, `deploy`, rerun, `git stash pop`, `deploy`), it's the model, not your change.
#### Under the hood
Both tools use the AWS-managed built-ins `aws.codeinterpreter.v1` and `aws.browser.v1`. Every call starts a fresh, isolated sandbox session and stops it afterwards, so nothing leaks between participants or requests. When a flag is on, your agent role gets only the session permissions it needs, in the inline policy `awsworkshop-<you>-sandbox-tools`; the platform sets `CODE_INTERPRETER_ENABLED` / `BROWSER_ENABLED` on the runtime, and `optional_tools()` plus `prompt_hints()` hand the tools to the orchestrator with a one-line usage hint each.

phase2/app/agent/sandbox_tools.py:
```python
def optional_tools() -> list:
    """The sandbox tools this runtime is configured for (empty when both capabilities are off)."""
    tools = []
    if capability_enabled("CODE_INTERPRETER_ENABLED"):
        tools.append(run_python)
    if capability_enabled("BROWSER_ENABLED"):
        tools.append(browse_web)
    return tools
```
