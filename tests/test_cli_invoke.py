"""`invoke` helpers and CLI parsing: reply rendering, session reuse, the deadline and flags after the subcommand."""

import json
import sys
import time
from pathlib import Path

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import bootcamp  # noqa: E402
from bootcamp_cli import agentcore, invoke, progress  # noqa: E402


@pytest.fixture
def history(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep the invoke history in a temporary folder."""
    monkeypatch.setattr(invoke, "HISTORY_DIR", tmp_path)
    return tmp_path


def test_reply_shows_extra_fields_on_one_line_each() -> None:
    body = {"response": "481 people.\n", "actor_id": "alice", "memories": ["likes\nteal"], "tools_used": ["data_agent"]}
    assert invoke.render_reply(body) == (
        '481 people.\n\nactor_id: alice\nmemories: ["likes\\nteal"]\ntools_used: ["data_agent"]'
    )


def test_plain_reply_has_no_trailing_blank_line() -> None:
    assert invoke.render_reply({"response": "Hi!\n\n"}) == "Hi!"


def test_json_reply_is_raw() -> None:
    body = {"response": "Hi", "tools_used": []}
    assert json.loads(invoke.render_reply(body, as_json=True)) == body


def test_long_fields_are_cut() -> None:
    assert invoke.compact("x" * 500).endswith("...") and len(invoke.compact("x" * 500)) == invoke.EXTRA_FIELD_CHARS


def test_session_defaults_to_a_new_one(history: Path) -> None:
    session_id = invoke.resolve_session(None, "erin")
    assert session_id.startswith(agentcore.SESSION_PREFIX) and not agentcore.is_check_session(session_id)


def test_last_session_is_reused(history: Path) -> None:
    invoke.remember("erin", "bootcamp-" + "a" * 32, "bob", "How many employees work in Engineering right now?")
    invoke.remember("erin", "bootcamp-" + "b" * 32, "carol", "hi")
    assert invoke.resolve_session("last", "erin") == "bootcamp-" + "b" * 32
    assert invoke.session_actors("erin")["bootcamp-" + "a" * 32] == "bob"
    assert invoke.load_history("erin")[0]["prompt"] == "How many employees work in Engineering ..."


def test_last_session_without_history(history: Path) -> None:
    with pytest.raises(RuntimeError, match="No earlier `invoke`"):
        invoke.resolve_session("last", "erin")


@pytest.mark.parametrize("session_id", ["short", "x" * 40 + " or 1=1"])
def test_bad_session_ids_are_refused(history: Path, session_id: str) -> None:
    with pytest.raises(RuntimeError, match="--session"):
        invoke.resolve_session(session_id, "erin")


def test_history_is_capped(history: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invoke, "HISTORY_LIMIT", 3)
    for index in range(5):
        invoke.remember("erin", f"session-{index}", "a", "p")
    assert [entry["session"] for entry in invoke.load_history("erin")] == ["session-2", "session-3", "session-4"]


def test_read_timeout_explains_the_agent_may_still_finish() -> None:
    def slow() -> None:
        raise requests.ReadTimeout()

    with pytest.raises(RuntimeError, match="may still finish server-side.*traces sid"):
        invoke.with_deadline(slow, "sid")


def test_overall_deadline(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(invoke, "DEADLINE_SECONDS", 0.05)
    with pytest.raises(RuntimeError, match="No answer from your agent"):
        invoke.with_deadline(lambda: time.sleep(1), "sid")


def test_other_errors_pass_through() -> None:
    with pytest.raises(ZeroDivisionError):
        invoke.with_deadline(lambda: 1 / 0, "sid")


@pytest.mark.parametrize(
    "argv",
    [
        ["--verbose", "invoke", "hi"],
        ["invoke", "hi", "--actor", "x", "--verbose"],
        ["up", "4", "--verbose"],
        ["phase1", "t5", "hello", "--verbose"],
    ],
)
def test_verbose_anywhere(argv: list[str]) -> None:
    assert bootcamp.build_parser().parse_args(argv).verbose is True


def test_flags_default_off() -> None:
    args = bootcamp.build_parser().parse_args(["invoke", "hi"])
    assert args.verbose is False and args.confirm is False and args.json is False and args.session is None


def test_instructor_commands_are_not_participant_commands(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        bootcamp.build_parser().parse_args(["account", "up"])
    assert "invalid choice: 'account'" in capsys.readouterr().err


def test_heartbeat_names_the_current_wait(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level("INFO", logger=progress.log.name)
    deadline = time.monotonic() + 5
    with progress.heartbeat("running stage checks", every=0.02), progress.doing("waiting for Cognito DNS"):
        while not caplog.records and time.monotonic() < deadline:
            time.sleep(0.01)
    messages = [record.getMessage() for record in caplog.records]
    assert messages and all("waiting for Cognito DNS" in message for message in messages)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
