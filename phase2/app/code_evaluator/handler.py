"""Code-based AgentCore evaluator (Phase 2, Task 6 Part C): "the answer states the exact numbers".

AgentCore Evaluations invokes this Lambda once per trace (one agent turn) with the session's spans; `trace_spans`
(shared/trace_spans.py, zipped next to this file) finds the answer of the outermost agent span (the orchestrator,
not a specialist). It scores that answer deterministically, no judge model:

- With ground truth (`bootcamp.py eval` attaches each golden item's expected answer): every number in the expected
  answer must appear in the agent's answer (1,201 and 1201 count as the same number). PASS = 1.0, FAIL = 0.0.
- Without ground truth (online evaluation of live traffic): the answer must not contain an unfilled placeholder such
  as "[count]" or "XX employees" (the classic sign of a model that invented a template instead of querying), and it
  must commit to something checkable: a number, or a plain refusal / "no data" statement. An answer that only
  promises to look ("Let me route this to our data specialist...") fails instead of passing for free; any other
  answer without numbers (a greeting, "Noted, you prefer bullet points") has nothing to check and is labelled N/A.

Contract: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/code-based-evaluators.html
"""

import json
import logging
import re

from trace_spans import expected_response, final_answer

log = logging.getLogger()
log.setLevel(logging.INFO)

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
PLACEHOLDER = re.compile(r"\[[a-z _]+\]|\bX{2,}\b|<[a-z _]+>", re.IGNORECASE)
NO_ANSWER_STATEMENT = re.compile(
    r"\b(?:can(?:no|['’])t|could(?: not|n['’]t)|unable|not able|(?:do|does|did)(?: not|n['’]t) have"
    r"|no (?:data|information|record)|not available|isn['’]t available|only (?:look up|cover)|read-only"
    r"|not allowed|won['’]t|will not|decline)\b|^Blocked by",
    re.IGNORECASE | re.MULTILINE,
)
"""A plain refusal or "no data" statement: a legitimate answer that carries no number."""
DEFERRAL = re.compile(
    r"\b(?:let me(?! know\b)|one moment|i['’]ll (?:check|look|route|query|ask|get|find|pull|fetch)"
    r"|i will (?:check|look|route|query|ask|get|find|pull|fetch)|rout(?:e|ing) (?:this|your))\b",
    re.IGNORECASE,
)
"""An answer that promises to fetch data instead of giving it (the routing-only non-answer).

"Let me know" is an invitation, not a promise to look something up, so "Noted ... just let me know" stays N/A."""


def numbers(text: str) -> set[str]:
    """Every number in `text`, normalised ("1,201" -> "1201", "5,000,000.00" -> "5000000")."""
    found = {match.replace(",", "") for match in NUMBER.findall(text)}
    return {value.rstrip("0").rstrip(".") if "." in value else value for value in found}


def score(answer: str, expected: str) -> dict:
    """PASS/FAIL with an explanation (ground-truth numbers when available, `score_without_reference` otherwise)."""
    if expected:
        missing = sorted(numbers(expected) - numbers(answer))
        if missing:
            return verdict(False, f"Missing the expected number(s) {', '.join(missing)}.")
        return verdict(True, "Every number in the expected answer appears in the agent's answer.")
    return score_without_reference(answer)


def score_without_reference(answer: str) -> dict:
    """Live traffic: no placeholders, and either a number or a plain refusal / "no data" statement."""
    placeholder = PLACEHOLDER.search(answer)
    if placeholder:
        return verdict(False, f"Unfilled placeholder {placeholder.group(0)!r} instead of a real value.")
    if numbers(answer):
        return verdict(True, "No ground truth for this turn; states numbers and no unfilled placeholders.")
    if NO_ANSWER_STATEMENT.search(answer):
        return verdict(True, "No ground truth for this turn; a plain refusal or no-data answer.")
    if DEFERRAL.search(answer):
        return verdict(False, "Promises to look the data up but gives no number: the answer commits to nothing.")
    return {"label": "N/A", "value": 1.0, "explanation": "No numbers and no data promised: nothing to check."}


def verdict(passed: bool, explanation: str) -> dict:
    return {"label": "PASS" if passed else "FAIL", "value": 1.0 if passed else 0.0, "explanation": explanation}


def handler(event: dict, _context: object) -> dict:
    """Lambda entry point: the evaluation input in, one score (or an error) out."""
    records = (event.get("evaluationInput") or {}).get("sessionSpans") or []
    trace_ids = (event.get("evaluationTarget") or {}).get("traceIds") or [None]
    answer = final_answer(records, trace_ids[0])
    log.info(json.dumps({"records": len(records), "trace": trace_ids[0], "answer": answer[:200]}))
    if not answer:
        return {"errorCode": "NO_ANSWER", "errorMessage": "No assistant answer found for the target trace."}
    return score(answer, expected_response(event))
