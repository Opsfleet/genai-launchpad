Optional add-on
# Optional: Browser
Let the agent read public web pages through a managed, sandboxed headless browser.
25 minAdvanced
Alice’s ask
## The “What Are Competitors Doing?” request
Before a board meeting Alice asks: “What does this vendor say on their product page?” The database can't answer that. AgentCore **Browser** gives the agent a managed headless Chromium in the cloud, isolated from your runtime.
Platform
## What the platform provisions for you

.env:
```bash
ENABLE_BROWSER=true
```

terminal:
```bash
uv run bootcamp.py deploy
```

- Session permissions for your agent role on the AWS-managed `aws.browser.v1`
- The `browse_web` tool, handed to your orchestrator automatically
Flags default to `false` and need stage 4 or higher. `uv run bootcamp.py status` shows `CODE_INTERPRETER_ENABLED` and `BROWSER_ENABLED`.
You
## What you do as a developer
### Read the tool

phase2/app/agent/sandbox_tools.py:
```python
@tool
def browse_web(url: str) -> str:
    """Open a public web page in a secure AgentCore Browser sandbox and return its title, final URL and visible text.

    Args:
        url: Full http(s) URL of the page to open.
    """
    if urlparse(url).scheme not in {"http", "https"}:
        return "Only http(s) URLs are supported."
    with browser_session(REGION, identifier=BROWSER_ID) as client:
        ws_url, headers = client.generate_ws_headers()
        signed = {name: value for name, value in headers.items() if name in SIGNED_HEADERS}
        with connect(ws_url, additional_headers=signed, max_size=None, open_timeout=CDP_TIMEOUT_SECONDS) as socket:
            page = read_page(CdpConnection(socket), url)
    return f"Title: {page['title']}\nURL: {page['url']}\n\n{page['text']}"
```

No Playwright: the tool talks Chrome DevTools Protocol over the browser's SigV4-signed websocket (four CDP commands: open a tab, navigate, wait for load, read title and text). It returns the title, the final URL and the first 4,000 characters of visible text.

terminal:
```bash
uv run bootcamp.py invoke "Open https://example.com and tell me the page title." --actor alice-chen
```

### Add a research specialist
Challenge
In `phase2/app/agent/agent.py`, add a `research_agent` specialist that reads public pages with `browse_web` and summarises them with the source URL, and register it with the orchestrator.
**Where:** edit `phase2/app/agent/agent.py` in place, run `uv run bootcamp.py deploy` (~1.5 min), then check with `uv run bootcamp.py invoke "Summarise https://aws.amazon.com/bedrock/agentcore/ in three bullets" --actor alice-chen --stream`: the tool line shows `[calling research_agent]`, not `browse_web`.
Docs
- AgentCore Browser (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-tool.html)
- AgentCore Browser: using the browser tool (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-using-tool.html)
- Strands: agents as tools (https://strandsagents.com/docs/user-guide/sdk/multi-agent/agents-as-tools/)
#### Hint 1
Same pattern as `weather_agent`, different tool. AgentCore Browser docs (https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/browser-tool.html).
#### Hint 2
Import `browse_web` from `sandbox_tools`, pass `tools=[browse_web]`, and put guardrails in the prompt: cite the URL, don't guess content the page didn't show.
#### Solution: on the task page (open it only when the participant asks for the solution)
### Deploy and research

terminal:
```bash
uv run bootcamp.py deploy
uv run bootcamp.py invoke "Summarise https://aws.amazon.com/bedrock/agentcore/ in three bullets" --actor alice-chen
```

### Experiments
- Compare `browse_web` with the weather agent's `get_us_forecast` (one purpose-built API call): which pages need a real browser (JavaScript-rendered content)?
- Only http(s) URLs are accepted. What else would you restrict (domains, page size) and where: prompt, tool or policy?
- Check the cost of a browsing question with `uv run bootcamp.py llm`.
**See it in the console:** **AgentCore → Observability** (https://us-east-1.console.aws.amazon.com/bedrock-agentcore/observability?region=us-east-1): the trace of a research question: the `research_agent` span with its `browse_web` call inside.
## Check your work
With the flag on, `test --only 4` adds a _browser tool_ check. It sends exactly this prompt:

terminal · the check's prompt, to try by hand:
```bash
uv run bootcamp.py invoke "DataStream's network team needs the current AWS IP ranges version: use the browse_web tool (directly or through your research specialist) to open https://ip-ranges.amazonaws.com/ip-ranges.json and reply with the exact value of its syncToken field." --actor alice-chen
```

It passes when the answer contains the live `syncToken` of that file: a ~10-digit number such as `1791300000` that AWS changes several times a week, so the model can't know it without loading the page. The check fetches the file itself before and after the agent runs and accepts either value.

terminal:
```bash
uv run bootcamp.py test --only 4
```

expected output (abridged):
```text
[PASS] stage 4 ...
[PASS] stage 4 browser tool: The syncToken is 1791300000.
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
