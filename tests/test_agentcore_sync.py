"""Gateway tool-list synchronization after a redeploy: syncs every target and waits for READY."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import agentcore  # noqa: E402


class FakeControl:
    """bedrock-agentcore-control with one target whose status walks through `statuses`."""

    def __init__(self, statuses: list[str], targets: tuple[str, ...] = ("T1",)) -> None:
        self.statuses, self.targets, self.synced = statuses, targets, []

    def list_gateway_targets(self, gatewayIdentifier: str) -> dict:  # noqa: N803 - boto3 parameter names
        return {"items": [{"targetId": target} for target in self.targets]}

    def synchronize_gateway_targets(self, gatewayIdentifier: str, targetIdList: list[str]) -> None:  # noqa: N803
        self.synced = targetIdList

    def get_gateway_target(self, gatewayIdentifier: str, targetId: str) -> dict:  # noqa: N803
        return {"status": self.statuses.pop(0), "statusReasons": ["boom"]}


class FakeSession:
    def __init__(self, control: FakeControl) -> None:
        self.control = control

    def client(self, name: str) -> FakeControl:
        return self.control


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agentcore.time, "sleep", lambda seconds: None)


def test_syncs_and_waits_until_ready() -> None:
    control = FakeControl(["SYNCHRONIZING", "SYNCHRONIZING", "READY"])
    agentcore.synchronize_gateway(FakeSession(control), "gw")
    assert control.synced == ["T1"] and control.statuses == []


def test_failed_sync_raises() -> None:
    with pytest.raises(RuntimeError, match="SYNCHRONIZE_UNSUCCESSFUL"):
        agentcore.synchronize_gateway(FakeSession(FakeControl(["SYNCHRONIZE_UNSUCCESSFUL"])), "gw")


def test_no_targets_is_a_no_op() -> None:
    control = FakeControl([], targets=())
    agentcore.synchronize_gateway(FakeSession(control), "gw")
    assert control.synced == []


def test_gives_up_eventually(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(agentcore, "SYNC_MAX_POLLS", 2)
    with pytest.raises(RuntimeError, match="still synchronizing"):
        agentcore.synchronize_gateway(FakeSession(FakeControl(["SYNCHRONIZING"] * 2)), "gw")


def test_main_rejects_bad_usage() -> None:
    assert agentcore.main(["nope"]) == 2


def test_main_syncs(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(agentcore, "synchronize_gateway", lambda session, *args: calls.append(args))
    assert agentcore.main(["sync-gateway", "gw-1"]) == 0
    assert agentcore.main(["sync-gateway", "gw-1", "target-1"]) == 0
    assert calls == [("gw-1", None), ("gw-1", ["target-1"])]


def test_sync_only_the_given_targets() -> None:
    control = FakeControl(["READY"])
    agentcore.synchronize_gateway(FakeSession(control), "gw", ["only-this"])
    assert control.synced == ["only-this"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
