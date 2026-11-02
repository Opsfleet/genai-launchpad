"""CLI views of the participant's observability data: a span tree per session and recent evaluation scores.

Spans live in the account-wide `aws/spans` log group (Transaction Search), filtered by the runtime's service name
`awsworkshop_<name>_agent.DEFAULT`; online-evaluation results land in
`/aws/bedrock-agentcore/evaluations/results/awsworkshop_<name>_*`. Both are read with CloudWatch Logs Insights.
Spans carry no tool inputs or prompts: Strands writes those as `strands.telemetry.tracer` records (the model's
messages, including each `toolUse` with its input) to the `otel-rt-logs` stream of your runtime's own log group.
"""

import json
import re
import time
from collections import defaultdict
from itertools import groupby

from bootcamp_cli.agentcore import CHECK_SESSION_PREFIX, is_check_session

SPANS_GROUP = "aws/spans"
EVAL_GROUP_PREFIX = "/aws/bedrock-agentcore/evaluations/results/awsworkshop_{participant}_"
QUERY_TIMEOUT_SECONDS = 60
ARGS_HELP = "also show each tool call's input (e.g. the SQL), read from your runtime log group's otel-rt-logs stream"
NO_TOOL_INPUTS_HINT = (
    "(no tool inputs found for this session in your runtime log group's otel-rt-logs stream: they lag a few minutes, "
    "and are missing when the agent called no tool)"
)
RUNTIME_LOG_STREAM = "otel-rt-logs"
INPUT_CHARS = 140
PROMPT_WORDS = 6
CHECK_LABEL = "(test)"
SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
SPAN_FIELDS = (
    "traceId, spanId, parentSpanId, name, durationNano, startTimeUnixNano, "
    "attributes.gen_ai.usage.input_tokens as input_tokens, attributes.gen_ai.usage.output_tokens as output_tokens, "
    "attributes.gen_ai.tool.call.id as tool_call"
)
EVAL_FIELDS = (
    "@timestamp, attributes.gen_ai.evaluation.name as evaluator, attributes.gen_ai.evaluation.score.value as score, "
    "attributes.gen_ai.evaluation.score.label as label, attributes.session.id as session"
)


def service_name(participant: str) -> str:
    """OpenTelemetry service name of the participant's agent runtime (DEFAULT endpoint)."""
    return f"awsworkshop_{participant}_agent.DEFAULT"


def run_query(logs, groups: list[str], query: str, hours: float) -> list[dict[str, str]]:
    """Run a Logs Insights query over the last `hours` and return its rows as dicts.

    Raises:
        RuntimeError: the query failed or did not finish within QUERY_TIMEOUT_SECONDS.
    """
    now = int(time.time())
    query_id = logs.start_query(
        logGroupNames=groups, startTime=now - int(hours * 3600), endTime=now, queryString=query
    )["queryId"]
    deadline = time.monotonic() + QUERY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        result = logs.get_query_results(queryId=query_id)
        if result["status"] == "Complete":
            return [{field["field"]: field["value"] for field in row} for row in result["results"]]
        if result["status"] in {"Failed", "Cancelled", "Timeout"}:
            raise RuntimeError(f"Logs Insights query {result['status'].lower()}: {query}")
        time.sleep(1)
    raise RuntimeError("Logs Insights query did not finish within a minute; retry, or narrow --hours.")


def latest_session(logs, service: str, hours: float) -> str | None:
    """Id of the most recent runtime session that produced spans, skipping `test` check sessions, or None."""
    query = (
        f'fields attributes.session.id as session | filter resource.attributes.service.name = "{service}" '
        f"and ispresent(session) and session not like /^{CHECK_SESSION_PREFIX}/ | sort @timestamp desc | limit 1"
    )
    rows = run_query(logs, [SPANS_GROUP], query, hours)
    return rows[0]["session"] if rows else None


def check_session_id(session_id: str) -> str:
    """`session_id`, validated because it goes into a query.

    Raises:
        RuntimeError: `session_id` contains characters a runtime session id never has.
    """
    if not SESSION_ID_PATTERN.match(session_id):
        raise RuntimeError(f"Not a session id: {session_id!r} (copy it from the `invoke` output).")
    return session_id


def session_spans(logs, service: str, session_id: str, hours: float) -> list[dict[str, str]]:
    """Every span of one session of the participant's agent.

    Raises:
        RuntimeError: `session_id` is not a valid session id.
    """
    check_session_id(session_id)
    query = (
        f'fields {SPAN_FIELDS} | filter resource.attributes.service.name = "{service}" '
        f'and attributes.session.id = "{session_id}" | sort startTimeUnixNano asc | limit 1000'
    )
    return run_query(logs, [SPANS_GROUP], query, hours)


def render_tree(spans: list[dict[str, str]], inputs: dict[str, str] | None = None) -> list[str]:
    """One line per span (repeated leaf siblings collapsed), children indented under their parent, per trace.

    Args:
        spans: The session's spans (see `session_spans`).
        inputs: Tool call id -> one-line tool input (see `tool_inputs`), shown on that tool's span.
    """
    known = {span["spanId"] for span in spans}
    children: dict[str, list[dict]] = defaultdict(list)
    for span in sorted(spans, key=lambda item: int(item.get("startTimeUnixNano", 0))):
        parent = span.get("parentSpanId", "")
        children[parent if parent in known else span["traceId"]].append(span)
    lines: list[str] = []
    for trace_id in dict.fromkeys(span["traceId"] for span in spans):
        lines.append(f"trace {trace_id}")
        _render_children(children, trace_id, 1, lines, inputs or {})
    return lines


def _render_children(
    children: dict[str, list[dict]], parent: str, depth: int, lines: list[str], inputs: dict[str, str]
) -> None:
    """Append `parent`'s children (consecutive same-name leaves merged as "xN") and recurse."""
    for _, run in groupby(children.get(parent, []), key=lambda span: _merge_key(span, children, inputs)):
        group = list(run)
        lines.append("  " * depth + _span_label(group) + _input_note(group[0], inputs))
        if len(group) == 1:
            _render_children(children, group[0]["spanId"], depth + 1, lines, inputs)


def _merge_key(span: dict[str, str], children: dict[str, list[dict]], inputs: dict[str, str]) -> str:
    """Leaves merge with same-name neighbours; spans with children or a shown input never merge."""
    unique = span["spanId"] in children or span.get("tool_call") in inputs
    return span["spanId"] if unique else f"leaf:{span['name']}"


def _input_note(span: dict[str, str], inputs: dict[str, str]) -> str:
    tool_input = inputs.get(span.get("tool_call", ""))
    return f"  <- {tool_input}" if tool_input else ""


def _span_label(group: list[dict[str, str]]) -> str:
    """`name xN  1.23s  tokens in/out` for a run of identical sibling spans."""
    seconds = sum(int(span.get("durationNano", 0)) for span in group) / 1e9
    count = f" x{len(group)}" if len(group) > 1 else ""
    tokens = [span for span in group if span.get("input_tokens")]
    usage = "".join(f"  tokens {span['input_tokens']} in/{span.get('output_tokens', '?')} out" for span in tokens[:1])
    return f"{group[0]['name']}{count}  {seconds:.2f}s{usage}"


def runtime_records(logs, group: str, session_ids: list[str], hours: float, like: str = "") -> list[dict]:
    """Parsed Strands telemetry records (model messages) of some sessions, oldest first.

    Args:
        logs: CloudWatch Logs client.
        group: The agent runtime's log group (`status` -> AGENT_LOG_GROUP).
        session_ids: Sessions to read (validated: they go into the query).
        hours: How far back to look.
        like: Optional plain word the raw record must contain (narrows the scan, e.g. "toolUse").
    """
    quoted = ", ".join(f'"{check_session_id(session_id)}"' for session_id in session_ids)
    narrow = f" and @message like /{re.escape(like)}/" if like else ""
    query = (
        f'fields @message | filter @logStream = "{RUNTIME_LOG_STREAM}" and attributes.session.id in [{quoted}]'
        f"{narrow} | sort @timestamp asc | limit 1000"
    )
    return [parse_record(row.get("@message", "")) for row in run_query(logs, [group], query, hours)]


def parse_record(message: str) -> dict:
    """A log message parsed as a JSON object ({} when it is not one)."""
    try:
        record = json.loads(message)
    except json.JSONDecodeError:
        return {}
    return record if isinstance(record, dict) else {}


def record_blocks(record: dict) -> list[tuple[str, dict]]:
    """(role, content block) for every message in a record's input and output (content is a JSON string)."""
    body = record.get("body") if isinstance(record.get("body"), dict) else {}
    pairs = []
    for side in ("input", "output"):
        for message in (body.get(side) or {}).get("messages", []):
            pairs += [(message.get("role", ""), block) for block in _blocks(_raw_content(message))]
    return pairs


def _raw_content(message: object) -> object:
    """A message's content blocks as stored: a JSON string under content.content / content.message, or bare."""
    content = message.get("content") if isinstance(message, dict) else None
    if isinstance(content, dict):
        return content.get("content") or content.get("message") or "[]"
    return content or "[]"


def _blocks(raw: object) -> list[dict]:
    try:
        blocks = json.loads(raw) if isinstance(raw, str) else raw
    except json.JSONDecodeError:
        return []
    return [block for block in blocks if isinstance(block, dict)] if isinstance(blocks, list) else []


def tool_inputs(logs, group: str | None, session_id: str, hours: float) -> dict[str, str]:
    """Tool call id -> one-line input for every tool call of a session (empty without a runtime log group)."""
    if not group:
        return {}
    inputs = {}
    for record in runtime_records(logs, group, [session_id], hours, like="toolUse"):
        for _, block in record_blocks(record):
            use = block.get("toolUse")
            if isinstance(use, dict) and use.get("toolUseId"):
                inputs[use["toolUseId"]] = describe_input(use.get("input"))
    return inputs


def describe_input(tool_input: object) -> str:
    """A tool input on one line: the bare value for single-argument tools, compact JSON otherwise."""
    if isinstance(tool_input, dict) and len(tool_input) == 1:
        tool_input = next(iter(tool_input.values()))
    text = tool_input if isinstance(tool_input, str) else json.dumps(tool_input, default=str)
    text = " ".join(text.split())
    return text if len(text) <= INPUT_CHARS else text[: INPUT_CHARS - 3] + "..."


def first_prompts(logs, group: str | None, session_ids: list[str], hours: float) -> dict[str, str]:
    """Session id -> first words of the first user prompt seen in that session's runtime records."""
    if not group or not session_ids:
        return {}
    prompts: dict[str, str] = {}
    for record in runtime_records(logs, group, session_ids, hours):
        session_id = (record.get("attributes") or {}).get("session.id", "")
        text = next((b["text"] for role, b in record_blocks(record) if role == "user" and "text" in b), "")
        if session_id and text and session_id not in prompts:
            words = text.split()
            prompts[session_id] = " ".join(words[:PROMPT_WORDS]) + (" ..." if len(words) > PROMPT_WORDS else "")
    return prompts


def evaluation_groups(logs, participant: str) -> list[str]:
    """The participant's online-evaluation result log groups (AgentCore creates them on first result)."""
    prefix = EVAL_GROUP_PREFIX.format(participant=participant)
    pages = logs.get_paginator("describe_log_groups").paginate(logGroupNamePrefix=prefix)
    return [group["logGroupName"] for page in pages for group in page["logGroups"]]


def recent_scores(logs, participant: str, hours: float, limit: int) -> list[dict[str, str]]:
    """Newest evaluation results first (empty when no evaluation group exists yet)."""
    groups = evaluation_groups(logs, participant)[:50]
    if not groups:
        return []
    query = f"fields {EVAL_FIELDS} | filter ispresent(score) | sort @timestamp desc | limit {limit}"
    return run_query(logs, groups, query, hours)


def render_scores(rows: list[dict[str, str]], actors: dict[str, str] | None = None) -> list[str]:
    """A header plus one aligned line per evaluation result (times in UTC).

    Args:
        rows: Results from `recent_scores`.
        actors: Session id -> who asked (actor, or the prompt's first words); `test` sessions are labelled.
    """
    lines = [f"{'time (UTC)':<19}  {'evaluator':<26} {'score':>5}  {'label':<20} {'actor / prompt':<24} session"]
    for row in rows:
        session = row.get("session", "")
        lines.append(
            f"{row.get('@timestamp', '')[:19]}  {row.get('evaluator', '?'):<26} {float(row.get('score', 0)):>5.2f}  "
            f"{row.get('label', ''):<20} {_actor(session, actors or {})[:24]:<24} {session}"
        )
    return lines


def _actor(session: str, actors: dict[str, str]) -> str:
    if session in actors:
        return actors[session]
    return CHECK_LABEL if is_check_session(session) else "-"
