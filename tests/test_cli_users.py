"""End-user sign-in (`users`), the runtime's SSE stream (`agentcore.sse_events`) and live printing (`invoke`)."""

import io
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import agentcore, invoke, users  # noqa: E402

OUT = {"pool_id": "pool", "user_client_id": "client", "users_parameter_path": "/workshop/awsworkshop-bob-users",
       "story_users": "alice-chen,jordan-lee"}  # fmt: skip


class UsernameExistsException(Exception):
    """Mirrors the Cognito error the CLI tolerates for an existing test user."""


class UserNotFoundException(Exception):
    """Mirrors the Cognito error for an already deleted user."""


class FakeCognito:
    """Records admin calls; sign-in answers with 'token-<user>-<password>'."""

    exceptions = type("Exceptions", (), {"UsernameExistsException": UsernameExistsException,
                                         "UserNotFoundException": UserNotFoundException})  # fmt: skip

    def __init__(self, existing: set[str]) -> None:
        self.users, self.calls = set(existing), []

    def admin_create_user(self, UserPoolId: str, Username: str, MessageAction: str) -> None:
        if Username in self.users:
            raise UsernameExistsException()
        self.users.add(Username)
        self.calls.append(("create", Username))

    def admin_set_user_password(self, UserPoolId: str, Username: str, Password: str, Permanent: bool) -> None:
        self.calls.append(("password", Username))

    def admin_delete_user(self, UserPoolId: str, Username: str) -> None:
        self.users.discard(Username)
        self.calls.append(("delete", Username))

    def initiate_auth(self, ClientId: str, AuthFlow: str, AuthParameters: dict) -> dict:
        assert (ClientId, AuthFlow) == ("client", "USER_PASSWORD_AUTH")
        token = f"token-{AuthParameters['USERNAME']}-{AuthParameters['PASSWORD']}"
        return {"AuthenticationResult": {"AccessToken": token}}


class FakeSsm:
    """One stored story-user password."""

    def get_parameter(self, Name: str, WithDecryption: bool) -> dict:
        assert Name == "/workshop/awsworkshop-bob-users/alice-chen" and WithDecryption
        return {"Parameter": {"Value": "stored-pw"}}


class FakeSession:
    def __init__(self, cognito: FakeCognito) -> None:
        self.clients = {"cognito-idp": cognito, "ssm": FakeSsm()}

    def client(self, name: str):
        return self.clients[name]


def test_story_users_sign_in_with_their_stored_password() -> None:
    cognito = FakeCognito({"alice-chen"})
    assert users.user_token(FakeSession(cognito), OUT, "alice-chen") == "token-alice-chen-stored-pw"
    assert cognito.calls == []


def test_any_other_name_becomes_a_test_user_with_a_fresh_password() -> None:
    cognito = FakeCognito({"guess-test"})
    token = users.user_token(FakeSession(cognito), OUT, "guess-test")
    assert token.startswith("token-guess-test-") and token.endswith(users.PASSWORD_SUFFIX)
    assert cognito.calls == [("password", "guess-test")]


def test_temporary_users_are_new_and_deleted_on_exit() -> None:
    cognito = FakeCognito(set())
    with users.temporary_users(FakeSession(cognito), OUT, 2, "eval") as accounts:
        names = [name for name, _ in accounts]
        assert len(set(names)) == 2 and all(name.startswith("eval-") for name in names)
    assert not cognito.users and [call[0] for call in cognito.calls].count("delete") == 2


def test_sse_events_parse_data_lines_only() -> None:
    lines = ['data: {"delta": "Hel"}', "", ": keep-alive", 'data: "lo"', 'data: {"response": "Hello"}']
    assert list(agentcore.sse_events(iter(lines))) == [{"delta": "Hel"}, {"delta": "lo"}, {"response": "Hello"}]


def printer() -> invoke.StreamPrinter:
    return invoke.StreamPrinter(out=io.StringIO(), notes=io.StringIO())


def test_stream_printer_prints_deltas_and_tools_on_their_own_line() -> None:
    live = printer()
    for event in [{"delta": "Let me check."}, {"tool": "data_agent"}, {"delta": "481."}, {"response": "x"}]:
        live.handle(event)
    live.finish()
    assert live.out.getvalue() == "Let me check.\n481.\n"
    assert live.notes.getvalue() == "[calling data_agent]\n" and live.tools == ["data_agent"]
    assert live.reply == {"response": "x"}


def test_stream_printer_falls_back_to_the_reply_text() -> None:
    live = printer()
    live.handle({"response": "Sorry, empty.", "actor_id": "alice-chen"})
    live.finish()
    assert live.out.getvalue() == "Sorry, empty.\n"


def test_stream_printer_raises_on_a_runtime_error_event() -> None:
    with pytest.raises(RuntimeError, match="mid-stream"):
        printer().handle({"error": "boom", "error_type": "ValueError"})


def test_print_stream_json_prints_raw_events(capsys: pytest.CaptureFixture[str]) -> None:
    invoke.print_stream([{"delta": "hi"}, {"response": "hi"}], as_json=True)
    lines = capsys.readouterr().out.splitlines()
    assert [json.loads(line) for line in lines] == [{"delta": "hi"}, {"response": "hi"}]
