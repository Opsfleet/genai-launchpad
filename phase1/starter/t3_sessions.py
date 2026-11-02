"""Task 3 starter: persist the conversation so the agent remembers Alice across restarts.

Fill in the TODO, then run:  uv run bootcamp.py phase1 t3 --starter "My name is Alice Chen"
Reference solution:           phase1/t3_sessions.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strands import Agent  # noqa: E402

from common import SESSIONS_DIR, SYSTEM_PROMPT, make_mcp_client, make_model, run, session_id  # noqa: E402, F401

SESSION_ID = session_id("alice_session_starter")
"""Your own session, separate from the reference's "alice_session"; `--session NAME` picks another one."""


def build_session_manager():
    """TODO: return a session manager that stores session SESSION_ID under SESSIONS_DIR."""
    raise NotImplementedError("TODO: create the session manager in phase1/starter/t3_sessions.py")


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
