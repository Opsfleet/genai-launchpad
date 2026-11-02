"""Task 6 starter: make the agent return a typed DepartmentReport instead of free text.

Fill in the TODOs, then run:  uv run bootcamp.py phase1 t6 --starter "Generate a department report"
Reference solution:            phase1/t6_structured_output.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pydantic import BaseModel, Field, model_validator  # noqa: E402, F401
from strands import Agent  # noqa: E402

from common import SYSTEM_PROMPT, make_mcp_client, make_model, run  # noqa: E402
from hooks import ApprovalHook  # noqa: E402


class DepartmentReport(BaseModel):
    """TODO 1: add fields title (str), summary (str), departments and total_employees (int).

    Make departments a list of a small `Department` model (name, active_employees), and add a model_validator that
    rejects a report whose total_employees is not the sum of its departments.
    """


def make_responder(agent: Agent):
    def respond(prompt: str) -> DepartmentReport:
        """TODO 2: call the agent with structured_output_model=DepartmentReport and print the JSON."""
        if not DepartmentReport.model_fields:
            raise NotImplementedError(
                "TODO 1: add the DepartmentReport fields in phase1/starter/t6_structured_output.py"
            )
        raise NotImplementedError("TODO 2: request structured output in make_responder()")

    return respond


if __name__ == "__main__":
    with make_mcp_client() as mcp_client:
        agent = Agent(
            name="Data Engineer",
            model=make_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=mcp_client.list_tools_sync(),
            hooks=[ApprovalHook()],
            callback_handler=None,
        )
        run(make_responder(agent), watch=agent)
