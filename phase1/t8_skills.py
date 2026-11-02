"""Task 8: agent skills. House rules live in SKILL.md files that the agent loads only when a question needs them.

At start-up only each skill's name and description reach the system prompt. When a question matches one, the model
calls the `skills` tool to load the full instructions (watch for `[tool] skills: ...`), then follows them.
"""

from strands import Agent
from strands.tools.mcp import MCPClient
from strands.vended_plugins.skills import AgentSkills

from common import PHASE1_DIR, SYSTEM_PROMPT, make_mcp_client, make_model, run

SKILLS_DIR = PHASE1_DIR / "skills"


def build_agent(mcp_client: MCPClient) -> Agent:
    """The data engineer with the database tools plus every skill under `SKILLS_DIR`."""
    return Agent(
        name="Data Engineer",
        model=make_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=mcp_client.list_tools_sync(),
        plugins=[AgentSkills(skills=SKILLS_DIR)],
    )


if __name__ == "__main__":
    with make_mcp_client() as mcp_client:
        run(build_agent(mcp_client))
