"""Task 7: agents as tools. An orchestrator routes to a data specialist and a weather specialist.

Every tool call prints as `[tool] name: input` (the orchestrator's data_agent / weather_agent calls and the
specialists' own query_db / get_us_forecast calls). A specialist that fails or answers with nothing reports
"The <name> specialist failed: ..." so the orchestrator never fills the gap with guesses. If the model still ends
with an empty answer, the last specialist result is printed instead.
"""

from strands import Agent, tool

from common import answer_or_fallback, ask_specialist, make_mcp_client, make_model, run
from hooks import ApprovalHook
from nws_weather import WEATHER_PROMPT, get_us_forecast

ORCHESTRATOR_PROMPT = """You are CEO Alice's executive assistant at DataStream Corp.

Route queries to specialists:
- Database queries, employee counts, department stats -> use data_agent
- Weather forecasts, temperature, weather conditions (any location) -> use weather_agent. It covers US
  locations only; when it says it can only look up US weather, pass that sentence on to Alice unchanged.
- Simple company questions -> answer directly

After the specialists reply, ALWAYS finish with a final answer for Alice that combines every specialist result
in your own words. Never end your turn with an empty message. If a specialist reports that it failed, tell Alice
which part could not be answered; never invent numbers or use placeholders such as [count].

DataStream Corp is a technology company with Sales, HR, and Engineering departments."""


SPECIALIST_FAILED = "The {specialist} specialist failed: {reason}. No data is available from it for this question."
"""Returned to the orchestrator instead of "" so a failed specialist is reported, never filled in with guesses."""


def consult(specialist: Agent, query: str, results: list[str], name: str) -> str:
    """Ask a specialist via `ask_specialist`; an exception or empty answer becomes an explicit failure message.

    Args:
        specialist: The specialist agent behind an orchestrator tool.
        query: The question the orchestrator routed to it.
        results: Shared list of specialist answers for this turn.
        name: Short specialist name for the failure message, e.g. "data".

    Returns:
        The specialist's answer, or "The <name> specialist failed: ..." so the orchestrator never guesses.
    """
    try:
        answer = ask_specialist(specialist, query, results).strip()
        reason = "it returned an empty answer"
    except Exception as error:
        answer, reason = "", f"{type(error).__name__}: {error}"
    if not answer:
        answer = SPECIALIST_FAILED.format(specialist=name, reason=reason)
        results.append(answer)
    return answer


def build_orchestrator(db_tools: list, specialist_results: list[str]) -> Agent:
    """Orchestrator whose two tools are specialist agents; their answers are appended to `specialist_results`."""

    @tool
    def data_agent(query: str) -> str:
        """Query and analyze the DataStream Corp database: employee counts, department statistics, any SQL question.

        Args:
            query: A database or data analysis question.
        """
        specialist = Agent(
            model=make_model(),
            system_prompt="You are a data specialist. Query the database to answer questions.",
            tools=db_tools,
            hooks=[ApprovalHook()],
            callback_handler=None,
        )
        return consult(specialist, query, specialist_results, "data")

    @tool
    def weather_agent(query: str) -> str:
        """Get the weather forecast for a US location (National Weather Service); says so for non-US places.

        Args:
            query: A weather-related question, including the place.
        """
        specialist = Agent(
            model=make_model(),
            system_prompt=WEATHER_PROMPT,
            tools=[get_us_forecast],
            callback_handler=None,
        )
        return consult(specialist, query, specialist_results, "weather")

    return Agent(
        name="Executive Assistant",
        model=make_model(),
        system_prompt=ORCHESTRATOR_PROMPT,
        tools=[data_agent, weather_agent],
    )


if __name__ == "__main__":
    results: list[str] = []
    with make_mcp_client() as mcp_client:
        orchestrator = build_orchestrator(mcp_client.list_tools_sync(), results)
        run(answer_or_fallback(orchestrator, results), watch=orchestrator)
