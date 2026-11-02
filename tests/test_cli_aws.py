"""Auto-refreshing participant credentials: generated AWS config, child env and the parent's session type."""

import configparser
import stat
import sys
from pathlib import Path

import boto3
import pytest
from botocore.credentials import RefreshableCredentials

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bootcamp_cli import aws  # noqa: E402
from bootcamp_cli.config import Settings  # noqa: E402

ROLE = "arn:aws:iam::123456789012:role/bootcamp/bootcamp-participant-dawson"
USER_CONFIG = """[sso-session corp]
sso_start_url = https://corp.awsapps.com/start
sso_region = us-east-1

[profile sb]
sso_session = corp
sso_account_id = 123456789012
sso_role_name = AdministratorAccess

[default]
region = eu-west-1
s3 =
  max_concurrent_requests = 4
"""


def settings(profile: str = "sb") -> Settings:
    """Participant settings for dawson."""
    return Settings(participant="dawson", region="us-east-1", model_id="m", profile=profile, role_arn="")


def parse(text: str) -> configparser.RawConfigParser:
    parser = configparser.RawConfigParser()
    parser.read_string(text)
    return parser


def test_config_keeps_user_profiles_and_adds_role_profile() -> None:
    parsed = parse(aws.bootcamp_config(USER_CONFIG, settings(), ROLE, {}))
    assert parsed["profile sb"]["sso_session"] == "corp"
    assert parsed["sso-session corp"]["sso_region"] == "us-east-1"
    assert "max_concurrent_requests = 4" in parsed["default"]["s3"]
    assert dict(parsed["profile bootcamp-dawson"]) == {
        "role_arn": ROLE,
        "role_session_name": "bootcamp-dawson",
        "region": "us-east-1",
        "source_profile": "sb",
    }


def test_static_env_keys_become_a_base_profile() -> None:
    environ = {"AWS_ACCESS_KEY_ID": "AKIDEXAMPLE", "AWS_SECRET_ACCESS_KEY": "secret", "AWS_SESSION_TOKEN": "tok"}
    parsed = parse(aws.bootcamp_config("", settings(profile=""), ROLE, environ))
    assert parsed["profile bootcamp-dawson"]["source_profile"] == aws.BASE_PROFILE
    assert parsed[f"profile {aws.BASE_PROFILE}"]["aws_session_token"] == "tok"


def test_no_profile_and_no_keys_uses_default_profile() -> None:
    parsed = parse(aws.bootcamp_config(USER_CONFIG, settings(profile=""), ROLE, {}))
    assert parsed["profile bootcamp-dawson"]["source_profile"] == "default"


def test_private_config_is_owner_only(tmp_path: Path) -> None:
    """POSIX mode bits only; on Windows the file sits in the user's own %TEMP%, protected by its ACL."""
    path = aws.write_private_config("[default]\n")
    assert path.read_text() == "[default]\n"
    if sys.platform != "win32":
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0


def test_user_config_path_respects_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "custom"))
    assert aws.user_config_path() == tmp_path / "custom"


def static_config(tmp_path: Path) -> Path:
    """A config whose role profile sources static keys (no network needed to build the session)."""
    text = "[profile src]\naws_access_key_id = AKIDEXAMPLE\naws_secret_access_key = s\n"
    path = tmp_path / "config"
    path.write_text(aws.bootcamp_config(text, settings(profile="src"), ROLE, {}))
    return path


def test_parent_session_credentials_refresh(tmp_path: Path) -> None:
    session = aws.profile_session(static_config(tmp_path), "bootcamp-dawson", "us-east-1")
    assert isinstance(session._session.get_credentials(), RefreshableCredentials)


def test_children_get_profile_not_static_keys(tmp_path: Path) -> None:
    config = static_config(tmp_path)
    access = aws.AwsAccess(aws.profile_session(config, "bootcamp-dawson", "us-east-1"), config, "bootcamp-dawson")
    environ = {"AWS_ACCESS_KEY_ID": "AKIDEXAMPLE", "AWS_SECRET_ACCESS_KEY": "s", "AWS_PROFILE": "sb", "PATH": "/bin"}
    env = access.child_env(environ)
    assert env["AWS_CONFIG_FILE"] == str(config)
    assert env["AWS_PROFILE"] == "bootcamp-dawson"
    assert env["AWS_REGION"] == "us-east-1"
    assert env["PATH"] == "/bin"
    assert not {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN"} & env.keys()


def test_instructor_children_get_frozen_keys() -> None:
    session = boto3.Session(aws_access_key_id="AKIDEXAMPLE", aws_secret_access_key="s", region_name="us-east-1")
    env = aws.AwsAccess(session).child_env({"AWS_PROFILE": "sb"})
    assert env["AWS_ACCESS_KEY_ID"] == "AKIDEXAMPLE"
    assert "AWS_PROFILE" not in env and "AWS_CONFIG_FILE" not in env
