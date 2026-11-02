"""Task 5: a hook that pauses the agent for human approval before destructive SQL runs.

Which statements count as destructive is decided by shared/sql_guard.py: anything that is not a plain
SELECT / EXPLAIN / read-only WITH query needs approval.
"""

import sys
from pathlib import Path

from strands.hooks import BeforeToolCallEvent, HookProvider, HookRegistry

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))

import sql_guard  # noqa: E402


class ApprovalHook(HookProvider):
    """Interrupts any destructive `query_db` call until a human answers 'y'."""

    def register_hooks(self, registry: HookRegistry, **kwargs) -> None:
        """Run `approve` before every tool call."""
        registry.add_callback(BeforeToolCallEvent, self.approve)

    def approve(self, event: BeforeToolCallEvent) -> None:
        """Ask for approval when a `query_db` call may write; cancel the call unless the answer is 'y'."""
        if event.tool_use.get("name") != "query_db":
            return
        query = event.tool_use["input"].get("query", "")
        if sql_guard.is_write(query):
            approval = event.interrupt("approval-required", reason={"query": query})
            if str(approval).strip().lower() != "y":
                event.cancel_tool = "User denied permission to run this query"
