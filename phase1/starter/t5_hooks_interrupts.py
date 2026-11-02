"""Task 5 starter: pause for human approval before destructive SQL, and answer the interrupt.

Fill in the TODOs, then run:  uv run bootcamp.py phase1 t5 --starter
Reference solution:            phase1/hooks.py and phase1/t5_hooks_interrupts.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strands import Agent  # noqa: E402
from strands.agent.conversation_manager import SlidingWindowConversationManager  # noqa: E402
from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry  # noqa: E402

from common import APPROVAL_NOTE, ONE_SHOT, SYSTEM_PROMPT, make_mcp_client, make_model, run  # noqa: E402

DESTRUCTIVE_KEYWORDS = ("DELETE", "UPDATE", "INSERT", "DROP", "ALTER", "TRUNCATE")


class ApprovalHook(HookProvider):
    """Interrupts any destructive `query_db` call until a human answers 'y'."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        registry.add_callback(BeforeToolCallEvent, self.approve)

    def approve(self, event: BeforeToolCallEvent) -> None:
        """TODO 1: for destructive query_db calls, event.interrupt(...) and cancel the tool unless the answer is 'y'."""
        raise NotImplementedError("TODO 1: implement ApprovalHook.approve in phase1/starter/t5_hooks_interrupts.py")


def ask_approval(query: str) -> str:
    if ONE_SHOT:
        print(f"\n[auto-deny] Denied destructive query: {query}")
        return "n"
    return input(f"\nApprove query '{query}'? (y/N): ")


def make_responder(agent: Agent):
    def respond(prompt: str):
        result = agent(prompt)
        # TODO 2: while result.stop_reason == "interrupt": answer each interrupt with ask_approval(...) and resume.
        if result.stop_reason == "interrupt":
            print("\n[TODO 2] The agent is waiting for approval: implement the interrupt loop in make_responder().")
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
