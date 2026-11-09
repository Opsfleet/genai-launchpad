"""Task 4 starter: summarize older turns so long chats stay small (and cheap) without forgetting.

Fill in the TODO, then run:  uv run bootcamp.py phase1 t4 --starter
Reference solution:           phase1/t4_conversation.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strands import Agent  # noqa: E402
from strands.session import FileSessionManager  # noqa: E402

from common import (  # noqa: E402
    SESSIONS_DIR,
    SYSTEM_PROMPT,
    ContextPrinter,
    make_mcp_client,
    make_model,
    run,
    session_id,
)

CONTEXT_WINDOW_TOKENS = 1000
"""Deliberately tiny (real models take ~200k), tuned on the suggested model: the system prompt and tool description
take ~340 tokens, the department table brings the prompt to ~650, and a message or two later it passes the 0.7
threshold (700 tokens). A short summary drops it back to ~400, leaving room for several messages before the next
summary. Another model's tokenizer may need another value."""


def build_conversation_manager():
    """TODO: return a conversation manager that summarizes older messages and keeps the 2 most recent verbatim.

    Give it a summarization prompt that keeps the facts the user told you (like a favorite color).
    """
    raise NotImplementedError("TODO: create the conversation manager in phase1/starter/t4_conversation.py")


if __name__ == "__main__":
    session_manager = FileSessionManager(
        session_id=session_id("summary_session_starter"), storage_dir=str(SESSIONS_DIR)
    )
    conversation_manager = build_conversation_manager()
    model = make_model()
    model.update_config(context_window_limit=CONTEXT_WINDOW_TOKENS)
    with make_mcp_client() as mcp_client:
        agent = Agent(
            name="Data Engineer",
            model=model,
            system_prompt=SYSTEM_PROMPT,
            tools=mcp_client.list_tools_sync(),
            session_manager=session_manager,
            conversation_manager=conversation_manager,
            hooks=[ContextPrinter(conversation_manager)],
        )
        run(agent)
