"""Locale-proof output; actionable one-line messages for AWS, network and missing-output failures; region resolution."""

import io
import sys
from pathlib import Path

import httpx
import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import cli, config, errors  # noqa: E402


def test_output_survives_a_non_utf8_code_page(monkeypatch: pytest.MonkeyPatch) -> None:
    out = io.TextIOWrapper(io.BytesIO(), encoding="cp1255", newline="\n")
    monkeypatch.setattr(sys, "stdout", out)
    cli.utf8_output()
    print("assistante exécutive")
    out.flush()
    assert out.buffer.getvalue().decode("utf-8") == "assistante exécutive\n"


def client_error(code: str, operation: str = "GetSecretValue") -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "m"}}, operation)


def test_invalid_access_key_names_the_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AWS_PROFILE", "sb")
    assert "aws configure --profile sb" in errors.explain(client_error("InvalidClientTokenId"))


def test_assume_role_denied_points_at_roster() -> None:
    assert "roster.json" in errors.explain(client_error("AccessDenied", "AssumeRole"))


def test_access_denied_explains_isolation() -> None:
    assert "tag isolation" in errors.explain(client_error("AccessDeniedException"))


def test_missing_output_says_run_up_0() -> None:
    assert "up 0" in errors.explain(KeyError("token_url"))


def test_network_error_is_one_line() -> None:
    message = errors.explain(httpx.ConnectError("boom"))
    assert "connection" in message and "\n" not in message


@pytest.mark.parametrize(
    ("bootcamp", "aws", "expected"),
    [("eu-west-1", "us-west-2", "eu-west-1"), ("", "us-west-2", "us-west-2"), ("", "", "us-east-1")],
)
def test_bootcamp_region_wins(monkeypatch: pytest.MonkeyPatch, bootcamp: str, aws: str, expected: str) -> None:
    monkeypatch.setenv("BOOTCAMP_REGION", bootcamp)
    monkeypatch.setenv("AWS_REGION", aws)
    assert config.resolve_region() == expected


def test_empty_participant_gets_a_friendly_one_liner() -> None:
    message = config.participant_problem("")
    assert message and "PARTICIPANT is empty" in message and "\n" not in message


def test_malformed_participant_is_named() -> None:
    assert "'Bad-Name'" in (config.participant_problem("Bad-Name") or "")


def test_valid_participant_has_no_problem() -> None:
    assert config.participant_problem("carol") is None


HOURS = {"start": "08:00", "stop": "22:00", "timezone": "Asia/Jerusalem"}


def test_gateway_hours_hint_names_the_window_when_known() -> None:
    assert "08:00-22:00 (Asia/Jerusalem)" in errors.gateway_hours_hint(HOURS)
    assert "daily hours" in errors.gateway_hours_hint(None)


@pytest.mark.parametrize(("status", "raises"), [(503, True), (502, False), (200, False), (429, False)])
def test_gateway_down_hook_turns_503_into_the_hours_hint(status: int, raises: bool) -> None:
    response = httpx.Response(status, request=httpx.Request("GET", "https://llm/key/info"))
    if not raises:
        errors.raise_if_gateway_down(HOURS, response)
        return
    with pytest.raises(RuntimeError, match="08:00-22:00"):
        errors.raise_if_gateway_down(HOURS, response)


def test_explain_503_hints_at_gateway_hours_not_the_html_body() -> None:
    request = httpx.Request("GET", "https://llm/key/info")
    response = httpx.Response(503, request=request, text="<html>503 Service Temporarily Unavailable</html>")
    message = errors.explain(httpx.HTTPStatusError("503", request=request, response=response))
    assert "daily hours" in message and "<html>" not in message
