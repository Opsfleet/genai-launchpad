"""Span tree rendering, tool inputs, evaluation score lines and the up-duration estimates."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import observe, progress  # noqa: E402


def span(span_id: str, parent: str, name: str, start: int, **extra: str) -> dict[str, str]:
    return {
        "traceId": "t1",
        "spanId": span_id,
        "parentSpanId": parent,
        "name": name,
        "startTimeUnixNano": str(start),
        "durationNano": "1000000000",
        **extra,
    }


def test_tree_nests_children_and_collapses_repeated_leaves() -> None:
    spans = [
        span("a", "platform", "POST /invocations", 1),
        span("b", "a", "invoke_agent Executive Assistant", 2, input_tokens="161", output_tokens="10"),
        span("c", "a", "CreateEvent", 3),
        span("d", "a", "CreateEvent", 4),
        span("e", "b", "chat", 5),
    ]
    assert observe.render_tree(spans) == [
        "trace t1",
        "  POST /invocations  1.00s",
        "    invoke_agent Executive Assistant  1.00s  tokens 161 in/10 out",
        "      chat  1.00s",
        "    CreateEvent x2  2.00s",
    ]


def test_session_id_is_validated_before_querying() -> None:
    with pytest.raises(RuntimeError, match="Not a session id"):
        observe.session_spans(None, "svc", 'x" or 1=1', 1)


def test_score_lines() -> None:
    row = {"@timestamp": "2026-10-07 05:31:50.020", "evaluator": "Builtin.Correctness", "score": "1.0", "label": "OK"}
    header, line = observe.render_scores([row])
    assert header.startswith("time (UTC)") and line.startswith("2026-10-07 05:31:50  Builtin.Correctness")


def test_service_name() -> None:
    assert observe.service_name("alice") == "awsworkshop_alice_agent.DEFAULT"


@pytest.mark.parametrize(("current", "target", "minutes"), [(-1, 0, 6.0), (2, 4, 16.5), (7, 7, 1.0)])
def test_up_minutes(current: int, target: int, minutes: float) -> None:
    assert progress.up_minutes(current, target) == minutes
