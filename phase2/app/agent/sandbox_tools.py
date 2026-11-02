"""Optional AgentCore built-in tools for the orchestrator: Code Interpreter and Browser.

Switched on per participant with ENABLE_CODE_INTERPRETER / ENABLE_BROWSER in .env; the platform then sets
CODE_INTERPRETER_ENABLED / BROWSER_ENABLED (and the tool ids) on the runtime and grants its role the session APIs.
Both use the AWS-managed tools (aws.codeinterpreter.v1, aws.browser.v1): every call starts a fresh, isolated
sandbox session and stops it afterwards, so nothing leaks between participants or requests.

The browser tool drives the remote headless Chromium over its Chrome DevTools Protocol (CDP) websocket with the
`websockets` package instead of Playwright: Playwright ships a ~40 MB Node driver per platform, and reading a page
(navigate, wait for load, read title + visible text) needs only four CDP commands.
"""

import itertools
import json
import os
import time
from urllib.parse import urlparse

from bedrock_agentcore.tools import browser_session, code_session
from strands import tool
from websockets.sync.client import ClientConnection, connect

REGION = os.environ["AWS_REGION"]
CODE_INTERPRETER_ID = os.getenv("CODE_INTERPRETER_ID", "aws.codeinterpreter.v1")
BROWSER_ID = os.getenv("BROWSER_ID", "aws.browser.v1")
OUTPUT_LIMIT = 4000
CDP_TIMEOUT_SECONDS = 30
PAGE_LOAD_POLLS = 40
PAGE_LOAD_POLL_SECONDS = 0.5
SIGNED_HEADERS = ("Authorization", "X-Amz-Date", "X-Amz-Security-Token", "User-Agent")
"""SigV4 headers from BrowserClient.generate_ws_headers; the websocket handshake headers are added by `websockets`."""
READ_PAGE_JS = (
    "JSON.stringify({title: document.title, url: location.href, "
    f"text: (document.body ? document.body.innerText : '').slice(0, {OUTPUT_LIMIT})}})"
)
PROMPT_HINTS = {
    "run_python": "Use run_python for calculations, statistics or data transformations instead of doing math yourself.",
    "browse_web": "Use browse_web to open a public web page when the user asks about a URL or live web content.",
}


def capability_enabled(flag: str) -> bool:
    """True when the runtime env var `flag` is "true" (set by Terraform from the participant's .env)."""
    return os.getenv(flag, "false").strip().lower() == "true"


def optional_tools() -> list:
    """The sandbox tools this runtime is configured for (empty when both capabilities are off)."""
    tools = []
    if capability_enabled("CODE_INTERPRETER_ENABLED"):
        tools.append(run_python)
    if capability_enabled("BROWSER_ENABLED"):
        tools.append(browse_web)
    return tools


def prompt_hints(tools: list) -> str:
    """Orchestrator prompt lines describing the enabled sandbox tools."""
    return "\n".join(PROMPT_HINTS[t.tool_name] for t in tools if t.tool_name in PROMPT_HINTS)


@tool
def run_python(code: str) -> str:
    """Execute Python code in a secure AgentCore Code Interpreter sandbox and return its output.

    Use it for calculations, statistics and data transformations. print() every value you need to see.

    Args:
        code: Python source code to run.
    """
    with code_session(REGION, identifier=CODE_INTERPRETER_ID) as client:
        return stream_text(client.execute_code(code))[:OUTPUT_LIMIT]


def stream_text(response: dict) -> str:
    """Join the text content of a Code Interpreter event stream (stdout, stderr or the error message)."""
    parts = []
    for event in response["stream"]:
        parts += [item.get("text", "") for item in event.get("result", {}).get("content", [])]
    return "\n".join(part for part in parts if part) or "(no output)"


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


class CdpConnection:
    """Minimal request/response client for a browser-level Chrome DevTools Protocol websocket."""

    def __init__(self, socket: ClientConnection) -> None:
        self._socket = socket
        self._ids = itertools.count(1)

    def send(self, method: str, params: dict | None = None, session_id: str | None = None) -> dict:
        """Send one CDP command (optionally to an attached page session) and return its result."""
        message_id = next(self._ids)
        message = {"id": message_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        self._socket.send(json.dumps(message))
        while True:
            reply = json.loads(self._socket.recv(timeout=CDP_TIMEOUT_SECONDS))
            if reply.get("id") == message_id:
                if "error" in reply:
                    raise RuntimeError(f"CDP {method} failed: {reply['error'].get('message')}")
                return reply.get("result", {})


def read_page(cdp: CdpConnection, url: str) -> dict:
    """Open `url` in a new tab, wait for the load to complete and return {title, url, text}."""
    target_id = cdp.send("Target.createTarget", {"url": "about:blank"})["targetId"]
    session_id = cdp.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
    cdp.send("Page.navigate", {"url": url}, session_id)
    for _ in range(PAGE_LOAD_POLLS):
        if evaluate(cdp, session_id, "document.readyState") == "complete":
            break
        time.sleep(PAGE_LOAD_POLL_SECONDS)
    return json.loads(evaluate(cdp, session_id, READ_PAGE_JS))


def evaluate(cdp: CdpConnection, session_id: str, expression: str) -> object:
    """Evaluate a JavaScript expression in the page and return its JSON value."""
    result = cdp.send("Runtime.evaluate", {"expression": expression, "returnByValue": True}, session_id)
    return result.get("result", {}).get("value")
