"""Shared settings for the Phase 1 tasks: model, paths, MCP client and a tiny CLI runner.

The runner prints every tool call (`[tool] query_db: SELECT ...`) so you can watch what the agent does; set
PHASE1_SHOW_TOOLS=0 to hide them. After a run it prints your remaining LiteLLM budget (PHASE1_SHOW_BUDGET=0 hides it).
"""

import json
import logging
import os
import sys
from collections.abc import Callable
from pathlib import Path

import httpx
import openai
from dotenv import load_dotenv
from mcp import StdioServerParameters, stdio_client
from strands import Agent
from strands.agent.conversation_manager import ConversationManager, SummarizingConversationManager
from strands.handlers.callback_handler import PrintingCallbackHandler
from strands.hooks import (
    AfterToolCallEvent,
    AgentInitializedEvent,
    BeforeModelCallEvent,
    BeforeToolCallEvent,
    HookProvider,
    HookRegistry,
)
from strands.models.openai import OpenAIModel
from strands.tools.mcp import MCPClient

PHASE1_DIR = Path(__file__).resolve().parent
load_dotenv(PHASE1_DIR.parent / ".env")
if not os.environ.get("AWS_PROFILE", "").strip():
    os.environ.pop("AWS_PROFILE", None)
sys.path.insert(0, str(PHASE1_DIR.parent / "shared"))

import litellm_gateway  # noqa: E402

MODEL_ID = os.getenv("MODEL_ID", "")
"""Set by `bootcamp.py phase1` (your .env MODEL_ID, else the class default)."""
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
DB_PATH = PHASE1_DIR / "datastream_corp.db"
SESSIONS_DIR = PHASE1_DIR / "sessions"
SESSION_ENV = "PHASE1_SESSION"
"""Set by `bootcamp.py phase1 tN --session NAME`: overrides the task's default session id."""
MCP_SERVER_PATH = PHASE1_DIR / "mcp_server.py"
STARTER_SERVER_PATH = PHASE1_DIR / "starter" / "mcp_server.py"
UNFINISHED_SERVER = "query_db is not implemented yet"
"""Text of the Task 2 starter server's stub; while it is there, Tasks 3-8 starters stop with a hint."""
ONE_SHOT = len(sys.argv) > 1
TASK_ID = Path(sys.argv[0]).stem.split("_")[0]
STARTER_RUN = Path(sys.argv[0]).resolve().parent.name == "starter"
"""True for `bootcamp.py phase1 tN --starter`: the starters then use YOUR Task 2 server, not the reference."""
SHOW_TOOLS = os.getenv("PHASE1_SHOW_TOOLS", "1") != "0"
SHOW_BUDGET = os.getenv("PHASE1_SHOW_BUDGET", "1") != "0"
SHOW_REASONING = os.getenv("PHASE1_SHOW_REASONING", "1") != "0"
DIM, RESET = "\033[2m", "\033[0m"
TOOL_INPUT_CHARS = 160
BUDGET_WARN_RATIO = 0.75
NOISY_LOGGERS = ("httpx", "httpcore", "mcp", "botocore", "urllib3", "fastmcp")
QUIET_SERVER_ENV = {"FASTMCP_LOG_LEVEL": "WARNING"}
"""Keeps the stdio MCP server from printing its INFO 'Starting MCP server' box into the chat."""

for _logger in NOISY_LOGGERS:
    logging.getLogger(_logger).setLevel(logging.WARNING)
logging.getLogger("strands.event_loop.event_loop").addFilter(lambda record: "NotImplementedError" not in record.args)
logging.getLogger("strands.models.openai").addFilter(
    lambda record: "reasoningContent is not supported" not in record.getMessage()
)
"""Strands drops a reasoning model's earlier thinking from resent history (expected); the warning is noise."""

SYSTEM_PROMPT = """You are a helpful assistant for DataStream Corp.

Some of our departments (the company has more than these):
- Sales: Handles customer relationships and revenue generation
- HR: Manages employee relations, hiring, and workplace culture
- Engineering: Builds and maintains our products and technical infrastructure

When you have database tools, use them for facts such as which departments exist and how many people work there.
Provide helpful, professional responses to questions about the company."""

APPROVAL_NOTE = """

You may change data when asked (INSERT, UPDATE, DELETE). A human approves every destructive query before it runs,
so call the tool directly instead of asking for confirmation in chat."""
"""Task 5: tells the model the approval step exists, so it calls the tool and the hook (not the chat) asks the human."""


def session_id(default: str) -> str:
    """The session to save under SESSIONS_DIR: `--session NAME` if given, else the task's `default`."""
    chosen = os.getenv(SESSION_ENV) or default
    print(f"[session] {chosen} (a new --session NAME starts fresh)", flush=True)
    return chosen


def make_model() -> OpenAIModel:
    """Every task talks to the model through the Opsfleet LiteLLM gateway (keyless, budgeted per participant)."""
    return litellm_gateway.make_model(MODEL_ID)


def mcp_server_path(starter: bool = STARTER_RUN, task: str = TASK_ID) -> Path:
    """The MCP server a task launches: the reference, or in a starter run your own phase1/starter/mcp_server.py.

    Args:
        starter: Whether a starter file is running.
        task: The running task, e.g. "t3"; Task 2 may launch the unfinished server (that is its exercise).

    Returns:
        Path of the server script.

    Raises:
        NotImplementedError: A Task 3-8 starter runs while the Task 2 starter server is still a stub.
    """
    if not starter:
        return MCP_SERVER_PATH
    if task != "t2" and UNFINISHED_SERVER in STARTER_SERVER_PATH.read_text(encoding="utf-8"):
        raise NotImplementedError(
            "Task 2 first: phase1/starter/mcp_server.py still has its TODO stub. Finish it, or copy "
            "phase1/mcp_server.py over it, then re-run"
        )
    return STARTER_SERVER_PATH


def make_mcp_client() -> MCPClient:
    """Return an MCP client that launches `mcp_server_path()` over stdio with this Python."""
    params = StdioServerParameters(
        command=sys.executable, args=[str(mcp_server_path())], env=os.environ | QUIET_SERVER_ENV
    )
    return MCPClient(lambda: stdio_client(params))


def find_todo(error: BaseException | None) -> NotImplementedError | None:
    """The NotImplementedError behind `error`, following `raise ... from` chains (Strands wraps hook errors).

    Args:
        error: The uncaught exception.

    Returns:
        The starter's TODO error, or None when the failure is something else.
    """
    while error is not None and not isinstance(error, NotImplementedError):
        error = error.__cause__ or error.__context__
    return error


def require_done(path: Path, todo: str) -> None:
    """Stop with the starter hint while a non-Python starter file (e.g. a SKILL.md) still contains `todo`."""
    if todo in path.read_text(encoding="utf-8"):
        raise NotImplementedError(f"{todo}: finish {path.relative_to(PHASE1_DIR.parent)}")


def _todo_hook(kind, error, traceback) -> None:
    """Starter files raise NotImplementedError for unfinished TODOs: show the hint, not a traceback."""
    todo = find_todo(error)
    if todo is None:
        sys.__excepthook__(kind, error, traceback)
        return
    print(f"\n[starter] {todo}\nFinish that TODO, or compare with the reference: uv run bootcamp.py phase1 {TASK_ID}")


sys.excepthook = _todo_hook


def describe_tool_input(tool_input: object) -> str:
    """One short line for a tool's input: `METHOD url` for HTTP tools, the bare value for single-argument tools,
    compact JSON otherwise.

    Args:
        tool_input: The `input` of a tool use (usually a dict of arguments).

    Returns:
        The input on a single line, cut to TOOL_INPUT_CHARS.
    """
    if isinstance(tool_input, dict) and "url" in tool_input:
        tool_input = f"{tool_input.get('method', 'GET')} {tool_input['url']}"
    elif isinstance(tool_input, dict) and len(tool_input) == 1:
        tool_input = next(iter(tool_input.values()))
    text = tool_input if isinstance(tool_input, str) else json.dumps(tool_input, default=str)
    text = " ".join(text.split())
    return text if len(text) <= TOOL_INPUT_CHARS else text[: TOOL_INPUT_CHARS - 3] + "..."


class ToolCallPrinter(HookProvider):
    """Prints `[tool] name: input` once per tool call, and a note when another hook (approval) cancels it.

    Hooks run again when an interrupted call resumes, so calls already shown are tracked by tool-use id.
    """

    def __init__(self) -> None:
        self.shown: set[str] = set()

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Run `show` before every tool call and `show_error` after it."""
        registry.add_callback(BeforeToolCallEvent, self.show)
        registry.add_callback(AfterToolCallEvent, self.show_error)

    def show_error(self, event: AfterToolCallEvent) -> None:
        """Print `[tool] name error: ...` when a call failed, e.g. structured output that did not validate (Task 6)."""
        if event.result.get("status") != "error" or event.cancel_message:
            return
        text = " ".join(block.get("text", "") for block in event.result.get("content", []))
        print(f"\n[tool] {event.tool_use.get('name')} error: {describe_tool_input(text)}")

    def show(self, event: BeforeToolCallEvent) -> None:
        """Print the tool name and a one-line view of its input the first time a call is seen."""
        name, call_id = event.tool_use.get("name"), event.tool_use.get("toolUseId", "")
        note = " (cancelled)" if event.cancel_tool else ""
        if call_id not in self.shown or not call_id:
            self.shown.add(call_id)
            print(f"\n[tool] {name}: {describe_tool_input(event.tool_use.get('input'))}{note}")
        elif note:
            print(f"\n[tool] {name}{note}")


class ContextPrinter(HookProvider):
    """Prints a `[context]` line whenever a conversation manager has just summarized (or dropped) older messages.

    Strands runs the manager's own before-model-call check first, so this hook sees its result for the same call.
    """

    def __init__(self, manager: ConversationManager) -> None:
        self.manager = manager
        self.seen = 0

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Remember the count restored from the session, then check before every model call."""
        registry.add_callback(AgentInitializedEvent, lambda event: self.reset())
        registry.add_callback(BeforeModelCallEvent, self.show)

    def reset(self) -> None:
        """Start counting from what the session already summarized."""
        self.seen = self.manager.removed_message_count

    def show(self, event: BeforeModelCallEvent) -> None:
        """Print the projected prompt size and the running total when messages just left the context."""
        removed = self.manager.removed_message_count
        if removed > self.seen:
            verb = "summarized" if isinstance(self.manager, SummarizingConversationManager) else "dropped"
            size = f"~{event.projected_input_tokens:,}" if event.projected_input_tokens else "?"
            limit = event.agent.model.context_window_limit or 0
            print(f"\n[context] prompt {size} of {limit:,} tokens: older messages {verb} ({removed} so far)")
        self.seen = removed


def _starts_tool(event: dict) -> bool:
    """Whether a Strands callback event opens a tool call."""
    return bool(event.get("event", {}).get("contentBlockStart", {}).get("start", {}).get("toolUse"))


class LabeledPrinter(PrintingCallbackHandler):
    """Strands' printer without its `Tool #1` lines, showing the model's reasoning as a dim `[reasoning]` block.

    Reasoning models (gpt-oss on Bedrock, for example) stream their thinking before the answer; Strands' default
    printer runs the two together. The answer itself never contains the reasoning. PHASE1_SHOW_REASONING=0 hides it.
    """

    def __init__(self) -> None:
        super().__init__(verbose_tool_use=False)
        self.thinking = False

    def __call__(self, **kwargs: object) -> None:
        reasoning = kwargs.pop("reasoningText", None)
        if reasoning and SHOW_REASONING:
            print(reasoning if self.thinking else f"\n{DIM}[reasoning] {reasoning}", end="", flush=True)
            self.thinking = True
        elif self.thinking and (kwargs.get("data") or kwargs.get("complete") or _starts_tool(kwargs)):
            print(f"{RESET}\n", end="")
            self.thinking = False
        super().__call__(**kwargs)


def quiet_tool_lines(agent: Agent) -> None:
    """Swap Strands' default printer for `LabeledPrinter` (ours prints tool lines with their input).

    Args:
        agent: A Strands agent; a custom or disabled callback handler is left alone.
    """
    if type(agent.callback_handler) is PrintingCallbackHandler:
        agent.callback_handler = LabeledPrinter()


def watch_tools(agent: Agent) -> Agent:
    """Attach a ToolCallPrinter to `agent` (unless PHASE1_SHOW_TOOLS=0), replacing Strands' terser tool lines.

    Args:
        agent: Any Strands agent, including specialists used as tools.

    Returns:
        The same agent, for chaining.
    """
    quiet_tool_lines(agent)
    if SHOW_TOOLS:
        agent.hooks.add_hook(ToolCallPrinter())
    return agent


def fetch_key_info() -> dict:
    """Spend and budget of the caller's LiteLLM key, keyless (STS identity) unless LITELLM_API_KEY is set.

    Returns:
        The gateway's `/key/info` `info` object.
    """
    api_key = os.getenv("LITELLM_API_KEY")
    auth = None if api_key else litellm_gateway.StsIdentityAuth()
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    with httpx.Client(base_url=os.environ["LITELLM_BASE_URL"], auth=auth, headers=headers, timeout=5) as client:
        return client.get("/key/info").raise_for_status().json().get("info", {})


def budget_line(spend: float, budget: float | None) -> str:
    """Human summary of LiteLLM spend, with a warning from BUDGET_WARN_RATIO of the budget used.

    Args:
        spend: Dollars spent so far.
        budget: The key's max budget in dollars, or None when unlimited.

    Returns:
        The line to print.
    """
    if not budget:
        return f"[budget] ${spend:.6f} spent (no budget limit)"
    line = f"[budget] ${spend:.6f} of ${budget:g} used ({spend / budget:.0%}), ${budget - spend:.6f} left"
    if spend >= BUDGET_WARN_RATIO * budget:
        line += " -- WARNING: budget nearly used up, ask the instructor before it runs out"
    return line


def report_budget() -> None:
    """Print the remaining LiteLLM budget; silently skipped when the gateway cannot be reached."""
    if not SHOW_BUDGET:
        return
    try:
        info = fetch_key_info()
    except (httpx.HTTPError, KeyError, ValueError):
        return
    print(budget_line(float(info.get("spend") or 0), info.get("max_budget")), "(may lag a few seconds)")


def ask_specialist(specialist: Agent, query: str, results: list[str]) -> str:
    """Run a specialist agent (printing its tool calls) and record its answer for `answer_or_fallback`.

    Args:
        specialist: The specialist agent behind an orchestrator tool.
        query: The question the orchestrator routed to it.
        results: Shared list of specialist answers for this turn.

    Returns:
        The specialist's answer text.
    """
    answer = str(watch_tools(specialist)(query))
    results.append(answer)
    return answer


def answer_or_fallback(orchestrator: Agent, specialist_results: list[str]) -> Callable[[str], object]:
    """Wrap an orchestrator so an empty final answer still shows the last specialist result.

    Args:
        orchestrator: The agent that routes to specialists.
        specialist_results: List the specialist tools append their answers to.

    Returns:
        A responder for `run`.
    """

    def respond(prompt: str) -> object:
        specialist_results.clear()
        result = orchestrator(prompt)
        if not str(result).strip():
            last = specialist_results[-1] if specialist_results else "(no specialist answered)"
            print(f"\n[fallback] Empty final answer (try another MODEL_ID); last specialist result:\n{last}")
        return result

    return respond


def chat(respond: Callable[[str], object]) -> None:
    """Answer the prompt given on the command line, or start a REPL (quit/exit to stop).

    Args:
        respond: An agent or any callable taking the prompt.
    """
    if ONE_SHOT:
        ask(respond, " ".join(sys.argv[1:]))
        return
    while (prompt := input("\nYou: ").strip()).lower() not in {"quit", "exit"}:
        if prompt:
            ask(respond, prompt)


def ask(respond: Callable[[str], object], prompt: str) -> None:
    """One turn; an unavailable model or a gateway that is off becomes a one-line hint instead of a traceback."""
    try:
        respond(prompt)
    except openai.APIError as error:
        hint = litellm_gateway.model_unavailable(MODEL_ID, str(error)) or litellm_gateway.gateway_down(
            getattr(error, "status_code", None)
        )
        if hint is None:
            raise
        print(f"\n[gateway] {hint}")
    print()


def run(respond: Callable[[str], object], watch: Agent | None = None) -> None:
    """Chat with `respond`, printing tool calls of `watch` (default: `respond` itself when it is an Agent).

    Args:
        respond: An agent or any callable taking the prompt.
        watch: Agent whose tool calls to print, when `respond` is a wrapper around it.
    """
    watched = watch or (respond if isinstance(respond, Agent) else None)
    if watched is not None:
        watch_tools(watched)
    try:
        chat(respond)
    except (KeyboardInterrupt, EOFError):
        print()
    report_budget()
