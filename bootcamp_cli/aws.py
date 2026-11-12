"""AWS session handling for the CLI and the terraform/python processes it starts.

Participant commands run as bootcamp-participant-<name>. Instead of assuming the role once and freezing the
temporary keys (role chaining caps them at one hour, after which long chats and applies fail with a misleading
401), the CLI writes a private AWS config: a copy of the user's own config plus a `bootcamp-<name>` profile with
`role_arn` and a source profile. The CLI's own session and every child (terraform, Phase 1 scripts) use that
profile through AWS_CONFIG_FILE/AWS_PROFILE, so botocore and the Go SDK re-assume the role before it expires.
"""

import atexit
import configparser
import logging
import os
import shutil
import tempfile
from pathlib import Path

import boto3
import botocore.session

from bootcamp_cli.config import Settings

log = logging.getLogger(__name__)

STATIC_KEY_VARS = ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
CREDENTIAL_VARS = (*STATIC_KEY_VARS, "AWS_SECURITY_TOKEN", "AWS_PROFILE", "AWS_DEFAULT_PROFILE")
BASE_PROFILE = "bootcamp-base"
REFRESHING_METHODS = ("container-role", "iam-role")
"""Credential sources that renew themselves in every child process (a Studio space, an EC2 instance role)."""


def participant_role_arn(account: str, participant: str) -> str:
    """ARN of the tag-isolated role the instructor's account stack created for `participant`."""
    return f"arn:aws:iam::{account}:role/bootcamp/bootcamp-participant-{participant}"


def runs_as_participant(caller_arn: str, participant: str) -> bool:
    """True when the base credentials already ARE the participant role (a Studio space runs as it)."""
    return f":assumed-role/bootcamp-participant-{participant}/" in caller_arn


def user_config_path() -> Path:
    """The AWS config file the user's own tools read (AWS_CONFIG_FILE or ~/.aws/config)."""
    return Path(os.environ.get("AWS_CONFIG_FILE") or Path.home() / ".aws" / "config").expanduser()


def profile_section(profile: str) -> str:
    """Config-file section name for `profile` (`default` has no `profile ` prefix)."""
    return profile if profile == "default" else f"profile {profile}"


def profile_name(settings: Settings) -> str:
    """Name of the generated participant profile."""
    return f"bootcamp-{settings.participant}"


def source_settings(profile: str, environ: dict[str, str]) -> tuple[dict[str, str], dict[str, str] | None]:
    """How the bootcamp profile gets its base credentials.

    Args:
        profile: the user's AWS_PROFILE ("" when unset).
        environ: the process environment.

    Returns:
        (settings for the bootcamp profile, base-profile keys or None). Static environment keys are moved into a
        base profile because env keys would otherwise win over AWS_PROFILE in every SDK.
    """
    if profile:
        return {"source_profile": profile}, None
    if environ.get("AWS_ACCESS_KEY_ID") and environ.get("AWS_SECRET_ACCESS_KEY"):
        keys = {var.lower(): environ[var] for var in STATIC_KEY_VARS if environ.get(var)}
        return {"source_profile": BASE_PROFILE}, keys
    return {"source_profile": "default"}, None


def bootcamp_config(user_config: str, settings: Settings, role_arn: str, environ: dict[str, str]) -> str:
    """Text of the private config: the user's config plus the auto-refreshing `bootcamp-<name>` profile."""
    parser = configparser.RawConfigParser()
    parser.read_string(user_config)
    source, base_keys = source_settings(settings.profile, environ)
    if base_keys:
        parser[profile_section(BASE_PROFILE)] = base_keys
    parser[profile_section(profile_name(settings))] = {
        "role_arn": role_arn,
        "role_session_name": f"bootcamp-{settings.participant}",
        "region": settings.region,
        **source,
    }
    return render_config(parser)


def render_config(parser: configparser.RawConfigParser) -> str:
    """Serialise `parser` in the AWS config format (multi-line values keep their indentation)."""
    lines = []
    for section in parser.sections():
        lines.append(f"[{section}]")
        lines.extend(f"{key} = {value}".replace("\n", "\n  ") for key, value in parser[section].items())
        lines.append("")
    return "\n".join(lines)


def write_private_config(text: str) -> Path:
    """Write `text` to an owner-only file in a fresh temp dir that is removed when the CLI exits."""
    directory = Path(tempfile.mkdtemp(prefix="bootcamp-aws-"))
    atexit.register(shutil.rmtree, directory, True)
    path = directory / "config"
    path.touch(mode=0o600)
    path.write_text(text)
    return path


def read_user_config() -> str:
    """The user's AWS config text ("" when they have none)."""
    path = user_config_path()
    return path.read_text() if path.is_file() else ""


def profile_session(config_file: Path, profile: str, region: str) -> boto3.Session:
    """boto3 session on `profile` from `config_file`; its role credentials refresh themselves."""
    core = botocore.session.Session()
    core.set_config_variable("config_file", str(config_file))
    return boto3.Session(botocore_session=core, profile_name=profile, region_name=region)


def frozen_credentials(session: boto3.Session) -> dict[str, str]:
    """The session's current credentials as AWS_* variables (instructor and BOOTCAMP_ROLE_ARN=none paths)."""
    creds = session.get_credentials().get_frozen_credentials()
    env = {"AWS_ACCESS_KEY_ID": creds.access_key, "AWS_SECRET_ACCESS_KEY": creds.secret_key}
    return env | ({"AWS_SESSION_TOKEN": creds.token} if creds.token else {})


class AwsAccess:
    """The CLI's own AWS session plus the environment its child processes need."""

    def __init__(self, session: boto3.Session, config_file: Path | None = None, profile: str = "") -> None:
        self.session = session
        self.config_file = config_file
        self.profile = profile

    def child_env(self, environ: dict[str, str] | None = None) -> dict[str, str]:
        """Environment for terraform/python children: the refreshing profile, or frozen keys as a fallback."""
        region = self.session.region_name
        base = os.environ if environ is None else environ
        env = {k: v for k, v in base.items() if k not in CREDENTIAL_VARS}
        env |= {"AWS_REGION": region, "AWS_DEFAULT_REGION": region}
        if self.config_file:
            return env | {"AWS_CONFIG_FILE": str(self.config_file), "AWS_PROFILE": self.profile}
        if self.session.get_credentials().method in REFRESHING_METHODS:
            return env
        return env | frozen_credentials(self.session)


def role_to_assume(base: boto3.Session, settings: Settings) -> str | None:
    """The participant role ARN to assume, or None when the base credentials already are that role."""
    if settings.role_arn:
        return settings.role_arn
    identity = base.client("sts").get_caller_identity()
    if runs_as_participant(identity["Arn"], settings.participant):
        return None
    return participant_role_arn(identity["Account"], settings.participant)


def make_access(settings: Settings, as_participant: bool = True) -> AwsAccess:
    """AWS access for this run.

    Participants get the refreshing bootcamp-<name> profile unless BOOTCAMP_ROLE_ARN is "none" or the base
    credentials already are their role (a Studio space): then the base session is used as-is, like instructors.
    """
    base = boto3.Session(profile_name=settings.profile or None, region_name=settings.region)
    role_arn = None if not as_participant or settings.role_arn.lower() == "none" else role_to_assume(base, settings)
    if role_arn is None:
        return AwsAccess(base)
    config_file = write_private_config(bootcamp_config(read_user_config(), settings, role_arn, dict(os.environ)))
    session = profile_session(config_file, profile_name(settings), settings.region)
    log.debug("Using %s as bootcamp-%s (credentials refresh automatically)", role_arn, settings.participant)
    return AwsAccess(session, config_file, profile_name(settings))


def make_session(settings: Settings, as_participant: bool = True) -> boto3.Session:
    """Just the CLI's boto3 session (auto-refreshing participant role); for scripts that start no children."""
    return make_access(settings, as_participant).session
