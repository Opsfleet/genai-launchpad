"""Task 2: give the agent real data by connecting it to the MCP server's `query_db` tool."""

from strands import Agent
from strands.tools.mcp import MCPClient

from common import SYSTEM_PROMPT, make_mcp_client, make_model, run


def build_agent(mcp_client: MCPClient) -> Agent:
    """The data engineer: the agent gets every tool the (open) MCP client's server exposes."""
    return Agent(
        name="Data Engineer",
        model=make_model(),
        system_prompt=SYSTEM_PROMPT,
        tools=mcp_client.list_tools_sync(),
    )


if __name__ == "__main__":
    with make_mcp_client() as mcp_client:
        run(build_agent(mcp_client))
