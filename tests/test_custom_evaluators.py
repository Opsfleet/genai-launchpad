"""Task 6 Part C: custom evaluators (`exact_numbers` Lambda, `--evaluators`) and the offline A/B (`--variants`).

No AWS calls: the Lambda handler and the prompt variants are imported from their source folders.
"""

import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "shared"))
from bootcamp_cli import ab_compare, evaluate, evaluators  # noqa: E402
from bootcamp_cli.golden import GoldenItem  # noqa: E402

ITEM = GoldenItem("eng", "How many in Engineering?", "Engineering has 481 employees.")
TOOL_ITEM = GoldenItem("sales", "Sales headcount?", "360.", (), ("data_agent",))
CUSTOM = {
    "rubric_judge": "awsworkshop_bob_rubric_judge-AbCdE12345",
    "exact_numbers": "awsworkshop_bob_exact_numbers-Zz9Yy8Xx7W",
}


def load(path: Path) -> ModuleType:
    """Import a module from a file outside the package (Lambda handler, agent helper)."""
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


handler = load(ROOT / "phase2" / "app" / "code_evaluator" / "handler.py")
variants = load(ROOT / "phase2" / "app" / "agent" / "prompt_variants.py")


@pytest.mark.parametrize(
    ("spec", "expected"),
    [
        ("builtin", list(evaluators.BUILTIN)),
        ("custom", list(CUSTOM.values())),
        ("all", [*evaluators.BUILTIN, *CUSTOM.values()]),
        (
            "rubric_judge, Builtin.Helpfulness,rubric_judge",
            [CUSTOM["rubric_judge"], "Builtin.Helpfulness"],
        ),
    ],
)
def test_evaluator_specs_resolve_to_ids(spec: str, expected: list[str]) -> None:
    assert evaluators.resolve(spec, [ITEM], CUSTOM) == expected


def test_bad_evaluator_specs_explain_themselves() -> None:
    with pytest.raises(RuntimeError, match="stage 6"):
        evaluators.resolve("custom", [ITEM], {})
    with pytest.raises(RuntimeError, match="Unknown evaluator 'rubric'.*rubric_judge"):
        evaluators.resolve("rubric", [ITEM], CUSTOM)
    assert evaluators.resolve("builtin", [TOOL_ITEM], {})[-1] == evaluators.TRAJECTORY


def test_custom_scores_are_keyed_and_shown_by_name() -> None:
    result = evaluate.new_result(ITEM, "eval-1")
    event = {"attributes": {"session.id": result.session, "gen_ai.evaluation.name": "awsworkshop_bob_rubric_judge",
                            "gen_ai.evaluation.score.value": 0.5}}  # fmt: skip
    evaluate.attach_scores([result], [event], list(CUSTOM.values()))
    assert result.scores == {CUSTOM["rubric_judge"]: 0.5}
    assert evaluators.short_name(CUSTOM["exact_numbers"]) == "exact_numbers"
    assert evaluators.short_name("Builtin.Correctness") == "Correctness"


def span(name: str, span_id: str, start: int, text: str = "", trace: str = "t1") -> dict:
    """A span record as AgentCore passes it to a code-based evaluator (OTel log events under `span_events`)."""
    output = {"messages": [{"role": "assistant", "content": {"message": text, "finish_reason": "end_turn"}}]}
    events = [{"event_name": "strands.telemetry.tracer", "body": {"output": output}}] if text else []
    return {"name": name, "traceId": trace, "spanId": span_id, "startTimeUnixNano": start,
            "endTimeUnixNano": start + 10, "span_events": events}  # fmt: skip


def records(answer: str, trace: str = "t1") -> list[dict]:
    """The orchestrator span (started first, ended last), a specialist span and a model-call span."""
    return [
        span("invoke_agent Executive Assistant", "root", 1, answer, trace),
        span("invoke_agent Strands Agents", "child", 2, "data: 481 and 999", trace),
        span("chat", "call", 3, '[{"toolUse": {"name": "data_agent"}}]', trace),
    ]


def lambda_event(answer: str, expected: str = "") -> dict:
    references = [{"context": {"spanContext": {"traceId": "t1"}}, "expectedResponse": {"text": expected}}]
    return {"evaluationInput": {"sessionSpans": records(answer)}, "evaluationTarget": {"traceIds": ["t1"]},
            "evaluationReferenceInputs": references if expected else []}  # fmt: skip


@pytest.mark.parametrize(
    ("answer", "expected", "label"),
    [
        ("Engineering has **1,201** of them.", "DataStream Corp has 1201 employees.", "PASS"),
        ("The budget is $5,000,000.00.", "The Engineering budget is $5,000,000.", "PASS"),
        ("Engineering has about 500 employees.", "Engineering has 481 employees.", "FAIL"),
        ("Engineering has [count] employees.", "", "FAIL"),
        ("Engineering has 481 employees.", "", "PASS"),
        ("Let me route this to our data specialist to get the headcount.", "", "FAIL"),
        ("I can only look up US weather (National Weather Service).", "", "PASS"),
        ("I don't have revenue forecasts: the database holds no such data.", "", "PASS"),
        ("Blocked by the DataStream guardrail: this request looks like a prompt attack.", "", "PASS"),
        ("Noted: you prefer answers as bullet points.", "", "N/A"),
        ("Hi Alice! How can I help today?", "", "N/A"),
        ("Got it! I've noted your favorite color is saffron. If you need anything, just let me know!", "", "N/A"),
        ("One moment, I'll check with the data team.", "", "FAIL"),
    ],
)
def test_code_evaluator_scores_the_orchestrator_answer(answer: str, expected: str, label: str) -> None:
    verdict = handler.handler(lambda_event(answer, expected), None)
    assert verdict["label"] == label and verdict["value"] == (0.0 if label == "FAIL" else 1.0)


def test_code_evaluator_reports_a_missing_answer() -> None:
    event = {
        "evaluationInput": {"sessionSpans": records("481", trace="other")},
        "evaluationTarget": {"traceIds": ["t1"]},
    }
    assert handler.handler(event, None)["errorCode"] == "NO_ANSWER"


def test_prompt_variants_extend_the_system_prompt() -> None:
    agent = SimpleNamespace(system_prompt="You are an assistant.")
    assert variants.apply_variant(agent, "a") == "A" and agent.system_prompt == "You are an assistant."
    assert variants.apply_variant(agent, "b") == "B" and agent.system_prompt.endswith(variants.VARIANTS["B"])
    assert variants.variant_name("Z") == variants.CONTROL


def test_a_variant_is_sent_and_must_be_echoed(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict | None] = []

    def reply(_out: dict, _token: str, _prompt: str, _session: str, extra_payload: dict | None = None) -> dict:
        sent.append(extra_payload)
        return {"response": "481", "variant": "A"}

    monkeypatch.setattr(evaluate.agentcore, "invoke_agent_body", reply)
    control = evaluate.ask({}, "t", evaluate.new_result(ITEM, "u1", "A"))
    ignored = evaluate.ask({}, "t", evaluate.new_result(ITEM, "u2", "C"))
    assert sent == [{"variant": "A"}, {"variant": "C"}]
    assert control.error == "" and "applied variant A, not C" in ignored.error


def test_every_variant_asks_every_item(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(evaluate.users, "admin_password", lambda session, out, name: "pw")
    monkeypatch.setattr(evaluate.users, "sign_in", lambda session, out, name, password: name)
    monkeypatch.setattr(evaluate.users, "delete_user", lambda session, out, name: None)
    monkeypatch.setattr(evaluate, "ask", lambda out, token, result: result)
    results = evaluate.ask_all(None, {}, [ITEM, TOOL_ITEM], ["A", "B"])
    pairs = [(result.variant, result.id) for result in results]
    assert pairs == [("A", "eng"), ("A", "sales"), ("B", "eng"), ("B", "sales")]
    assert len({result.session for result in results}) == 4


def scored(item: GoldenItem, variant: str, score: float, answer: str) -> evaluate.Result:
    result = evaluate.new_result(item, "u", variant)
    result.answer, result.scores = answer, {"Builtin.Correctness": score, CUSTOM["rubric_judge"]: score}
    return result


def test_ab_report_compares_variants_side_by_side() -> None:
    results = [scored(ITEM, "A", 1.0, "Engineering has 481 employees, as of today in our database."),
               scored(TOOL_ITEM, "A", 0.5, "About 360."), scored(ITEM, "B", 1.0, "Engineering: 481."),
               scored(TOOL_ITEM, "B", 1.0, "Sales: 360.")]  # fmt: skip
    report = evaluate.Report("ds", "1", "job", "COMPLETED", "now", ["Builtin.Correctness", CUSTOM["rubric_judge"]],
                             results, variants=["A", "B"])  # fmt: skip
    lines = ab_compare.render(report)
    assert lines[0].startswith("A/B A vs B: dataset ds v1")
    assert "PASS RATE 1/2 (50%)" in lines and "PASS RATE 2/2 (100%)" in lines
    rows = {
        line.split()[0]: line.split() for line in lines[lines.index(next(x for x in lines if x.startswith("metric"))) :]
    }
    assert rows["pass"][-3:] == ["100%", "+50", "pts"]
    assert rows["rubric_judge"][1:] == ["0.75", "1.00", "+0.25"]
    assert ab_compare.lowest_pass_rate(report) == 0.5
    session = evaluate.session_metadata(results[2], ITEM, SimpleNamespace(name="ds", version="1"))
    assert session["metadata"]["variant"] == "B"
