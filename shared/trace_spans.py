"""Read an agent turn out of the span records AgentCore Evaluations hands a code-based evaluator.

AgentCore invokes a code-based evaluator once per trace (one agent turn) with the session's spans; each span record
carries its OTel log events (`span_events`, whose `body.input.messages` / `body.output.messages` hold the
conversation). Shared by both Task 6 evaluator Lambdas (`exact_numbers`, `rubric_judge`); copied into every
Phase 2 app zip by bootcamp_cli.build. Standard library only.

Contract: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html
"""

import json

AGENT_SPAN_PREFIX = "invoke_agent"
CONTEXT_CHARS = 12000
"""Upper bound of the conversation text handed to a judge (the newest part is kept)."""


def message_text(content: object) -> str:
    """Plain text of a message content (a string, a list of parts or a {"text": ...} part)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(message_text(part) for part in content)
    if isinstance(content, dict):
        return message_text(content.get("text") or content.get("message") or content.get("content") or "")
    return ""


def bodies(record: dict) -> list[dict]:
    """The OTel log bodies of a span record: its own `body` and those of its `span_events`."""
    found = [record.get("body"), *[event.get("body") for event in record.get("span_events") or []]]
    return [body for body in found if isinstance(body, dict)]


def messages(record: dict, side: str) -> list[dict]:
    """The `input` or `output` messages of a span record's log bodies."""
    found = [message for body in bodies(record) for message in (body.get(side) or {}).get("messages") or []]
    return [message for message in found if isinstance(message, dict)]


def outputs(record: dict) -> list[str]:
    """Assistant texts a span record carries (`output.messages` of its log bodies, or a `gen_ai.completion`); tool
    calls without text carry none."""
    contents = [message.get("content") for message in messages(record, "output")]
    contents.append((record.get("attributes") or {}).get("gen_ai.completion"))
    return [text for text in (block_text(blocks(content)) for content in contents) if text]


def in_trace(record: dict, trace_id: str | None) -> bool:
    return trace_id is None or record.get("traceId") == trace_id


def start(record: dict) -> int:
    return int(record.get("startTimeUnixNano") or 0)


def outermost_agent(records: list[dict], trace_id: str | None) -> dict | None:
    """The outermost agent invocation span of the trace (the orchestrator, not its specialists)."""
    agents = [r for r in records if str(r.get("name", "")).startswith(AGENT_SPAN_PREFIX) and in_trace(r, trace_id)]
    return min(agents, key=start) if agents else None


def agent_span_ids(records: list[dict], trace_id: str | None) -> set[str]:
    """Span ids of the outermost agent invocation in the trace."""
    root = outermost_agent(records, trace_id)
    return {str(root.get("spanId", ""))} if root else set()


def final_answer(records: list[dict], trace_id: str | None) -> str:
    """The orchestrator's answer for the trace; falls back to the latest assistant text in the trace."""
    roots = agent_span_ids(records, trace_id)
    traced = [record for record in records if in_trace(record, trace_id) and outputs(record)]
    preferred = [record for record in traced if str(record.get("spanId", "")) in roots] or traced
    if not preferred:
        return ""
    latest = max(preferred, key=lambda record: int(record.get("timeUnixNano") or record.get("endTimeUnixNano") or 0))
    return outputs(latest)[-1]


def question(records: list[dict], trace_id: str | None) -> str:
    """The user's question of the trace: the last user text (not a tool result) the orchestrator span received."""
    root = outermost_agent(records, trace_id)
    users = [message for message in messages(root or {}, "input") if message.get("role") == "user"]
    texts = [block_text(blocks(message.get("content"))) for message in users]
    return next((text for text in reversed(texts) if text), "")


def expected_response(event: dict) -> str:
    """The ground-truth expected answer for this trace, if `eval` provided one."""
    for reference in event.get("evaluationReferenceInputs") or []:
        text = message_text((reference or {}).get("expectedResponse"))
        if text:
            return text
    return ""


def blocks(content: object) -> list[dict]:
    """A message's content blocks: a JSON list stored as a string under content.content / content.message, a bare
    list, or plain text (one text block)."""
    raw = (content.get("content") or content.get("message") or "") if isinstance(content, dict) else content
    parsed = _json_list(raw) if isinstance(raw, str) else raw
    if isinstance(parsed, list):
        return [block for block in parsed if isinstance(block, dict)]
    text = raw if isinstance(raw, str) else message_text(raw)
    return [{"text": text}] if text.strip() else []


def _json_list(raw: str) -> list | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, list) else None


def block_text(found: list[dict]) -> str:
    """The text blocks of a message, joined."""
    return " ".join(str(block["text"]) for block in found if block.get("text")).strip()


def describe(role: str, block: dict) -> str:
    """One conversation line for a content block: text, a tool call or a tool result ("" for anything else)."""
    if block.get("text"):
        return f"{role}: {block['text']}"
    if isinstance(block.get("toolUse"), dict):
        use = block["toolUse"]
        return f"{role} calls tool {use.get('name')}({json.dumps(use.get('input'), default=str)})"
    if isinstance(block.get("toolResult"), dict):
        return f"tool result: {message_text(block['toolResult'].get('content'))}"
    return ""


def conversation(records: list[dict], trace_id: str | None) -> str:
    """The trace's conversation, one line per message part (user, tool calls with inputs, tool results, answers).

    Every span's input and output messages, oldest span first, each distinct line once (model-call spans repeat
    the conversation so far); cut to the newest CONTEXT_CHARS characters.
    """
    lines: dict[str, None] = {}
    for record in sorted((r for r in records if in_trace(r, trace_id)), key=start):
        for side in ("input", "output"):
            for message in messages(record, side):
                for block in blocks(message.get("content")):
                    line = " ".join(describe(str(message.get("role", "")), block).split())
                    if line:
                        lines[line] = None
    return "\n".join(lines)[-CONTEXT_CHARS:]
