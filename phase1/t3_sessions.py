"""Task 3: persist the conversation with FileSessionManager so the agent remembers you across restarts."""

from strands import Agent
from strands.session import FileSessionManager

from common import SESSIONS_DIR, SYSTEM_PROMPT, make_mcp_client, make_model, run, session_id

SESSION_ID = session_id("alice_session")
"""The starter file uses "alice_session_starter", so running the reference never fills in your starter's memory;
`--session NAME` picks another one."""


def build_session_manager() -> FileSessionManager:
    """Session SESSION_ID, stored as JSON files under SESSIONS_DIR."""
    return FileSessionManager(session_id=SESSION_ID, storage_dir=str(SESSIONS_DIR))


if __name__ == "__main__":
    session_manager = build_session_manager()
    with make_mcp_client() as mcp_client:
        agent = Agent(
            name="Data Engineer",
            model=make_model(),
            system_prompt=SYSTEM_PROMPT,
            tools=mcp_client.list_tools_sync(),
            session_manager=session_manager,
        )
        run(agent)
