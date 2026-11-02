"""`invoke --local`: the local agent gets the runtime's environment from stack outputs, never from .env."""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import agentcore, local_agent  # noqa: E402

OUT = {
    "participant": "bob",
    "litellm_base_url": "https://llm.example",
    "gateway_url": "https://gw.example/mcp",
    "memory_id": "awsworkshop_bob_memory-1",
    "memory_strategy_id": "facts-1",
    "memory_preference_strategy_id": "prefs-1",
    "memory_summary_strategy_id": "summary-1",
    "credential_provider_name": "awsworkshop-bob-gateway",
    "oauth_scope": "bootcamp/invoke",
    "local_workload_identity": "awsworkshop-bob-local",
    "code_interpreter_enabled": False,
    "browser_enabled": False,
    "guardrail_id": "",
    "trust_actor_header": False,
}


class FakeSession:
    region_name = "us-east-1"

    def get_credentials(self):
        return self

    def get_frozen_credentials(self):
        return self

    access_key, secret_key, token = "AKIA_ROLE", "secret", "session-token"


def test_needs_memory_first() -> None:
    with pytest.raises(RuntimeError, match="up 3"):
        local_agent.agent_env(OUT | {"memory_id": "", "local_workload_identity": ""}, "nova-2-lite")


def test_runtime_variables_come_from_outputs() -> None:
    env = local_agent.agent_env(OUT, "nova-2-lite")
    assert env["MODEL_ID"] == "nova-2-lite"
    assert env["MEMORY_PREFERENCE_STRATEGY_ID"] == "prefs-1"
    assert env["CODE_INTERPRETER_ENABLED"] == "false" and "CODE_INTERPRETER_ID" not in env
    assert "GUARDRAIL_ID" not in env and "TRUST_ACTOR_HEADER" not in env


def test_optional_features_follow_the_stack() -> None:
    out = OUT | {"browser_enabled": True, "guardrail_id": "g-1", "guardrail_version": "2", "trust_actor_header": True}
    env = local_agent.agent_env(out, "nova-2-lite")
    assert env["BROWSER_ENABLED"] == "true" and env["BROWSER_ID"] == "aws.browser.v1"
    assert env["GUARDRAIL_ID"] == "g-1" and env["GUARDRAIL_VERSION"] == "2"
    assert env["TRUST_ACTOR_HEADER"] == "true"


def test_process_uses_the_role_not_the_shell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "bootcamp")
    monkeypatch.setenv("TRUST_ACTOR_HEADER", "true")
    env = local_agent.process_env(OUT, "nova-2-lite", FakeSession())
    assert "AWS_PROFILE" not in env and "TRUST_ACTOR_HEADER" not in env
    assert env["AWS_ACCESS_KEY_ID"] == "AKIA_ROLE" and env["AWS_SESSION_TOKEN"] == "session-token"
    assert str(local_agent.SHARED_DIR) in env["PYTHONPATH"].split(os.pathsep)


def test_windows_stops_the_whole_process_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []
    monkeypatch.setattr(local_agent.os, "name", "nt")
    monkeypatch.setattr(local_agent.subprocess, "run", lambda cmd, **_: calls.append(cmd))

    class Agent:
        pid = 42

        def wait(self, timeout: int) -> None:
            calls.append("waited")

    local_agent._stop(Agent())
    assert calls == [["taskkill", "/PID", "42", "/T", "/F"], "waited"]


def test_agent_writes_utf8_whatever_the_locale() -> None:
    assert local_agent.process_env(OUT, "nova-2-lite", FakeSession())["PYTHONUTF8"] == "1"


def test_deployed_agent_gets_no_workload_token_header() -> None:
    assert agentcore.local_headers({"agent_runtime_arn": "arn"}) == {}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
