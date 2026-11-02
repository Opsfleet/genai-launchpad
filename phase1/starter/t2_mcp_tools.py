"""Task 2 starter: give the agent real data through your MCP server (phase1/starter/mcp_server.py).

Fill in the TODOs, then run:  uv run bootcamp.py phase1 t2 --starter "What tables are in the database?"
Reference solution:            phase1/t2_mcp_tools.py and phase1/mcp_server.py

In a --starter run, `make_mcp_client()` launches YOUR server (phase1/starter/mcp_server.py); the starters of
Tasks 3-8 keep using it.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strands import Agent  # noqa: E402
from strands.tools.mcp import MCPClient  # noqa: E402

from common import SYSTEM_PROMPT, make_mcp_client, make_model, run  # noqa: E402, F401


def build_agent(mcp_client: MCPClient) -> Agent:
    """TODO 3: return an Agent named "Data Engineer" with make_model(), SYSTEM_PROMPT and the server's tools."""
    raise NotImplementedError("TODO 3: build the agent in phase1/starter/t2_mcp_tools.py (hint: list_tools_sync())")


if __name__ == "__main__":
    with make_mcp_client() as client:
        run(build_agent(client))
