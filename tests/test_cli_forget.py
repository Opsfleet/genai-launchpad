"""`bootcamp.py forget`: drops the local workspace only once its state is empty (terraform is faked)."""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootcamp  # noqa: E402
from bootcamp_cli import forget, tf  # noqa: E402
from bootcamp_cli.config import Settings  # noqa: E402


class FakeTerraform:
    """Records terraform calls; `remaining` is what the state still holds after a refresh."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, workspaces: list[str], remaining: list[str]) -> None:
        self.calls: list[list[str]] = []
        monkeypatch.setattr(forget.tf, "prepare", lambda directory, env, workspace: None)
        monkeypatch.setattr(forget.tf, "workspaces", lambda directory, env: workspaces)
        monkeypatch.setattr(forget, "refreshed_addresses", lambda ctx: remaining)
        monkeypatch.setattr(forget.tf, "terraform", lambda directory, args, env, capture=False: self.calls.append(args))


WORKSPACE_DELETE = [
    ["workspace", "select", "-no-color", "default"],
    ["workspace", "delete", "-no-color", "-force", "bob"],
]
CTX = SimpleNamespace(settings=SimpleNamespace(participant="bob"), env={})


def test_nothing_to_forget_without_a_workspace(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    fake = FakeTerraform(monkeypatch, ["default"], [])
    forget.forget(CTX, force=False)
    assert fake.calls == [] and "nothing to forget" in capsys.readouterr().out


def test_empty_state_deletes_the_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTerraform(monkeypatch, ["default", "bob"], [])
    forget.forget(CTX, force=False)
    assert fake.calls == WORKSPACE_DELETE


def test_refuses_while_resources_remain(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTerraform(monkeypatch, ["default", "bob"], ["aws_cognito_user_pool.this"])
    with pytest.raises(RuntimeError, match="still exist"):
        forget.forget(CTX, force=False)
    assert fake.calls == []


def test_force_skips_the_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeTerraform(monkeypatch, ["default", "bob"], ["aws_cognito_user_pool.this"])
    forget.forget(CTX, force=True)
    assert fake.calls == WORKSPACE_DELETE


def test_refresh_runs_at_stage_0_and_ignores_local_only_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    """At the deployed stage, outputs index the resources the refresh just dropped and the apply fails."""
    applies: list[list[str]] = []
    monkeypatch.setattr(forget.tf, "prepare", lambda directory, env, workspace: None)
    monkeypatch.setattr(forget.tf, "run_live", lambda directory, args, env, verbose: applies.append(args))
    left = [
        "terraform_data.gateway_tool_sync[0]",
        'random_password.user["alice-chen"]',
        "aws_bedrockagentcore_memory.this[0]",
    ]
    monkeypatch.setattr(forget.tf, "state_addresses", lambda directory, env: left)
    settings = Settings(participant="bob", region="us-east-1", model_id="m", profile="", role_arn="")
    ctx = SimpleNamespace(settings=settings, env={}, verbose=False)
    assert forget.refreshed_addresses(ctx) == ["aws_bedrockagentcore_memory.this[0]"]
    assert "-var=stage=0" in applies[0] and "-refresh-only" in applies[0]


def test_managed_addresses_skip_data_sources_and_include_modules() -> None:
    module = {
        "resources": [{"address": "aws_s3_bucket.code", "mode": "managed"}, {"address": "data.x.y", "mode": "data"}],
        "child_modules": [{"resources": [{"address": "module.m.aws_iam_role.r", "mode": "managed"}]}],
    }
    assert tf.managed_addresses(module) == ["aws_s3_bucket.code", "module.m.aws_iam_role.r"]


def test_forget_parser() -> None:
    args = bootcamp.build_parser().parse_args(["forget", "--force"])
    assert (args.command, args.force) == ("forget", True)
