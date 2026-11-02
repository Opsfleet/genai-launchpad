"""Task 5: human-in-the-loop. ApprovalHook interrupts destructive SQL and we answer the interrupt.

In one-shot mode (prompt on the command line) destructive queries are auto-denied.
"""

from strands import Agent
from strands.agent.conversation_manager import SlidingWindowConversationManager

from common import APPROVAL_NOTE, ONE_SHOT, SYSTEM_PROMPT, make_mcp_client, make_model, run
from hooks import ApprovalHook


def ask_approval(query: str) -> str:
    if ONE_SHOT:
        print(f"\n[auto-deny] Denied destructive query: {query}")
        return "n"
    return input(f"\nApprove query '{query}'? (y/N): ")


def make_responder(agent: Agent):
    def respond(prompt: str):
        result = agent(prompt)
        while result.stop_reason == "interrupt":
            responses = [
                {"interruptResponse": {"interruptId": i.id, "response": ask_approval(i.reason["query"])}}
                for i in result.interrupts
                if i.name == "approval-required"
            ]
            result = agent(responses)
        return result

    return respond


if __name__ == "__main__":
    with make_mcp_client() as mcp_client:
        agent = Agent(
            name="Data Engineer",
            model=make_model(),
            system_prompt=SYSTEM_PROMPT + APPROVAL_NOTE,
            tools=mcp_client.list_tools_sync(),
            conversation_manager=SlidingWindowConversationManager(window_size=20),
            hooks=[ApprovalHook()],
        )
        run(make_responder(agent), watch=agent)
