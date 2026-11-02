"""`bootcamp.py memory` and the Task 3 preference challenge, with fake AgentCore clients (no AWS)."""

import sys
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import checks, memory  # noqa: E402

MEMORY_ID = "awsworkshop_carol_memory-abc"
STRATEGIES = [
    {"name": "UserFacts", "type": "SEMANTIC", "strategyId": "facts-1",
     "namespaceTemplates": ["/strategies/{memoryStrategyId}/actors/{actorId}"]},
    {"name": "UserPreferences", "type": "USER_PREFERENCE", "strategyId": "prefs-1",
     "namespaces": ["/strategies/{memoryStrategyId}/actors/{actorId}"]},
    {"name": "SessionSummaries", "type": "SUMMARIZATION", "strategyId": "sum-1",
     "namespaceTemplates": ["/strategies/{memoryStrategyId}/actors/{actorId}/sessions/{sessionId}"]},
]  # fmt: skip


class FakeControl:
    """bedrock-agentcore-control with one memory."""

    def get_memory(self, memoryId: str) -> dict:  # noqa: N803 - boto3 keyword
        return {"memory": {"id": memoryId, "strategies": STRATEGIES}}


class FakeData:
    """bedrock-agentcore: records keyed by namespace path, two sessions with events."""

    def __init__(self, records: dict[str, list[str]]) -> None:
        self.records = records

    def list_memory_records(self, memoryId: str, namespacePath: str, maxResults: int) -> dict:  # noqa: N803
        texts = self.records.get(namespacePath, [])[:maxResults]
        return {"memoryRecordSummaries": [{"content": {"text": text}} for text in texts]}

    def list_sessions(self, memoryId: str, actorId: str, maxResults: int) -> dict:  # noqa: N803
        return {"sessionSummaries": [{"sessionId": "old", "createdAt": 1}, {"sessionId": "new", "createdAt": 2}]}

    def list_events(self, memoryId: str, actorId: str, sessionId: str, maxResults: int) -> dict:  # noqa: N803
        return {"events": [{}] * (4 if sessionId == "new" else 2)}


class FakeSession:
    """A boto3 session handing out the fake clients."""

    def __init__(self, records: dict[str, list[str]]) -> None:
        self.clients = {"bedrock-agentcore-control": FakeControl(), "bedrock-agentcore": FakeData(records)}

    def client(self, name: str):
        return self.clients[name]


def test_strategies_read_either_namespace_field() -> None:
    found = memory.strategies(FakeControl(), MEMORY_ID)
    assert [s.template for s in found][1] == "/strategies/{memoryStrategyId}/actors/{actorId}"
    assert memory.by_type(found, "USER_PREFERENCE").strategy_id == "prefs-1"
    assert memory.by_type(found, "EPISODIC") is None


@pytest.mark.parametrize(
    ("index", "expected"),
    [(0, "/strategies/facts-1/actors/alice"), (2, "/strategies/sum-1/actors/alice/sessions")],
)
def test_actor_namespace_cuts_unknown_parts(index: int, expected: str) -> None:
    assert memory.actor_namespace(memory.strategies(FakeControl(), MEMORY_ID)[index], "alice") == expected


def test_report_lists_sessions_and_records_per_namespace() -> None:
    session = FakeSession({"/strategies/prefs-1/actors/alice": ['{"preference": "answers in French"}']})
    lines = memory.report(session, MEMORY_ID, "alice")
    assert lines[1].startswith("short-term") and lines[2] == "  new: 4 events"
    assert "  UserPreferences (USER_PREFERENCE) /strategies/prefs-1/actors/alice: 1 records" in lines
    assert '    - {"preference": "answers in French"}' in lines


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ("Je peux vous aider avec les données de DataStream.", True),
        ("I can help you with DataStream data and the weather.", False),
    ],
)
def test_is_french(answer: str, expected: bool) -> None:
    assert checks.is_french(answer) is expected


def test_preference_challenge_waits_for_the_memory() -> None:
    assert checks.challenge_preference({"agent_runtime_arn": "", "memory_id": ""}, FakeSession({}))[0] == "SKIP"


@pytest.mark.parametrize(
    ("records", "answer", "status"),
    [
        (["prefers French"], "Je peux vous aider avec les données et la météo.", "PASS"),
        (["prefers French"], "I can help with data.", "FAIL"),
        ([], "Je peux vous aider avec les données.", "FAIL"),
    ],
)
def test_preference_challenge(monkeypatch: pytest.MonkeyPatch, records: list, answer: str, status: str) -> None:
    monkeypatch.setattr(checks, "new_user", lambda out, session: ("prefs-42", "token"))
    monkeypatch.setattr(checks, "ask_agent", lambda *args: answer)
    monkeypatch.setattr(checks, "PREFERENCE_WAIT_SECONDS", 0)
    session = FakeSession({"/strategies/prefs-1/actors/prefs-42": records})
    out = {"agent_runtime_arn": "arn", "memory_id": MEMORY_ID}
    assert checks.challenge_preference(out, session)[0] == status


def test_challenge_lists_pass_the_session(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    entries = [("plain", lambda out: ("SKIP", "a")), ("with session", lambda out, session: ("PASS", session))]
    monkeypatch.setitem(checks.CHALLENGES, 3, entries)
    assert checks._run_challenge(3, {}, "the-session")
    assert capsys.readouterr().out.splitlines() == [
        "[CHALLENGE] SKIP stage 3 plain: a",
        "[CHALLENGE] PASS stage 3 with session: the-session",
    ]


def test_unknown_actor_has_no_sessions() -> None:
    class NoActor(FakeData):
        def list_sessions(self, **_: str) -> dict:
            raise ClientError({"Error": {"Code": "ResourceNotFoundException", "Message": "Actor x not found"}}, "op")

    assert memory.recent_sessions(NoActor({}), MEMORY_ID, "x") == []
