"""`bootcamp.py doctor`: version parsing, budget and network verdicts, and the AWS chain's skip-after-failure."""

import sqlite3
import sys
from pathlib import Path

import httpx
import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import doctor, report  # noqa: E402
from bootcamp_cli.config import Settings  # noqa: E402

SETTINGS = Settings(participant="bob", region="us-east-1", model_id="gpt-6-luna", profile="", role_arn="")


def test_version_tuple_and_terraform_floor() -> None:
    assert doctor.version_tuple("Terraform v1.10.2") == (1, 10, 2)
    assert doctor.version_tuple("1.9") < doctor.version_tuple("Terraform v1.10.0")
    assert doctor.version_tuple(doctor.required_terraform()) >= (1, 9)


def test_terraform_too_old_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "tool_output", lambda command: "Terraform v1.5.7")
    assert doctor.check_terraform().status is report.Status.FAIL


def test_missing_tool_fails_with_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(doctor, "tool_output", lambda command: None)
    result = doctor.check_aws_cli()
    assert result.status is report.Status.FAIL and "install" in result.fix


@pytest.mark.parametrize(
    ("info", "status"),
    [
        ({"spend": 0.2, "max_budget": 1}, report.Status.PASS),
        ({"spend": 1.0, "max_budget": 1}, report.Status.FAIL),
        ({"spend": 0.0, "max_budget": None}, report.Status.PASS),
    ],
)
def test_budget_result(info: dict, status: report.Status) -> None:
    assert doctor.budget_result(info).status is status


def test_unreachable_endpoint_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(url: str, **_: object) -> None:
        raise httpx.ConnectError("refused")

    monkeypatch.setattr(doctor.httpx, "get", refuse)
    assert doctor.check_network("GitHub", "https://github.com/").status is report.Status.FAIL


def test_blank_participant_fails_the_participant_step() -> None:
    blank = Settings(participant="", region="us-east-1", model_id="m", profile="", role_arn="")
    assert doctor.participant_check(blank).status is report.Status.FAIL


def test_aws_chain_skips_everything_after_a_denied_role(monkeypatch: pytest.MonkeyPatch) -> None:
    chain = doctor.AwsChain(SETTINGS)
    denied = ClientError({"Error": {"Code": "AccessDenied", "Message": "no"}}, "AssumeRole")
    monkeypatch.setattr(chain, "credentials", lambda: [report.passed("AWS credentials", "me")])
    monkeypatch.setattr(chain, "participant_role", lambda: (_ for _ in ()).throw(denied))
    results = chain.run()
    assert [r.status for r in results[:3]] == [report.Status.PASS, report.Status.PASS, report.Status.FAIL]
    assert results[2].name == "Participant role" and "PARTICIPANT" in results[2].fix
    assert {r.status for r in results[3:]} == {report.Status.SKIP} and len(results) == len(doctor.AwsChain.STEPS)


def test_gateway_rejection_gets_a_gateway_hint() -> None:
    request = httpx.Request("POST", "https://llm/v1/chat/completions")
    error = httpx.HTTPStatusError("429", request=request, response=httpx.Response(429, request=request))
    assert "budget" in doctor._aws_fix(error)


def test_gateway_off_at_night_fails_the_call_with_its_hours() -> None:
    chain = doctor.AwsChain(SETTINGS)
    chain.active_hours = {"start": "08:00", "stop": "22:00", "timezone": "Asia/Jerusalem"}
    request = httpx.Request("POST", "https://llm/v1/chat/completions")
    error = httpx.HTTPStatusError("503", request=request, response=httpx.Response(503, request=request, text="<html>"))
    result = chain._call_failure(error)
    assert result.status is report.Status.FAIL and "08:00-22:00" in result.fix


def _database(tmp_path: Path, script: str) -> Path:
    db = tmp_path / "datastream_corp.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(script)
    return db


def test_database_check_passes_warns_and_fails(tmp_path: Path) -> None:
    good = _database(tmp_path, "CREATE TABLE employees (status TEXT); INSERT INTO employees VALUES ('active');")
    assert doctor.check_database(good).status is report.Status.PASS
    good.unlink()
    assert doctor.check_database(good).status is report.Status.WARN
    assert not good.exists()
    empty = _database(tmp_path, "")
    result = doctor.check_database(empty)
    assert result.status is report.Status.FAIL and "phase1 t0" in result.fix
