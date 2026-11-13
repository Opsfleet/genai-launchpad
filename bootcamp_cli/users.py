"""End-user sign-in: your agent trusts only a verified Cognito user token, never a caller-chosen actor name.

- Story users (`alice-chen`, `jordan-lee`) are created by your stack in task 0. Their generated passwords are SSM
  SecureString parameters under `users_parameter_path`, which only your participant role can read. `invoke --actor`
  signs in with that password (Cognito `InitiateAuth`, USER_PASSWORD_AUTH), as any login page would.
- Any other `--actor` name is a test user: the CLI acts as your user pool's admin, creates it on first use and sets a
  fresh password before each sign-in.
- `test` and `eval` use throwaway users (`temporary_users`) so no long-term memory from earlier runs can answer for
  them. They are deleted afterwards. Their memory records stay in your memory until `down`.
"""

import base64
import json
import logging
import secrets
import uuid
from collections.abc import Iterator
from contextlib import contextmanager

import boto3

log = logging.getLogger(__name__)

PASSWORD_SUFFIX = "Aa1!"
"""Appended to a random token so a generated password meets any Cognito password policy."""


def jwt_claims(token: str) -> dict:
    """The claims of a JWT: its middle base64url part, decoded WITHOUT checking the signature (for inspection only)."""
    payload = token.split(".")[1]
    return json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))


def story_users(out: dict) -> list[str]:
    """The users your stack created (terraform output `story_users`, comma-separated)."""
    return [name for name in str(out.get("story_users", "")).split(",") if name]


def user_token(session: boto3.Session, out: dict, username: str) -> str:
    """An access token for `username`: a story user's stored password, or a fresh admin-set one for a test user."""
    if username in story_users(out):
        password = stored_password(session, out, username)
    else:
        log.info("Signing in as test user %s (created in your user pool on first use)", username)
        password = admin_password(session, out, username)
    return sign_in(session, out, username, password)


def stored_password(session: boto3.Session, out: dict, username: str) -> str:
    """A story user's password from SSM Parameter Store (decrypted)."""
    name = f"{out['users_parameter_path']}/{username}"
    return session.client("ssm").get_parameter(Name=name, WithDecryption=True)["Parameter"]["Value"]


def sign_in(session: boto3.Session, out: dict, username: str, password: str) -> str:
    """Sign in through the pool's user app client (no client secret) and return the user's access token."""
    response = session.client("cognito-idp").initiate_auth(
        ClientId=out["user_client_id"],
        AuthFlow="USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": username, "PASSWORD": password},
    )
    return response["AuthenticationResult"]["AccessToken"]


def admin_password(session: boto3.Session, out: dict, username: str) -> str:
    """Create `username` in your user pool when it is new, then give it a fresh permanent password."""
    cognito, pool_id = session.client("cognito-idp"), out["pool_id"]
    password = secrets.token_urlsafe(24) + PASSWORD_SUFFIX
    try:
        cognito.admin_create_user(UserPoolId=pool_id, Username=username, MessageAction="SUPPRESS")
        log.debug("Created user %s in your user pool", username)
    except cognito.exceptions.UsernameExistsException:
        pass
    cognito.admin_set_user_password(UserPoolId=pool_id, Username=username, Password=password, Permanent=True)
    return password


def delete_user(session: boto3.Session, out: dict, username: str) -> None:
    """Remove a throwaway user (already gone is fine)."""
    cognito = session.client("cognito-idp")
    try:
        cognito.admin_delete_user(UserPoolId=out["pool_id"], Username=username)
    except cognito.exceptions.UserNotFoundException:
        pass


@contextmanager
def temporary_users(session: boto3.Session, out: dict, count: int, prefix: str) -> Iterator[list[tuple[str, str]]]:
    """`count` brand-new users as (username, access token), deleted again on exit.

    Args:
        session: Your participant session (admin of your own user pool).
        out: Terraform outputs (`pool_id`, `user_client_id`).
        count: How many users.
        prefix: Username prefix, e.g. `check` or `eval`, followed by 8 random hex characters.
    """
    names = [f"{prefix}-{uuid.uuid4().hex[:8]}" for _ in range(count)]
    try:
        yield [(name, sign_in(session, out, name, admin_password(session, out, name))) for name in names]
    finally:
        for name in names:
            delete_user(session, out, name)
