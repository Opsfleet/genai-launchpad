"""`invoke` helpers: an overall deadline, a compact view of the agent's reply (or its live stream), and a local
session history.

The history (`.build/invocations_<participant>.jsonl`, git-ignored) remembers which session, actor and prompt each
`invoke` used, so `invoke --session last` can reuse a warm session, `traces` defaults to your own latest invoke
(not a `test` check) and `scores` can show who asked.
"""

import io
import json
import sys
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

import requests

from bootcamp_cli import agentcore
from bootcamp_cli.config import ROOT

HISTORY_DIR = ROOT / ".build"
HISTORY_LIMIT = 200
LAST_SESSION = "last"
DEADLINE_SECONDS = agentcore.INVOKE_READ_SECONDS + 20
"""Overall deadline for one `invoke`: the read timeout plus the token request and connection."""
MIN_SESSION_CHARS = 33
EXTRA_FIELD_CHARS = 200
PROMPT_WORDS = 6


def history_path(participant: str) -> Path:
    """Where this participant's invoke history lives."""
    return HISTORY_DIR / f"invocations_{participant}.jsonl"


def load_history(participant: str) -> list[dict]:
    """Every remembered invoke, oldest first (empty when there is none or the file is unreadable)."""
    try:
        lines = history_path(participant).read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def remember(participant: str, session_id: str, actor: str, prompt: str) -> None:
    """Append one invoke to the history, keeping the newest HISTORY_LIMIT entries."""
    entry = {"session": session_id, "actor": actor, "prompt": first_words(prompt), "time": int(time.time())}
    entries = [*load_history(participant), entry][-HISTORY_LIMIT:]
    HISTORY_DIR.mkdir(exist_ok=True)
    history_path(participant).write_text("".join(json.dumps(item) + "\n" for item in entries), encoding="utf-8")


def last_session(participant: str) -> str | None:
    """Session id of the participant's latest `invoke` on this machine, or None."""
    entries = load_history(participant)
    return entries[-1]["session"] if entries else None


def session_actors(participant: str) -> dict[str, str]:
    """Session id -> actor for every remembered invoke."""
    return {entry["session"]: entry.get("actor", "?") for entry in load_history(participant)}


def first_words(text: str, words: int = PROMPT_WORDS) -> str:
    """The first `words` words of `text` on one line, with "..." when cut."""
    parts = text.split()
    return " ".join(parts[:words]) + (" ..." if len(parts) > words else "")


def resolve_session(requested: str | None, participant: str) -> str:
    """The session id to invoke: a new one, the last one (`last`), or the given id.

    Raises:
        RuntimeError: `last` with no earlier invoke, or an id AgentCore would reject.
    """
    if requested is None:
        return agentcore.new_session_id()
    if requested == LAST_SESSION:
        session_id = last_session(participant)
        if session_id is None:
            raise RuntimeError("No earlier `invoke` on this machine: run one without --session first.")
        return session_id
    if len(requested) < MIN_SESSION_CHARS or not requested.replace("-", "").replace("_", "").isalnum():
        raise RuntimeError(f"--session must be `last` or an id of {MIN_SESSION_CHARS}+ letters, digits, - or _.")
    return requested


def compact(value: object, limit: int = EXTRA_FIELD_CHARS) -> str:
    """A reply field on one line (strings bare, the rest as JSON), cut to `limit` characters."""
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."


def render_reply(body: dict, as_json: bool = False) -> str:
    """The answer text followed by one `key: value` line per extra reply field (or the raw JSON)."""
    if as_json:
        return json.dumps(body, indent=2, ensure_ascii=False, default=str)
    answer = str(body.get("response", "")).strip() or "(empty answer)"
    extras = [f"{key}: {compact(value)}" for key, value in body.items() if key != "response"]
    return "\n".join([answer, "", *extras]) if extras else answer


@dataclass
class StreamPrinter:
    """Prints a streamed reply as it arrives: text deltas to `out`, tool calls on their own lines to `notes`."""

    out: TextIO = field(default_factory=lambda: sys.stdout)
    notes: TextIO = field(default_factory=lambda: sys.stderr)
    tools: list[str] = field(default_factory=list)
    reply: dict = field(default_factory=dict)
    text: str = ""

    def handle(self, event: dict) -> None:
        """Print one event: `delta` text, a `tool` call, or the final reply object (has "response").

        Raises:
            RuntimeError: The runtime reported an error inside the stream.
        """
        if "error" in event:
            raise RuntimeError(f"the agent failed mid-stream: {event.get('error_type', '')} {event['error']}")
        if "delta" in event:
            self._write(self.out, str(event["delta"]))
        elif "tool" in event:
            self.tools.append(str(event["tool"]))
            self._note(f"[calling {event['tool']}]")
        elif "response" in event:
            self.reply = event

    def finish(self) -> None:
        """End the answer line; print the reply text if no delta was streamed (e.g. the agent's fallback answer)."""
        if not self.text.strip():
            self._write(self.out, str(self.reply.get("response", "")).strip() or "(empty answer)")
        self._write(self.out, "\n")

    def _note(self, line: str) -> None:
        if self.text and not self.text.endswith("\n"):
            self._write(self.out, "\n")
        print(line, file=self.notes, flush=True)

    def _write(self, stream: TextIO, text: str) -> None:
        stream.write(text)
        stream.flush()
        if stream is self.out:
            self.text += text


def print_stream(events: Iterable[dict], as_json: bool = False) -> StreamPrinter:
    """Print a streamed reply live (or each raw event as one JSON line) and return what was seen."""
    printer = StreamPrinter(out=io.StringIO(), notes=io.StringIO()) if as_json else StreamPrinter()
    for event in events:
        if as_json:
            print(json.dumps(event, ensure_ascii=False), flush=True)
        printer.handle(event)
    if not as_json:
        printer.finish()
    return printer


def timeout_message(session_id: str) -> str:
    """What to do when no answer arrived in time: the agent may still be working on it."""
    return (
        f"No answer from your agent within {agentcore.INVOKE_READ_SECONDS}s. It may still finish server-side: in a "
        f"few minutes run `uv run bootcamp.py traces {session_id}` to see what it did (spans lag 2-10 min), or "
        "check the runtime logs (`status` -> AGENT_LOG_GROUP)."
    )


def with_deadline[T](call: Callable[[], T], session_id: str) -> T:
    """Run `call` on a daemon thread so a stalled HTTP response never hangs the CLI past DEADLINE_SECONDS.

    Raises:
        RuntimeError: No answer in time (a read timeout or the overall deadline), with what to check next.
    """
    result: dict = {}

    def run() -> None:
        try:
            result["value"] = call()
        except Exception as error:  # noqa: BLE001 - re-raised on the main thread
            result["error"] = error

    worker = threading.Thread(target=run, daemon=True)
    worker.start()
    worker.join(DEADLINE_SECONDS)
    if worker.is_alive() or isinstance(result.get("error"), requests.Timeout):
        raise RuntimeError(timeout_message(session_id))
    if "error" in result:
        raise result["error"]
    return result["value"]
