"""Task 7 specialists report failures explicitly instead of handing the orchestrator an empty string."""

import sys
from pathlib import Path

import pytest

PHASE1 = Path(__file__).resolve().parents[1] / "phase1"
sys.path.insert(0, str(PHASE1))
_excepthook = sys.excepthook
import t7_agents_as_tools as solution  # noqa: E402

sys.excepthook = _excepthook
sys.path.insert(0, str(PHASE1 / "starter"))
sys.modules.pop("t7_agents_as_tools")
import t7_agents_as_tools as starter  # noqa: E402

sys.path[:] = [entry for entry in sys.path if not entry.startswith(str(PHASE1))]
for _name in [name for name, module in sys.modules.items() if str(PHASE1) in str(getattr(module, "__file__", ""))]:
    del sys.modules[_name]


def _answering(text: str):
    def ask(specialist: object, query: str, results: list[str]) -> str:
        results.append(text)
        return text

    return ask


def _failing(specialist: object, query: str, results: list[str]) -> str:
    raise RuntimeError("gateway 502")


@pytest.mark.parametrize("module", [solution, starter], ids=["solution", "starter"])
def test_answer_passes_through(monkeypatch: pytest.MonkeyPatch, module) -> None:
    monkeypatch.setattr(module, "ask_specialist", _answering("Sales has 360 employees."))
    results: list[str] = []
    assert module.consult(object(), "q", results, "data") == "Sales has 360 employees."
    assert results == ["Sales has 360 employees."]


@pytest.mark.parametrize("module", [solution, starter], ids=["solution", "starter"])
def test_empty_answer_becomes_explicit_failure(monkeypatch: pytest.MonkeyPatch, module) -> None:
    monkeypatch.setattr(module, "ask_specialist", _answering("  "))
    results: list[str] = []
    answer = module.consult(object(), "q", results, "data")
    assert answer.startswith("The data specialist failed: it returned an empty answer")
    assert results[-1] == answer


@pytest.mark.parametrize("module", [solution, starter], ids=["solution", "starter"])
def test_exception_becomes_explicit_failure(monkeypatch: pytest.MonkeyPatch, module) -> None:
    monkeypatch.setattr(module, "ask_specialist", _failing)
    results: list[str] = []
    answer = module.consult(object(), "q", results, "weather")
    assert answer.startswith("The weather specialist failed: RuntimeError: gateway 502")
    assert results == [answer]


def test_orchestrator_prompt_forbids_placeholders() -> None:
    assert "never invent numbers" in solution.ORCHESTRATOR_PROMPT
    assert "never invent numbers" in starter.ORCHESTRATOR_PROMPT


@pytest.mark.parametrize("module", [solution, starter], ids=["solution", "starter"])
def test_weather_specialist_is_us_only(module) -> None:
    assert "US locations only" in module.WEATHER_PROMPT
    assert module.get_us_forecast.tool_name == "get_us_forecast"
    assert "pass that sentence on to Alice unchanged" in module.ORCHESTRATOR_PROMPT


def test_phase2_uses_the_shared_weather_tool_behind_the_gateway() -> None:
    agent_source = (PHASE1.parent / "phase2" / "app" / "agent" / "agent.py").read_text(encoding="utf-8")
    lambda_source = (PHASE1.parent / "phase2" / "app" / "weather_lambda" / "handler.py").read_text(encoding="utf-8")
    assert "tools=search_tools(gateway, WEATHER_TOOLS" in agent_source
    assert "system_prompt=nws_weather.WEATHER_PROMPT" in agent_source
    assert "nws_weather.get_us_forecast(" in lambda_source
    assert "http_request" not in agent_source


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
