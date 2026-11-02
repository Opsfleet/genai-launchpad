"""LLM-as-a-judge as a code-based AgentCore evaluator (Phase 2, Task 6 Part C): `rubric_judge`.

AgentCore's managed LLM-as-a-judge evaluators call Bedrock as the caller, and on this platform nobody but the
LiteLLM gateway calls Bedrock. So the judge lives in this Lambda: AgentCore invokes it once per trace with the
session's spans, it fills the rubric of `evaluators.yaml` (packaged next to this file, entry JUDGE_RUBRIC) with the
turn's conversation and answer, asks JUDGE_MODEL through the gateway and returns the score.

Keyless: each request carries a presigned STS GetCallerIdentity URL signed with this function's role
(awsworkshop-<you>-rubric-judge), the same protocol as shared/litellm_gateway.py. The gateway maps that role to you,
so judge calls bill your LiteLLM budget. A gateway or reply problem returns an evaluator error, never a crash.
"""

import json
import logging
import os
import re
from pathlib import Path

import boto3
import httpx
import yaml

from trace_spans import conversation, expected_response, final_answer

log = logging.getLogger()
log.setLevel(logging.INFO)

RUBRIC_FILE = Path(__file__).with_name("evaluators.yaml")
IDENTITY_HEADER = "X-Amz-Sts-Identity-Url"
TIMEOUT = httpx.Timeout(45.0, connect=5.0)
MAX_TOKENS = 1024
"""Room for a reasoning judge model: with too few tokens it can spend them all thinking and reply with nothing."""
JSON_OBJECT = re.compile(r"\{.*\}", re.DOTALL)
NO_REFERENCE = "(no reference answer for this turn)"
REPLY_FORMAT = (
    "Reply with one JSON object and nothing else: "
    '{"score": <a score from the rating scale>, "label": "<its label>", "explanation": "<one or two sentences>"}'
)


def load_rubric(name: str, path: Path | None = None) -> dict:
    """The rubric entry `name` of evaluators.yaml (default: the packaged RUBRIC_FILE).

    Raises:
        KeyError: No entry has that name.
    """
    path = path or RUBRIC_FILE
    rubrics = {entry["name"]: entry for entry in yaml.safe_load(path.read_text(encoding="utf-8"))}
    if name not in rubrics:
        raise KeyError(f"rubric {name!r} not in {path.name} (has: {', '.join(rubrics)})")
    return rubrics[name]


def judge_messages(rubric: dict, context: str, answer: str, expected: str) -> list[dict]:
    """The judge's chat: the rubric with its placeholders filled, then the rating scale and the reply format."""
    filled = rubric["instructions"]
    for placeholder, value in {"context": context, "assistant_turn": answer, "expected_response": expected}.items():
        filled = filled.replace("{" + placeholder + "}", value or NO_REFERENCE)
    scale = "\n".join(f"- {level['value']}: {level['label']} - {level['definition']}" for level in rubric["scale"])
    return [
        {"role": "system", "content": f"You are a strict evaluator.\n\nRating scale:\n{scale}\n\n{REPLY_FORMAT}"},
        {"role": "user", "content": filled},
    ]


def identity_url() -> str:
    """A 2-minute presigned STS GetCallerIdentity URL (GET), signed with this function's role."""
    sts = boto3.client("sts", region_name=os.environ.get("AWS_REGION", "us-east-1"))
    return sts.generate_presigned_url("get_caller_identity", ExpiresIn=120, HttpMethod="GET")


def ask_judge(chat: list[dict]) -> str:
    """The judge model's reply text, through the gateway (temperature 0).

    Raises:
        httpx.HTTPError: The gateway is unreachable, timed out or refused the call (budget, auth).
    """
    response = httpx.post(
        f"{os.environ['LITELLM_BASE_URL'].rstrip('/')}/v1/chat/completions",
        json={
            "model": os.environ["JUDGE_MODEL"],
            "messages": chat,
            "temperature": 0,
            "max_tokens": MAX_TOKENS,
        },
        headers={IDENTITY_HEADER: identity_url()},
        timeout=TIMEOUT,
    )
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"] or ""


def parse_verdict(reply: str, scale: list[dict]) -> dict:
    """The judge's JSON reply as an evaluator result, its score snapped to the nearest level of the scale.

    Raises:
        ValueError: The reply holds no JSON object with a numeric score.
    """
    found = JSON_OBJECT.search(reply)
    if not found:
        raise ValueError(f"no JSON object in the judge reply: {reply[:200]!r}")
    verdict = json.loads(found.group(0))
    score = float(verdict["score"])
    level = min(scale, key=lambda item: abs(float(item["value"]) - score))
    explanation = str(verdict.get("explanation") or level["definition"])
    return {"label": level["label"], "value": float(level["value"]), "explanation": explanation}


def error(code: str, message: str) -> dict:
    log.warning("%s: %s", code, message)
    return {"errorCode": code, "errorMessage": message[:500]}


def judge(event: dict, answer: str, records: list[dict], trace_id: str | None) -> dict:
    """Score one answer with the configured rubric; gateway and reply problems become evaluator errors."""
    try:
        rubric = load_rubric(os.environ.get("JUDGE_RUBRIC", "datastream_rubric"))
    except (OSError, KeyError, TypeError, yaml.YAMLError) as failure:
        return error("RUBRIC_INVALID", str(failure))
    chat = judge_messages(rubric, conversation(records, trace_id), answer, expected_response(event))
    try:
        return parse_verdict(ask_judge(chat) or ask_judge(chat), rubric["scale"])
    except httpx.HTTPStatusError as failure:
        return error("JUDGE_HTTP_ERROR", f"{failure.response.status_code} {failure.response.text}")
    except httpx.HTTPError as failure:
        return error("JUDGE_UNREACHABLE", f"{type(failure).__name__}: {failure}")
    except (ValueError, KeyError, TypeError, IndexError) as failure:
        return error("JUDGE_REPLY_INVALID", str(failure))


def handler(event: dict, _context: object) -> dict:
    """Lambda entry point: the evaluation input in, one rubric score (or an error) out."""
    records = (event.get("evaluationInput") or {}).get("sessionSpans") or []
    trace_id = ((event.get("evaluationTarget") or {}).get("traceIds") or [None])[0]
    answer = final_answer(records, trace_id)
    if not answer:
        return error("NO_ANSWER", "No assistant answer found for the target trace.")
    result = judge(event, answer, records, trace_id)
    log.info(json.dumps({"records": len(records), "trace": trace_id, "answer": answer[:200], "result": result}))
    return result
