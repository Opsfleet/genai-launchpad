"""Task 6: force the agent to answer with a typed Pydantic object instead of free text."""

from pydantic import BaseModel, Field, model_validator
from strands import Agent

from common import SYSTEM_PROMPT, make_mcp_client, make_model, run
from hooks import ApprovalHook


class Department(BaseModel):
    """One department row of the report."""

    name: str = Field(description="Department name, as in the departments table")
    active_employees: int = Field(description="Employees with status = 'active' in this department (0 if none)")


class DepartmentReport(BaseModel):
    """Department report for DataStream Corp."""

    title: str = Field(description="Report title")
    summary: str = Field(description="Executive summary: only facts from the query results, no reasons or plans")
    departments: list[Department] = Field(
        description="Every department in the departments table, including those with no active employees"
    )
    total_employees: int = Field(description="Active employees in the whole company")

    @model_validator(mode="after")
    def total_matches_departments(self) -> "DepartmentReport":
        """Reject a total that is not the sum of the departments; Strands sends the error back so the model retries."""
        counted = sum(department.active_employees for department in self.departments)
        if counted != self.total_employees:
            raise ValueError(f"total_employees is {self.total_employees}, but the departments add up to {counted}")
        return self


def make_responder(agent: Agent):
    def respond(prompt: str) -> DepartmentReport:
        report = agent(prompt, structured_output_model=DepartmentReport).structured_output
        print(report.model_dump_json(indent=2))
        return report

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
