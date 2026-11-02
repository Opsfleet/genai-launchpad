"""One-line, actionable messages for the failures participants actually hit (instead of raw tracebacks)."""

import os

import httpx
import requests
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

HANDLED = (BotoCoreError, ClientError, requests.RequestException, httpx.HTTPError, KeyError)
ACCESS_DENIED = {"AccessDenied", "AccessDeniedException", "UnauthorizedOperation", "UnauthorizedException"}
EXPIRED = {"ExpiredToken", "ExpiredTokenException", "InvalidClientTokenId", "RequestExpired"}
GATEWAY_DOWN_STATUSES = frozenset({503})
"""What the gateway's load balancer answers while it has no running task (e.g. outside its daily hours); 502 stays
the proxy's "empty model answer" and 504 a slow model."""


def login_hint() -> str:
    """How to fix the user's AWS access key (wrong, deleted or revoked)."""
    profile = os.getenv("AWS_PROFILE", "").strip() or "bootcamp"
    return (
        f"check the access key in `aws configure --profile {profile}` (create a new one in the console under "
        "Security credentials if needed; if you cannot sign in, ask your instructor for a new invitation)"
    )


def gateway_hours_hint(active_hours: dict | None = None) -> str:
    """Why the class gateway may not answer: it is off outside its daily hours (from the gateway settings secret)."""
    if not active_hours:
        return "outside the class gateway's daily hours (see the bootcamp site) it is off; otherwise retry in a minute"
    window = f"{active_hours['start']}-{active_hours['stop']} ({active_hours['timezone']})"
    return f"the class gateway runs {window}; outside those hours it is off. Otherwise retry in a minute"


def raise_if_gateway_down(active_hours: dict | None, response: httpx.Response) -> None:
    """httpx response hook for gateway clients: a 503 becomes the active-hours hint.

    Raises:
        RuntimeError: The gateway answered with a status that means it has no running task.
    """
    status = response.status_code
    if status in GATEWAY_DOWN_STATUSES:
        raise RuntimeError(f"The LiteLLM gateway answered HTTP {status}: {gateway_hours_hint(active_hours)}.")


def explain(error: Exception) -> str:
    """Map a handled exception to a single actionable line."""
    if isinstance(error, ClientError):
        return explain_client_error(error)
    if isinstance(error, NoCredentialsError):
        return "No AWS credentials found: run `aws configure --profile bootcamp` and set AWS_PROFILE=bootcamp in .env."
    if isinstance(error, BotoCoreError):
        return f"AWS error: {error}"
    if isinstance(error, httpx.HTTPStatusError):
        return explain_status(error)
    if isinstance(error, httpx.HTTPError | requests.RequestException):
        return f"Network request failed ({error}); check your connection or VPN and retry."
    return f"Missing value {error}: your stack is not provisioned yet; run `uv run bootcamp.py up 0` first."


def explain_status(error: httpx.HTTPStatusError) -> str:
    """An HTTP error status; 503 adds the gateway's daily-hours hint instead of the (HTML) body."""
    status = error.response.status_code
    if status in GATEWAY_DOWN_STATUSES:
        return f"{error.request.url} returned {status} (if this is the LiteLLM gateway, {gateway_hours_hint()})."
    return f"{error.request.url} returned {status}: {error.response.text[:300]}"


def explain_client_error(error: ClientError) -> str:
    """AWS API errors: expired logins, isolation denials, everything else verbatim."""
    code = error.response.get("Error", {}).get("Code", "")
    operation = error.operation_name
    if code in EXPIRED:
        return f"Your AWS credentials have expired: {login_hint()}, then retry."
    if code in ACCESS_DENIED and operation == "AssumeRole":
        return (
            "You cannot assume your bootcamp-participant role: check PARTICIPANT in .env and that the "
            "instructor has added you to roster.json and run `uv run instructor.py up`."
        )
    if code in ACCESS_DENIED:
        return (
            f"AWS denied {operation}: participant roles may only touch their own awsworkshop-<name>-* resources "
            "(tag isolation); check PARTICIPANT in .env, or ask the instructor."
        )
    return f"AWS {operation} failed: {error}"
