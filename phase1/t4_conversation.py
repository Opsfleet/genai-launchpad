"""Task 4: keep long chats affordable with SummarizingConversationManager (old turns become a summary)."""

from strands import Agent
from strands.agent.conversation_manager import SummarizingConversationManager
from strands.session import FileSessionManager

from common import SESSIONS_DIR, SYSTEM_PROMPT, ContextPrinter, make_mcp_client, make_model, run, session_id

CONTEXT_WINDOW_TOKENS = 1000
"""Deliberately tiny (real models take ~200k), tuned on the suggested model: the system prompt and tool description
take ~340 tokens, the department table brings the prompt to ~650, and a message or two later it passes the 0.7
threshold (700 tokens). A short summary drops it back to ~400, leaving room for several messages before the next
summary. Another model's tokenizer may need another value."""

SUMMARY_PROMPT = """Summarize the conversation so far as short bullet points in the third person.
Keep every fact the user stated about themselves (name, role, preferences such as a favorite color).
Give each tool result one short line: never copy a table or a list of rows. Do not address the user."""
"""Strands' default summary lists topics and tool results and may drop personal facts; this one keeps them."""


def build_conversation_manager() -> SummarizingConversationManager:
    """Summarize most (80%) of the older messages once the context is 70% full; keep the 2 most recent verbatim."""
    return SummarizingConversationManager(
        summary_ratio=0.8,
        preserve_recent_messages=2,
        summarization_system_prompt=SUMMARY_PROMPT,
        proactive_compression={"compression_threshold": 0.7},
    )


if __name__ == "__main__":
    session_manager = FileSessionManager(session_id=session_id("summary_session"), storage_dir=str(SESSIONS_DIR))
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
