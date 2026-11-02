"""Phase 1 runner helpers: tool-call lines, budget summary and the empty-answer fallback of Task 7."""

import sys
from pathlib import Path

import pytest

PHASE1 = str(Path(__file__).resolve().parents[1] / "phase1")
sys.path.insert(0, PHASE1)
_excepthook = sys.excepthook
import common  # noqa: E402

sys.excepthook = _excepthook
sys.path.remove(PHASE1)


class FakeToolEvent:
    """The parts of BeforeToolCallEvent the printer uses."""

    def __init__(self, name: str, tool_input: object, cancelled: bool = False) -> None:
        self.tool_use = {"name": name, "input": tool_input, "toolUseId": "call-1"}
        self.cancel_tool = "denied" if cancelled else False


def test_single_argument_tools_show_the_bare_value() -> None:
    assert common.describe_tool_input({"query": "SELECT *\n  FROM employees"}) == "SELECT * FROM employees"


def test_http_tools_show_method_and_url() -> None:
    assert common.describe_tool_input({"headers": {"A": "b"}, "method": "GET", "url": "https://x"}) == "GET https://x"


def test_multi_argument_tools_show_compact_json() -> None:
    assert common.describe_tool_input({"a": 1, "b": "c"}) == '{"a": 1, "b": "c"}'


def test_long_inputs_are_cut() -> None:
    text = common.describe_tool_input({"query": "x" * 500})
    assert len(text) == common.TOOL_INPUT_CHARS and text.endswith("...")


def test_printer_marks_cancelled_calls(capsys: pytest.CaptureFixture[str]) -> None:
    common.ToolCallPrinter().show(FakeToolEvent("query_db", {"query": "DELETE FROM t"}, cancelled=True))
    assert "[tool] query_db: DELETE FROM t (cancelled)" in capsys.readouterr().out


def test_resumed_call_prints_only_the_cancellation(capsys: pytest.CaptureFixture[str]) -> None:
    printer = common.ToolCallPrinter()
    printer.show(FakeToolEvent("query_db", {"query": "DELETE FROM t"}))
    printer.show(FakeToolEvent("query_db", {"query": "DELETE FROM t"}, cancelled=True))
    assert capsys.readouterr().out.split() == "[tool] query_db: DELETE FROM t [tool] query_db (cancelled)".split()


@pytest.mark.parametrize(("spend", "warned"), [(0.2, False), (0.74, False), (0.75, True), (1.0, True)])
def test_budget_warning_from_75_percent(spend: float, warned: bool) -> None:
    line = common.budget_line(spend, 1.0)
    assert line.startswith(f"[budget] ${spend:.6f} of $1 used")
    assert ("WARNING" in line) is warned


def test_budget_without_limit() -> None:
    assert "no budget limit" in common.budget_line(0.5, None)


def test_empty_answer_prints_last_specialist_result(capsys: pytest.CaptureFixture[str]) -> None:
    results: list[str] = []

    def orchestrator(prompt: str) -> str:
        results.extend(["first", "481 employees"])
        return ""

    common.answer_or_fallback(orchestrator, results)("q")
    out = capsys.readouterr().out
    assert "[fallback]" in out and "481 employees" in out


def test_non_empty_answer_has_no_fallback(capsys: pytest.CaptureFixture[str]) -> None:
    results = ["stale"]
    common.answer_or_fallback(lambda prompt: "done", results)("q")
    assert "[fallback]" not in capsys.readouterr().out
    assert results == []


def test_todo_found_behind_wrapping_exceptions() -> None:
    try:
        try:
            raise NotImplementedError("TODO 1")
        except NotImplementedError as todo:
            raise RuntimeError("event loop failed") from todo
    except RuntimeError as wrapped:
        assert str(common.find_todo(wrapped)) == "TODO 1"


def test_other_errors_are_not_todos() -> None:
    assert common.find_todo(ValueError("boom")) is None


class FakeAgent:
    """The part of a Strands Agent `quiet_tool_lines` touches."""

    def __init__(self, handler: object) -> None:
        self.callback_handler = handler


def test_default_handler_keeps_text_but_drops_its_tool_lines(capsys: pytest.CaptureFixture[str]) -> None:
    agent = FakeAgent(common.PrintingCallbackHandler())
    common.quiet_tool_lines(agent)
    tool_start = {"contentBlockStart": {"start": {"toolUse": {"name": "query_db"}}}}
    agent.callback_handler(event=tool_start)
    agent.callback_handler(data="481 people")
    assert capsys.readouterr().out == "481 people"


def test_custom_handlers_are_left_alone() -> None:
    agent = FakeAgent(print)
    common.quiet_tool_lines(agent)
    assert agent.callback_handler is print


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_reasoning_is_labeled_and_separated_from_the_answer(capsys: pytest.CaptureFixture[str]) -> None:
    printer = common.LabeledPrinter()
    printer(reasoningText="Let me think.")
    printer(reasoningText=" Done.")
    printer(data="It is four.", complete=True)
    out = capsys.readouterr().out
    assert "[reasoning] Let me think. Done." in out
    assert out.index("Done.") < out.index("It is four.") and "\n" in out[out.index("Done.") : out.index("It is four.")]
    assert out.count("[reasoning]") == 1


def test_reasoning_stays_one_block_across_empty_events(capsys: pytest.CaptureFixture[str]) -> None:
    printer = common.LabeledPrinter()
    printer(reasoningText="We need to find num")
    printer(event={"contentBlockDelta": {}})
    printer(reasoningText="ber of employees.")
    printer(event={"contentBlockStart": {"start": {"toolUse": {"name": "query_db"}}}})
    out = capsys.readouterr().out
    assert out.count("[reasoning]") == 1 and "find number of employees." in out
