"""Connect Strands agents to the bootcamp LiteLLM gateway.

Keyless by default: every request carries a presigned STS GetCallerIdentity URL made with the caller's own
AWS credentials (laptop: the participant role; AgentCore Runtime: the agent's execution role). The gateway
replays it against STS to learn who is calling and bills that participant's LiteLLM budget, so no API key
ever lives in code, .env files or runtime config. Set LITELLM_API_KEY to use a virtual key instead.
Copied into every Phase 2 app zip by bootcamp_cli.build so the deployed agent uses the exact same client.

The gateway already retries answer-less model responses; as a last guard, `GatewayModel` raises
`EmptyModelResponseError` when a reply still carries no text, no tool call and no output tokens, so an agent fails
loudly instead of treating "" as an answer.
"""

import json
import os
import time
from collections.abc import AsyncGenerator
from typing import Any

import boto3
import httpx
from strands.models.openai import OpenAIModel
from strands.types.streaming import StreamEvent

IDENTITY_HEADER = "X-Amz-Sts-Identity-Url"
PRESIGN_SECONDS = 120
REFRESH_MARGIN_SECONDS = 30
KEYLESS_PLACEHOLDER = "keyless"


class StsIdentityAuth(httpx.Auth):
    """Adds a fresh presigned STS identity URL to each request (cached until shortly before it expires).

    Short-lived (2 min) because the URL is a bearer credential for your LLM budget until it expires.
    The URL must be signed for GET: STS is a query-protocol API, so boto3 presigns for POST by default and the
    gateway's GET replay would fail with SignatureDoesNotMatch.
    """

    def __init__(self, session: boto3.Session | None = None, region: str | None = None) -> None:
        self._session = session or boto3.Session()
        self._region = region or self._session.region_name or os.getenv("AWS_REGION", "us-east-1")
        self._url = ""
        self._expires_at = 0.0

    def identity_url(self) -> str:
        if time.time() > self._expires_at - REFRESH_MARGIN_SECONDS:
            sts = self._session.client("sts", region_name=self._region)
            self._url = sts.generate_presigned_url("get_caller_identity", ExpiresIn=PRESIGN_SECONDS, HttpMethod="GET")
            self._expires_at = time.time() + PRESIGN_SECONDS
        return self._url

    def auth_flow(self, request: httpx.Request):
        request.headers[IDENTITY_HEADER] = self.identity_url()
        yield request


class EmptyModelResponseError(RuntimeError):
    """The model finished without text, tool calls or output tokens (an upstream failure, not an answer)."""


def _as_text(block: dict) -> dict:
    """A toolUse/toolResult content block as an equivalent text block; any other block unchanged."""
    if "toolUse" in block:
        use = block["toolUse"]
        return {"text": f"[called tool {use['name']} with {json.dumps(use.get('input', {}))}]"}
    if "toolResult" in block:
        parts = block["toolResult"].get("content", [])
        return {"text": "[tool result] " + " ".join(p.get("text") or json.dumps(p.get("json", "")) for p in parts)}
    return block


def has_output(event: StreamEvent) -> bool:
    """Whether a Strands stream event carries model output: a content block (text, tool use, reasoning) or tokens."""
    usage = event.get("metadata", {}).get("usage", {})
    return "contentBlockStart" in event or "contentBlockDelta" in event or usage.get("outputTokens", 0) > 0


class GatewayModel(OpenAIModel):
    """Strands OpenAIModel bound to the gateway.

    Strands opens (and closes) a fresh OpenAI client per request from `_resolve_client_args()`, so the keyless
    httpx client must be created per request too; the STS signer (and its cached URL) is shared.
    """

    def __init__(self, base_url: str, api_key: str | None = None, session: boto3.Session | None = None, **config):
        super().__init__(
            client_args={"base_url": f"{base_url.rstrip('/')}/v1", "api_key": api_key or KEYLESS_PLACEHOLDER}, **config
        )
        self._auth = None if api_key else StsIdentityAuth(session)

    def _resolve_client_args(self) -> dict:
        args = dict(self.client_args)
        if self._auth:
            args["http_client"] = httpx.AsyncClient(auth=self._auth, timeout=600)
        return args

    def format_request(self, messages: list, tool_specs: list | None = None, *args: Any, **kwargs: Any) -> dict:
        """OpenAIModel's request; a call without tools gets its history's tool blocks as plain text.

        Bedrock rejects tool calls in the history of a request that defines no tools ("toolConfig field must be
        defined"), and Strands makes exactly such calls, e.g. to summarize a conversation. Rendering the old tool
        calls and results as text keeps their content for the model without needing any tool definition.
        """
        if not tool_specs:
            messages = [
                {**message, "content": [_as_text(block) for block in message["content"]]} for message in messages
            ]
        return super().format_request(messages, tool_specs, *args, **kwargs)

    async def stream(self, *args: Any, **kwargs: Any) -> AsyncGenerator[StreamEvent]:
        """Stream like OpenAIModel, but raise `EmptyModelResponseError` if the reply carried no output at all."""
        produced = False
        async for event in super().stream(*args, **kwargs):
            produced = produced or has_output(event)
            yield event
        if not produced:
            raise EmptyModelResponseError("the model returned an empty response (no text, tool call or tokens)")


MODEL_DOWN_MARKERS = (
    "serviceunavailable",
    "unable to process your request",
    "model access",
    "not available for this account",
    "don't have access to the model",
    "model identifier is invalid",
)
"""Bedrock errors (as LiteLLM relays them) that mean the model itself is unavailable, not a mistake by the caller."""
MODELS_HINT = "uv run bootcamp.py llm models"
"""Lists the gateway's models with prices and suggestions."""


def model_unavailable(model: str, error_text: str) -> str | None:
    """A one-line explanation when a gateway error says `model` is unavailable, otherwise None."""
    if not any(marker in error_text.lower() for marker in MODEL_DOWN_MARKERS):
        return None
    return (
        f"model {model} is unavailable right now (Bedrock). Retry in a minute, or set MODEL_ID in .env to "
        f"another model from `{MODELS_HINT}`; if it persists, tell your instructor."
    )


GATEWAY_DOWN_STATUSES = frozenset({503})
"""What the gateway's load balancer answers while it has no running task (e.g. outside its daily hours)."""


def gateway_down(status_code: int | None) -> str | None:
    """A one-line explanation when an HTTP status means the gateway itself is not answering, otherwise None."""
    if status_code not in GATEWAY_DOWN_STATUSES:
        return None
    return (
        f"the class gateway is not answering (HTTP {status_code}): outside the class gateway's daily hours "
        "(see the bootcamp site) it is off; otherwise retry in a minute."
    )


def make_model(model_id: str | None = None, base_url: str | None = None, **params) -> OpenAIModel:
    """Strands model routed through the gateway; reads MODEL_ID / LITELLM_BASE_URL / LITELLM_API_KEY from env."""
    return GatewayModel(
        base_url or os.environ["LITELLM_BASE_URL"],
        os.getenv("LITELLM_API_KEY"),
        model_id=model_id or os.environ["MODEL_ID"],
        params=params or None,
    )
