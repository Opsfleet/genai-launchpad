"""Task 8 starter: give the agent skills, SKILL.md house rules that it loads only when a question needs them.

Fill in the TODOs, then run:  uv run bootcamp.py phase1 t8 --starter "Give me the headcount report"
Reference solution:            phase1/t8_skills.py and phase1/skills/
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strands import Agent  # noqa: E402
from strands.tools.mcp import MCPClient  # noqa: E402

from common import SYSTEM_PROMPT, make_mcp_client, make_model, require_done, run  # noqa: E402, F401

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
HEADCOUNT_SKILL = SKILLS_DIR / "headcount-report" / "SKILL.md"


def build_agent(mcp_client: MCPClient) -> Agent:
    """TODO 2: return the "Data Engineer" agent with the MCP tools and an AgentSkills plugin for SKILLS_DIR.

    AgentSkills lives in strands.vended_plugins.skills.
    """
    raise NotImplementedError("TODO 2: build the agent in phase1/starter/t8_skills.py (hint: plugins=[...])")


if __name__ == "__main__":
    require_done(HEADCOUNT_SKILL, "TODO 1")
    with make_mcp_client() as mcp_client:
        run(build_agent(mcp_client))
