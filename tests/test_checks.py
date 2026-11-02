"""Smoke-check helpers that decide PASS/FAIL without AWS: result parsing, number matching, stage gating, paging."""

import base64
import json
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import checks  # noqa: E402


@pytest.mark.parametrize(
    ("answer", "number", "expected"),
    [
        ("Engineering has 481 employees.", 481, True),
        ("There are **481** people", 481, True),
        ("It printed 57,938.", 57938, True),
        ("4810 employees", 481, False),
        ("1,481 employees", 481, False),
        ("about 4.81 hundred", 481, False),
        ("I could not find that.", 481, False),
    ],
)
def test_mentions_number(answer: str, number: int, expected: bool) -> None:
    assert checks.mentions_number(answer, number) is expected


def fake_tool(monkeypatch: pytest.MonkeyPatch, is_error: bool, text: str) -> None:
    """Make agentcore.call_tool return a fixed (is_error, text)."""
    monkeypatch.setattr(checks.agentcore, "call_tool", lambda *args: (is_error, text))


def test_query_rows_returns_data(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tool(monkeypatch, False, json.dumps({"data": [{"n": 3}], "rows_affected": -1}))
    assert checks.query_rows("url", "token", "query_db", "SELECT 1") == [{"n": 3}]


@pytest.mark.parametrize(
    ("is_error", "text"),
    [(False, "Error executing query: no such table: x"), (False, '{"rows": []}'), (True, "denied by policy")],
)
def test_query_rows_rejects_non_data(monkeypatch: pytest.MonkeyPatch, is_error: bool, text: str) -> None:
    fake_tool(monkeypatch, is_error, text)
    with pytest.raises(RuntimeError):
        checks.query_rows("url", "token", "query_db", "SELECT 1")


def test_unprovisioned_stage_is_reported(capsys: pytest.CaptureFixture[str]) -> None:
    assert not checks.run_checks({"stage": "4"}, session=None, up_to=4, only=7)
    assert "stage 7 not provisioned (current: 4)" in capsys.readouterr().out


class FakeLogs:
    """filter_log_events that returns empty pages (with a nextToken) before the page holding a span."""

    def __init__(self, empty_pages: int) -> None:
        self.empty_pages = empty_pages
        self.calls = 0

    def filter_log_events(self, **_: object) -> dict:
        self.calls += 1
        if self.calls <= self.empty_pages:
            return {"events": [], "nextToken": f"t{self.calls}"}
        return {"events": [{"message": "span"}]}


def test_find_spans_follows_pages() -> None:
    assert checks.find_spans(FakeLogs(empty_pages=2), "rt") == [{"message": "span"}]


def test_find_spans_gives_up() -> None:
    logs = FakeLogs(empty_pages=99)
    assert checks.find_spans(logs, "rt") == []
    assert logs.calls == checks.SPANS_MAX_PAGES


def test_no_argument_tools_skips_query_tool_and_required_args() -> None:
    schemas = {"query_db": {}, "list_tables": {}, "describe_table": {"required": ["table_name"]}, "x": {"required": []}}
    assert checks.no_argument_tools(schemas, "query_db") == ["list_tables", "x"]


def test_extra_tools_must_return_json(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tool(monkeypatch, False, "Error executing query: boom")
    with pytest.raises(RuntimeError, match="list_tables"):
        checks.extra_tools_detail("url", "token", {"query_db": {}, "list_tables": {}}, "query_db")


def test_extra_tools_detail_counts_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tool(monkeypatch, False, json.dumps({"data": [{"name": "employees"}]}))
    detail = checks.extra_tools_detail("url", "token", {"query_db": {}, "list_tables": {}}, "query_db")
    assert detail == " extra tools OK (rows): {'list_tables': 1}"
    assert checks.extra_tools_detail("url", "token", {"query_db": {}}, "query_db") == ""


@pytest.mark.parametrize(
    ("answer", "expected"),
    [("", True), ("  \n", True), ("Sorry, the model returned an empty answer (possibly ...)", True), ("481", False)],
)
def test_is_empty_answer(answer: str, expected: bool) -> None:
    assert checks.is_empty_answer(answer) is expected


def fake_agent(monkeypatch: pytest.MonkeyPatch, answers: list[str]) -> list[str]:
    """Make agentcore.invoke_agent return `answers` in order; returns the list of prompts it received."""
    prompts: list[str] = []

    def invoke(out, token, prompt, session_id):
        prompts.append(prompt)
        return answers.pop(0)

    monkeypatch.setattr(checks.agentcore, "invoke_agent", invoke)
    return prompts


def test_ask_agent_retries_once_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    prompts = fake_agent(monkeypatch, ["", "481 people"])
    assert checks.ask_agent({}, "q", "t") == "481 people"
    assert prompts == ["q", "q"]


class FakeUsers:
    """Stands in for bootcamp_cli.users: records created and deleted users, tokens are 'token-<name>'."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.created: list[str] = []
        self.deleted: list[str] = []
        monkeypatch.setattr(checks.users, "admin_password", lambda _session, _out, name: self.create(name))
        monkeypatch.setattr(checks.users, "sign_in", lambda session, out, name, password: f"token-{name}")
        monkeypatch.setattr(checks.users, "delete_user", lambda session, out, name: self.deleted.append(name))

    def create(self, name: str) -> str:
        self.created.append(name)
        return "pw"


def test_each_check_user_is_new_and_deleted_after_the_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fixed actor would let long-term memory from an earlier run answer instead of the tools."""
    fake = FakeUsers(monkeypatch)
    first, second = checks.new_user({}, None), checks.new_user({}, None)
    assert first[0] != second[0] and all(name.startswith("bootcamp-check-") for name in fake.created)
    assert first[1] == f"token-{first[0]}"
    checks.delete_check_users(None)
    assert sorted(fake.deleted) == sorted(fake.created) and not checks._CHECK_USERS


def test_forged_token_carries_the_victims_claims() -> None:
    out = {"discovery_url": "https://idp/pool/.well-known/openid-configuration", "user_client_id": "c"}
    header, claims, signature = checks.forged_token(out, "alice-chen").split(".")
    decoded = json.loads(base64.urlsafe_b64decode(claims + "=" * (-len(claims) % 4)))
    assert decoded["username"] == "alice-chen" and decoded["iss"] == "https://idp/pool" and signature


def fake_identity(monkeypatch: pytest.MonkeyPatch, statuses: dict, actor_id: str) -> list[dict]:
    """Runtime answering `statuses` per token and `actor_id` to any question; returns the extra headers sent."""
    sent: list[dict] = []
    monkeypatch.setattr(checks.agentcore, "get_token", lambda out: "m2m")
    monkeypatch.setattr(checks.agentcore, "invoke_status", lambda out, token: statuses.get(token, 403))
    monkeypatch.setattr(checks.users, "user_token", lambda session, out, name: f"token-{name}")
    monkeypatch.setattr(checks, "forged_token", lambda out, name: "forged")

    def invoke(out, token, prompt, session_id, extra_headers=None):
        sent.append(extra_headers or {})
        return {"response": "hi", "actor_id": actor_id}

    monkeypatch.setattr(checks.agentcore, "invoke_agent_body", invoke)
    return sent


@pytest.mark.parametrize(
    ("statuses", "actor_id", "ok"),
    [
        ({None: 401, "m2m": 403, "forged": 401}, "jordan-lee", True),
        ({None: 401, "m2m": 200, "forged": 401}, "jordan-lee", False),
        ({None: 401, "m2m": 403, "forged": 401}, "alice-chen", False),
    ],
)
def test_check_identity(monkeypatch: pytest.MonkeyPatch, statuses: dict, actor_id: str, ok: bool) -> None:
    sent = fake_identity(monkeypatch, statuses, actor_id)
    assert checks.check_identity({}, None)[0] is ok
    assert sent == [{checks.agentcore.FORGED_ACTOR_HEADER: "alice-chen"}]


def test_ask_agent_gives_a_hint_when_still_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_agent(monkeypatch, ["", ""])
    with pytest.raises(RuntimeError, match="another MODEL_ID"):
        checks.ask_agent({}, "q", "t")


def test_optional_prompts_are_datastream_work() -> None:
    assert checks.CODE_INTERPRETER_PROMPT.startswith("DataStream")
    assert checks.BROWSER_PROMPT.startswith("DataStream")
    assert checks.CODE_INTERPRETER_EXPECTED == 57938


def test_code_interpreter_prompt_does_not_invite_a_phone_shaped_answer() -> None:
    assert "number" not in checks.CODE_INTERPRETER_PROMPT
    assert "checksum it prints" in checks.CODE_INTERPRETER_PROMPT


def fake_mcp(monkeypatch: pytest.MonkeyPatch, schemas: dict[str, dict], text: str) -> None:
    """A fake MCP endpoint exposing `schemas` whose every tool answers `text`."""
    monkeypatch.setattr(checks.agentcore, "get_token", lambda out: "token")
    monkeypatch.setattr(checks.agentcore, "list_tool_schemas", lambda url, token: schemas)
    monkeypatch.setattr(checks.agentcore, "list_tools", lambda url, token: list(schemas))
    fake_tool(monkeypatch, False, text)


OUT = {"mcp_server_url": "rt", "gateway_url": "gw", "agent_runtime_arn": "arn"}


@pytest.mark.parametrize(
    ("schemas", "rows", "status"),
    [
        ({"query_db": {}}, [], "SKIP"),
        ({"query_db": {}, "list_tables": {}}, [{"name": "employees"}], "PASS"),
        ({"query_db": {}, "list_tables": {}}, [{"name": "other"}], "FAIL"),
    ],
)
def test_challenge_list_tables(monkeypatch: pytest.MonkeyPatch, schemas: dict, rows: list, status: str) -> None:
    fake_mcp(monkeypatch, schemas, json.dumps({"data": rows}))
    assert checks.challenge_list_tables(OUT)[0] == status


@pytest.mark.parametrize(
    ("schemas", "status"),
    [({}, "SKIP"), ({"DataStreamDatabase___describe_table": {"required": ["table"]}}, "PASS")],
)
def test_challenge_describe_table(monkeypatch: pytest.MonkeyPatch, schemas: dict, status: str) -> None:
    fake_mcp(monkeypatch, schemas, json.dumps({"data": [{"name": "updated_at", "type": "TEXT"}]}))
    assert checks.challenge_describe_table(OUT)[0] == status


def fake_body(monkeypatch: pytest.MonkeyPatch, extra: dict) -> None:
    """Make the agent reply {"response": ..., **extra}, where extra may echo the signed-in user (from the token)."""
    monkeypatch.setattr(checks, "new_user", lambda out, session: ("check-1", "token-check-1"))

    def invoke(out, token, prompt, session_id, extra_headers=None):
        actor = token.removeprefix("token-")
        return {"response": "hi"} | {key: (actor if value == "ECHO" else value) for key, value in extra.items()}

    monkeypatch.setattr(checks.agentcore, "invoke_agent_body", invoke)


@pytest.mark.parametrize(
    ("extra", "status"),
    [
        ({}, "SKIP"),
        ({"actor_id": "ECHO", "memories": []}, "PASS"),
        ({"actor_id": "default_user", "memories": []}, "FAIL"),
        ({"actor_id": "ECHO"}, "SKIP"),
        ({"actor_id": "ECHO", "memories": "none"}, "FAIL"),
    ],
)
def test_challenge_who_am_i(monkeypatch: pytest.MonkeyPatch, extra: dict, status: str) -> None:
    fake_body(monkeypatch, extra)
    assert checks.challenge_who_am_i(OUT, None)[0] == status


def test_agent_target_is_the_deployed_agent_after_up_4() -> None:
    out = {"agent_runtime_arn": "arn:runtime"}
    with checks.agent_target(out, None) as target:
        assert target is out


def test_agent_target_runs_agent_py_locally_before_up_4(monkeypatch: pytest.MonkeyPatch) -> None:
    started = []

    @contextmanager
    def running(out: dict, model_id: str, session: object):
        started.append(model_id)
        yield {"local_agent_url": "http://127.0.0.1:8080", "local_workload_token": "wat"}

    monkeypatch.setattr(checks.local_agent, "running", running)
    with checks.agent_target({"agent_runtime_arn": "", "model_id": "nova-2-lite"}, None) as target:
        assert checks.agentcore.runtime_url(target) == "http://127.0.0.1:8080/invocations"
        assert checks.agentcore.local_headers(target) == {"WorkloadAccessToken": "wat"}
    assert started == ["nova-2-lite"]


@pytest.mark.parametrize(
    ("extra", "status"),
    [
        ({}, "SKIP"),
        ({"tools_used": ["data_agent"]}, "PASS"),
        ({"tools_used": []}, "FAIL"),
        ({"tools_used": "data_agent"}, "FAIL"),
    ],
)
def test_challenge_tools_used(monkeypatch: pytest.MonkeyPatch, extra: dict, status: str) -> None:
    fake_body(monkeypatch, extra)
    assert checks.challenge_tools_used(OUT, None)[0] == status


@pytest.mark.parametrize(("status", "ok"), [("PASS", True), ("SKIP", True), ("FAIL", False)])
def test_challenge_line(monkeypatch: pytest.MonkeyPatch, capsys, status: str, ok: bool) -> None:
    monkeypatch.setitem(checks.CHALLENGES, 1, ("demo", lambda out: (status, "detail")))
    assert checks._run_challenge(1, {}) is ok
    assert capsys.readouterr().out == f"[CHALLENGE] {status} stage 1 demo: detail\n"


def test_challenge_error_is_a_failure(monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.setitem(checks.CHALLENGES, 1, ("demo", lambda out: 1 / 0))
    assert not checks._run_challenge(1, {})
    assert "[CHALLENGE] FAIL stage 1 demo: ZeroDivisionError" in capsys.readouterr().out


@pytest.mark.parametrize(("bypass_answer", "ok"), [("Error: the database is read-only", True), ('{"data": []}', False)])
def test_policy_check_requires_disguised_writes_to_fail(
    monkeypatch: pytest.MonkeyPatch, bypass_answer: str, ok: bool
) -> None:
    """A disguised write that Cedar lets through must not run; a normal JSON result means it executed."""

    def call_tool(url, token, tool, arguments):
        query = arguments["query"]
        if query == checks.HARMLESS_DELETE_SQL:
            return True, "Tool Execution Denied"
        if query in checks.CEDAR_BYPASS_SQL:
            return False, bypass_answer
        return False, json.dumps({"data": [{"n": 1}]})

    monkeypatch.setattr(checks.agentcore, "get_token", lambda out: "token")
    monkeypatch.setattr(checks.agentcore, "call_tool", call_tool)
    assert checks.check_policy(OUT, None)[0] is ok


def test_ask_agent_retries_once_after_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    replies: list = [checks.requests.ReadTimeout(), "481 people"]

    def invoke(out, token, prompt, session_id, extra_headers=None):
        reply = replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply

    monkeypatch.setattr(checks.agentcore, "invoke_agent", invoke)
    assert checks.ask_agent({}, "q", "t") == "481 people"


def test_ask_agent_hint_after_two_timeouts(monkeypatch: pytest.MonkeyPatch) -> None:
    def invoke(out, token, prompt, session_id, extra_headers=None):
        raise checks.requests.ReadTimeout()

    monkeypatch.setattr(checks.agentcore, "invoke_agent", invoke)
    with pytest.raises(RuntimeError, match="no answer within"):
        checks.ask_agent({}, "q", "t")


def test_check_sessions_are_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions: list[str] = []
    monkeypatch.setattr(checks.agentcore, "invoke_agent", lambda out, token, prompt, sid: sessions.append(sid) or "ok")
    checks.ask_agent({}, "q", "t")
    assert checks.agentcore.is_check_session(sessions[0]) and len(sessions[0]) >= 33


@pytest.mark.parametrize(
    ("text", "limit", "expected"),
    [
        ("There are\n\n**481** people.\n", 120, "There are **481** people."),
        ("MCP error: [No policy allows this action on the tool]", 30, "MCP error: [No policy..."),
        ("x" * 50, 10, "xxxxxxx..."),
    ],
)
def test_one_line(text: str, limit: int, expected: str) -> None:
    assert checks.one_line(text, limit) == expected


def test_open_identity_hole_downgrades_only_the_identity_checks(capsys: pytest.CaptureFixture[str]) -> None:
    required = {name: req for name, _, req in checks.stage_checks(4, {"trust_actor_header": True})}
    assert required == {"agent answers": True, "identity from the verified token only": False,
                        "memory recall across sessions, no cross-user leak": False}  # fmt: skip
    assert all(req for _, _, req in checks.stage_checks(4, {}))
    checks.print_skipped_optionals(4, {"trust_actor_header": True})
    assert "[WARN] stage 4 TRUST_ACTOR_HEADER=true" in capsys.readouterr().out


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_browser_check_asks_again_after_a_miss(monkeypatch: pytest.MonkeyPatch) -> None:
    answers = iter(["The browser timed out.", "syncToken is 1700000000."])
    monkeypatch.setattr(checks, "new_user", lambda out, session: ("user", "token"))
    monkeypatch.setattr(checks, "live_sync_token", lambda: "1700000000")
    monkeypatch.setattr(checks, "ask_agent", lambda out, prompt, token: next(answers))
    assert checks.check_browser({}, None)[0]
