"""Where each participant's LiteLLM settings live: the Secrets Manager secret bootcamp/participants/<name>/litellm.

The instructor's roster sync writes it (tagged Participant=<name>); the participant CLI reads only its own copy to
learn the gateway URL. Both sides share this module so the naming can never diverge.
"""

import json

import boto3

SECRET_PREFIX = "bootcamp/participants/"
PING_MAX_TOKENS = 16
"""Smallest completion every gateway model accepts (gpt-6-luna rejects max_output_tokens below 16)."""


def secret_name(participant: str) -> str:
    """The secret holding `participant`'s LiteLLM key, gateway URL and models."""
    return f"{SECRET_PREFIX}{participant}/litellm"


def ping_payload(model: str) -> dict:
    """A tiny chat completion request (a fraction of a cent) that proves `model` answers through the gateway."""
    return {"model": model, "messages": [{"role": "user", "content": "Reply with OK"}], "max_tokens": PING_MAX_TOKENS}


def read_gateway(session: boto3.Session, participant: str) -> dict:
    """The participant's own gateway settings (base_url, models, api_key) from their tagged secret.

    Args:
        session: Session allowed to read the secret (the participant's own role, or the instructor).
        participant: Roster name.

    Returns:
        The decoded secret document.
    """
    secret = session.client("secretsmanager").get_secret_value(SecretId=secret_name(participant))
    return json.loads(secret["SecretString"])
