"""`bootcamp.py memory`: what AgentCore Memory holds for one actor, short-term and long-term.

Short-term memory is the raw conversation: one event per turn, stored per actor and session (`ListSessions`,
`ListEvents`); the agent reloads a session's events when you continue it with `--session last`. Long-term memory is
what each strategy extracts from those events in the background (about 1-2 minutes later): records under the
strategy's namespace (`ListMemoryRecords`), which the agent searches before every model call (`RetrieveMemoryRecords`).
"""

from dataclasses import dataclass

from botocore.exceptions import ClientError

SHOWN_SESSIONS = 5
RECORDS_PER_NAMESPACE = 20
RECORD_CHARS = 160


@dataclass(frozen=True)
class Strategy:
    """One extraction strategy of a memory: its name, type, id and namespace template."""

    name: str
    type: str
    strategy_id: str
    template: str


def strategies(control, memory_id: str) -> list[Strategy]:
    """The memory's strategies as returned by `GetMemory` (first namespace template of each)."""
    memory = control.get_memory(memoryId=memory_id)["memory"]
    return [
        Strategy(item.get("name", ""), item.get("type", ""), item["strategyId"], _template(item))
        for item in memory.get("strategies", [])
    ]


def _template(item: dict) -> str:
    """A strategy's namespace template (`namespaceTemplates`, or the older `namespaces` field)."""
    return next(iter(item.get("namespaceTemplates") or item.get("namespaces") or [""]))


def by_type(found: list[Strategy], strategy_type: str) -> Strategy | None:
    """The first strategy of `strategy_type` (e.g. USER_PREFERENCE), or None."""
    return next((strategy for strategy in found if strategy.type == strategy_type), None)


def actor_namespace(strategy: Strategy, actor: str) -> str:
    """The namespace prefix holding `actor`'s records of `strategy`.

    A template part that is still unknown here (`{sessionId}`) and everything after it is cut off, so a per-session
    template yields the prefix of all the actor's sessions.
    """
    filled = strategy.template.replace("{memoryStrategyId}", strategy.strategy_id).replace("{actorId}", actor)
    return filled.split("{", 1)[0].rstrip("/")


def record_texts(data, memory_id: str, namespace: str, limit: int = RECORDS_PER_NAMESPACE) -> list[str]:
    """The text of up to `limit` long-term records under `namespace` (a path: its sub-namespaces are included)."""
    response = data.list_memory_records(memoryId=memory_id, namespacePath=namespace, maxResults=limit)
    return [record["content"]["text"] for record in response.get("memoryRecordSummaries", [])]


def recent_sessions(data, memory_id: str, actor: str) -> list[str]:
    """Up to SHOWN_SESSIONS of `actor`'s short-term sessions, newest first (none for an actor never seen)."""
    try:
        summaries = data.list_sessions(memoryId=memory_id, actorId=actor, maxResults=100).get("sessionSummaries", [])
    except ClientError as error:
        if error.response.get("Error", {}).get("Code") != "ResourceNotFoundException":
            raise
        return []
    summaries.sort(key=lambda summary: summary.get("createdAt", 0), reverse=True)
    return [summary["sessionId"] for summary in summaries[:SHOWN_SESSIONS]]


def event_count(data, memory_id: str, actor: str, session_id: str) -> int:
    """How many events (turns) the first page of `session_id` holds (at most 100)."""
    page = data.list_events(memoryId=memory_id, actorId=actor, sessionId=session_id, maxResults=100)
    return len(page.get("events", []))


def short_term_lines(data, memory_id: str, actor: str) -> list[str]:
    """One line per recent session of `actor`, with its event count."""
    sessions = recent_sessions(data, memory_id, actor)
    lines = [f"short-term (events per session, newest {SHOWN_SESSIONS}): {len(sessions)} shown"]
    lines += [f"  {session}: {event_count(data, memory_id, actor, session)} events" for session in sessions]
    return lines


def long_term_lines(data, memory_id: str, found: list[Strategy], actor: str) -> list[str]:
    """One block per strategy: its namespace for `actor` and the records in it."""
    lines = ["long-term (records per strategy namespace):"]
    for strategy in found:
        namespace = actor_namespace(strategy, actor)
        texts = record_texts(data, memory_id, namespace)
        lines.append(f"  {strategy.name} ({strategy.type}) {namespace}: {len(texts)} records")
        lines += [f"    - {_one_line(text)}" for text in texts]
    return lines


def report(session, memory_id: str, actor: str) -> list[str]:
    """Everything `bootcamp.py memory` prints for `actor`."""
    data = session.client("bedrock-agentcore")
    found = strategies(session.client("bedrock-agentcore-control"), memory_id)
    header = f"memory {memory_id}, actor {actor}"
    return [header, *short_term_lines(data, memory_id, actor), *long_term_lines(data, memory_id, found, actor)]


def _one_line(text: str) -> str:
    """`text` flattened to one line of at most RECORD_CHARS characters."""
    flat = " ".join(text.split())
    return flat if len(flat) <= RECORD_CHARS else flat[: RECORD_CHARS - 3] + "..."
