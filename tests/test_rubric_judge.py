"""Task 6 Part C: the `rubric_judge` code-based evaluator (LLM-as-a-judge through LiteLLM) and its wiring.

No AWS or gateway calls: the STS presign and the gateway's HTTP reply are stubbed.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))
import trace_spans  # noqa: E402
from bootcamp_cli import build, checks  # noqa: E402

TASK6_TF = ROOT / "terraform" / "participant" / "task6_evaluations.tf"
RUBRICS = ROOT / "phase2" / "evals" / "evaluators.yaml"


def load(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"{path.parent.name}_handler", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


judge = load(ROOT / "phase2" / "app" / "rubric_judge" / "handler.py")


def body(side: str, role: str, blocks: list[dict]) -> dict:
    """An OTel log body as Strands writes it: content blocks as a JSON string."""
    return {side: {"messages": [{"role": role, "content": {"content": json.dumps(blocks)}}]}}


def span(name: str, span_id: str, start_ns: int, bodies: list[dict]) -> dict:
    return {"name": name, "traceId": "t1", "spanId": span_id, "startTimeUnixNano": start_ns,
            "endTimeUnixNano": start_ns + 100, "span_events": [{"body": b} for b in bodies]}  # fmt: skip


SQL = {"toolUse": {"name": "query_database", "input": {"sql": "SELECT COUNT(*) FROM employees"}, "toolUseId": "u1"}}
RECORDS = [
    span("invoke_agent Executive Assistant", "root", 1, [
        body("input", "user", [{"text": "How many employees do we have?"}]),
        body("output", "assistant", [{"text": "DataStream Corp has 1,201 employees."}]),
    ]),
    span("execute_tool query_database", "tool", 2, [
        body("input", "assistant", [SQL]),
        body("output", "user", [{"toolResult": {"toolUseId": "u1", "content": [{"text": '[{"n": 1201}]'}]}}]),
    ]),
]  # fmt: skip


def event(expected: str = "") -> dict:
    references = [{"expectedResponse": {"text": expected}}] if expected else []
    return {"evaluationInput": {"sessionSpans": RECORDS}, "evaluationTarget": {"traceIds": ["t1"]},
            "evaluationReferenceInputs": references}  # fmt: skip


class Gateway:
    """Stands in for httpx.post: records the request, answers with a scripted reply or raises."""

    def __init__(self, reply: str = "", status: int = 200, raises: Exception | None = None) -> None:
        self.reply, self.status, self.raises, self.calls = reply, status, raises, []

    def __call__(self, url: str, json: dict, headers: dict, timeout: httpx.Timeout) -> httpx.Response:
        self.calls.append({"url": url, "json": json, "headers": headers, "timeout": timeout})
        if self.raises:
            raise self.raises
        payload = {"choices": [{"message": {"content": self.reply}}]} if self.status == 200 else {"error": "budget"}
        return httpx.Response(self.status, json=payload, request=httpx.Request("POST", url))


@pytest.fixture
def gateway(monkeypatch: pytest.MonkeyPatch):
    def install(**kwargs) -> Gateway:
        fake = Gateway(**kwargs)
        monkeypatch.setattr(judge.httpx, "post", fake)
        return fake

    monkeypatch.setenv("LITELLM_BASE_URL", "https://llm.example/")
    monkeypatch.setenv("JUDGE_MODEL", "judge-model")
    monkeypatch.delenv("JUDGE_RUBRIC", raising=False)
    monkeypatch.setattr(judge, "RUBRIC_FILE", RUBRICS)
    monkeypatch.setattr(judge, "identity_url", lambda: "https://sts.amazonaws.com/?Action=GetCallerIdentity")
    return install


def test_conversation_lists_question_tool_calls_results_and_answer() -> None:
    text = trace_spans.conversation(RECORDS, "t1")
    assert text.splitlines() == [
        "user: How many employees do we have?",
        "assistant: DataStream Corp has 1,201 employees.",
        'assistant calls tool query_database({"sql": "SELECT COUNT(*) FROM employees"})',
        'tool result: [{"n": 1201}]',
    ]
    assert trace_spans.question(RECORDS, "t1") == "How many employees do we have?"
    assert trace_spans.conversation(RECORDS, "other") == ""


def test_the_judge_is_asked_through_the_gateway_keylessly(gateway) -> None:
    fake = gateway(reply='{"score": 1, "label": "Grounded", "explanation": "1201 comes from the query."}')
    result = judge.handler(event(), None)
    assert result == {"label": "Grounded", "value": 1.0, "explanation": "1201 comes from the query."}
    call = fake.calls[0]
    assert call["url"] == "https://llm.example/v1/chat/completions"
    assert call["headers"] == {judge.IDENTITY_HEADER: "https://sts.amazonaws.com/?Action=GetCallerIdentity"}
    assert call["json"]["model"] == "judge-model" and call["json"]["temperature"] == 0
    assert call["timeout"].read and call["timeout"].connect


def test_the_prompt_carries_the_rubric_the_turn_and_the_scale(gateway) -> None:
    fake = gateway(reply='{"score": 0, "label": "Ungrounded", "explanation": "x"}')
    judge.handler(event(), None)
    system, user = (message["content"] for message in fake.calls[0]["json"]["messages"])
    assert "Partly grounded" in system and '"score"' in system
    assert "SELECT COUNT(*) FROM employees" in user and "DataStream Corp has 1,201 employees." in user
    assert "{context}" not in user and "{assistant_turn}" not in user


@pytest.mark.parametrize(
    ("reply", "value", "label"),
    [
        ('```json\n{"score": 0.6, "label": "whatever", "explanation": "rounded"}\n```', 0.5, "Partly grounded"),
        ('Verdict: {"score": "0.1", "explanation": "invented"}', 0.0, "Ungrounded"),
        ('{"score": 7, "explanation": "out of range"}', 1.0, "Grounded"),
    ],
)
def test_scores_snap_to_the_rubric_scale(gateway, reply: str, value: float, label: str) -> None:
    gateway(reply=reply)
    result = judge.handler(event(), None)
    assert (result["value"], result["label"]) == (value, label)


@pytest.mark.parametrize(
    ("kwargs", "code"),
    [
        ({"status": 429}, "JUDGE_HTTP_ERROR"),
        ({"raises": httpx.ReadTimeout("slow")}, "JUDGE_UNREACHABLE"),
        ({"reply": "I think it is fine."}, "JUDGE_REPLY_INVALID"),
        ({"reply": '{"label": "Grounded"}'}, "JUDGE_REPLY_INVALID"),
    ],
)
def test_gateway_and_reply_problems_are_evaluator_errors(gateway, kwargs: dict, code: str) -> None:
    gateway(**kwargs)
    result = judge.handler(event(), None)
    assert result["errorCode"] == code and result["errorMessage"]


def test_unknown_rubric_and_missing_answer_are_errors(gateway, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = gateway(reply="{}")
    monkeypatch.setenv("JUDGE_RUBRIC", "nope")
    assert judge.handler(event(), None)["errorCode"] == "RUBRIC_INVALID"
    empty = {"evaluationInput": {"sessionSpans": []}, "evaluationTarget": {"traceIds": ["t1"]}}
    assert judge.handler(empty, None)["errorCode"] == "NO_ANSWER"
    assert fake.calls == []


def test_ground_truth_fills_expected_response(gateway) -> None:
    rubric = {"instructions": "Expected: {expected_response}\nGot: {assistant_turn}", "scale": []}
    with_truth = judge.judge_messages(rubric, "ctx", "481", "Engineering has 481 employees.")
    without = judge.judge_messages(rubric, "ctx", "481", "")
    assert "Expected: Engineering has 481 employees." in with_truth[1]["content"]
    assert judge.NO_REFERENCE in without[1]["content"]


def test_shipped_rubrics_use_only_known_placeholders() -> None:
    import yaml

    entries = yaml.safe_load(RUBRICS.read_text(encoding="utf-8"))
    assert entries and len({entry["name"] for entry in entries}) == len(entries)
    for entry in entries:
        used = set(re.findall(r"\{([a-z_]+)\}", entry["instructions"]))
        assert used and used <= {"context", "assistant_turn", "expected_response"}, used
        assert all({"value", "label", "definition"} <= set(level) for level in entry["scale"])
        assert all(0 <= float(level["value"]) <= 1 for level in entry["scale"])
    assert judge.load_rubric("datastream_rubric", RUBRICS)["name"] == "datastream_rubric"


def test_the_lambda_zip_packages_the_rubrics() -> None:
    assert RUBRICS in build.APP_EXTRA_FILES["rubric_judge"]
    assert 'build_app("rubric_judge")' in (ROOT / "bootcamp.py").read_text(encoding="utf-8")


def test_terraform_registers_both_code_evaluators_online_and_no_managed_judge() -> None:
    terraform = TASK6_TF.read_text(encoding="utf-8")
    assert re.search(r"rubric_judge = \{\s*app\s*= \"rubric_judge\"", terraform)
    assert all(key in terraform for key in ("LITELLM_BASE_URL", "JUDGE_MODEL", "JUDGE_RUBRIC"))
    assert "aws_bedrockagentcore_evaluator.code : evaluator.evaluator_id" in terraform
    participant_tf = "".join(path.read_text() for path in TASK6_TF.parent.glob("*.tf"))
    assert "llm_as_a_judge" not in participant_tf and "bedrock_evaluator_model_config" not in participant_tf


def test_the_stage6_probe_is_a_readable_turn() -> None:
    records = checks.judge_probe_event()["evaluationInput"]["sessionSpans"]
    assert trace_spans.final_answer(records, "probe") == checks.JUDGE_PROBE_ANSWER
    assert trace_spans.question(records, "probe") == checks.JUDGE_PROBE_QUESTION
    assert checks.JUDGE_PROBE_SQL in trace_spans.conversation(records, "probe")


class FakeLambda:
    """Lambda client stand-in: the rubric_judge's JUDGE_RUBRIC and a scripted verdict."""

    def __init__(self, rubric: str, verdict: dict) -> None:
        self.rubric, self.verdict, self.invoked = rubric, verdict, []

    def client(self, _service: str) -> "FakeLambda":
        return self

    def get_function_configuration(self, FunctionName: str) -> dict:  # noqa: N803
        return {"Environment": {"Variables": {"JUDGE_RUBRIC": self.rubric}}}

    def invoke(self, FunctionName: str, Payload: bytes) -> dict:  # noqa: N803
        self.invoked.append(FunctionName)
        return {"Payload": SimpleNamespace(read=lambda: json.dumps(self.verdict).encode())}


@pytest.mark.parametrize(
    ("rubric", "verdict", "status"),
    [
        ("datastream_rubric", {}, "SKIP"),
        ("concise_rubric", {"label": "Concise", "value": 1.0, "explanation": "short"}, "PASS"),
        ("concise_rubric", {"errorCode": "RUBRIC_INVALID", "errorMessage": "not found"}, "FAIL"),
    ],
)
def test_own_rubric_challenge(rubric: str, verdict: dict, status: str) -> None:
    fake = FakeLambda(rubric, verdict)
    result, detail = checks.challenge_own_rubric({"participant": "bob"}, fake)
    assert result == status
    assert fake.invoked == ([] if status == "SKIP" else ["awsworkshop-bob-rubric-judge"])


def test_an_empty_judge_reply_is_asked_once_more(gateway) -> None:
    fake = gateway(reply="")
    assert judge.handler(event(), None)["errorCode"] == "JUDGE_REPLY_INVALID"
    assert len(fake.calls) == 2
