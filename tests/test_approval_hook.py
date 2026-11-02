"""Phase 1 ApprovalHook: prompts for real writes only (no false positives on names like `updated_at`)."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "phase1"))
from hooks import ApprovalHook  # noqa: E402


class FakeEvent:
    """The parts of BeforeToolCallEvent the hook uses; records interrupts and answers with `answer`."""

    def __init__(self, query: str, answer: str = "n", name: str = "query_db") -> None:
        self.tool_use = {"name": name, "input": {"query": query}}
        self.answer = answer
        self.interrupted = False
        self.cancel_tool: str | bool = False

    def interrupt(self, name: str, reason: dict) -> str:
        self.interrupted = True
        return self.answer


@pytest.mark.parametrize("query", ["SELECT updated_at FROM employees", "WITH e AS (SELECT 1) SELECT * FROM e"])
def test_reads_run_without_prompt(query: str) -> None:
    event = FakeEvent(query)
    ApprovalHook().approve(event)
    assert not event.interrupted and not event.cancel_tool


@pytest.mark.parametrize("query", ["/* c */ DELETE FROM employees", "REPLACE INTO departments VALUES (1)"])
def test_writes_prompt_and_deny(query: str) -> None:
    event = FakeEvent(query, answer="n")
    ApprovalHook().approve(event)
    assert event.interrupted and event.cancel_tool


def test_approved_write_runs() -> None:
    event = FakeEvent("DROP TABLE x", answer="y")
    ApprovalHook().approve(event)
    assert event.interrupted and not event.cancel_tool


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
