Task 0 · 8 tasks
# Setup check
Confirm your setup, your database copy and your model access before Alice's first request lands.
20 minEasy
Alice’s ask
## The “Getting Started” challenge
Welcome to **DataStream Corp**, a 1,200-person tech company whose CEO, **Alice Chen**, wants an AI assistant that actually knows the business. You are the developer she hired to build it.
Before you write a line of agent code, make sure the plumbing works: the code, your AWS identity, the company database and a route to a model.
You
## Build it
### Finish the setup
Follow Before you start on your laptop or in your browser workspace until `uv run bootcamp.py doctor` shows every line with ✔, then run everything below from `datastream-bootcamp`. Every `bootcamp.py` command runs as your workshop role `bootcamp-participant-<name>`, which is what the platform recognises you by.
### Meet your model gateway
Every model call in this bootcamp goes through the **Opsfleet LiteLLM gateway**. You never call Bedrock directly: your role can't. And there is **no API key**: each request carries a presigned AWS identity, and the gateway maps your role to your personal budget (default **$10**), which is plenty. Cost depends on the model. With `gpt-6-luna` or `claude-haiku-5-5`, Phase 1 about $0.04-0.25 and Phase 2 with the optional pages about $0.05-0.30; `claude-sonnet-5-5` costs about 20 times more. Larger models cost far more; `uv run bootcamp.py llm budget` shows your spend any time.

terminal:
```bash
uv run bootcamp.py llm          # summary: gateway URL, models, your budget
uv run bootcamp.py llm models   # the models you may use, with prices per million tokens
uv run bootcamp.py llm budget   # spent, limit and what is left (any time during the day)
```

If this prints `LITELLM_BASE_URL`, `MODELS`, your `MODEL_ID` and your `BUDGET` (spent of max), the role assumption and keyless identity both work. If your budget runs out, model calls fail with HTTP 429 `budget_exceeded`; ask your instructor for a top-up.
The gateway runs **08:00-22:00 Israel time** (Asia/Jerusalem) every day; work any time within that window. Outside it the gateway is off and model calls answer HTTP 503 with a one-line hint; inside it, a 503 means the gateway is restarting, so retry in a minute.
Your instructor chooses which Bedrock models the class may use, so the list differs between classes. `uv run bootcamp.py llm models` shows the models enabled for you: each one's real Bedrock name, its price per million tokens, and a NOTES column marking the _class default_, the models your instructor _suggests_, known quirks, and which model it falls back to.
`MODEL_ID` is optional: leave it empty to use the class default. To switch, set `MODEL_ID=<model>` in `.env` (any name from `llm models`), or for a single command (`MODEL_ID=<model> uv run bootcamp.py ...`). Prefer the suggested models; very small models often fail the tool-use tasks.
Some models have a fallback: if that model is down, the gateway retries it and then answers with its fallback model instead (still from your budget, at the fallback's price); `llm models` shows it as `falls back to ...`. If a model stays unavailable, the scripts print a one-line `[gateway]` hint: retry in a minute, or set `MODEL_ID` to another model, and tell your instructor if it persists.
### Run the setup check

terminal:
```bash
uv run bootcamp.py phase1 t0
```

It downloads _your own copy_ of the DataStream SQLite database into `phase1/`, counts employees, checks your AWS identity, builds a test agent and makes a real model call through the gateway.
Phase 1 adds a few rows to your copy: an empty **Research** department and six _terminated_ employees (`status = 'terminated'`). Throughout Phase 1, **headcount means active employees** (`status = 'active'`): Engineering 481, Sales 360, Marketing 180, HR 84, Finance 60, Operations 36 and Research 0: **1,201** in total. Counting every row gives 1,207, which is how you spot an agent that forgot the filter.
## Check your work
Phase 1 has no automated test: you check it by running the task and looking for the result below.
Every line starts with `PASS`, including _LiteLLM gateway_, ending with _Setup complete, ready for Task 1_. The database line reads `1201 active employees (1207 in total); departments: Engineering, Sales, Marketing, HR, Finance, Operations, Research`.

terminal:
```bash
uv run bootcamp.py phase1 t0
```

#### Under the hood
`bootcamp.py phase1 t0` runs `phase1/t0_setup.py` with your `.env` loaded and your participant role assumed. The shared helpers live in `phase1/common.py`; the one that matters most is the model factory:

phase1/common.py (model factory):
```python
MODEL_ID = os.getenv("MODEL_ID", "")
"""Set by `bootcamp.py phase1` (your .env MODEL_ID, else the class default)."""

def make_model() -> OpenAIModel:
    """Every task talks to the model through the Opsfleet LiteLLM gateway (keyless, budgeted per participant)."""
    return litellm_gateway.make_model(MODEL_ID)
```

The heavy lifting is in `shared/litellm_gateway.py`, which Phase 2 reuses unchanged:

shared/litellm_gateway.py (excerpt):
```python
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

def make_model(model_id: str | None = None, base_url: str | None = None, **params) -> OpenAIModel:
    """Strands model routed through the gateway; reads MODEL_ID / LITELLM_BASE_URL / LITELLM_API_KEY from env."""
    return GatewayModel(
        base_url or os.environ["LITELLM_BASE_URL"],
        os.getenv("LITELLM_API_KEY"),
        model_id=model_id or os.environ["MODEL_ID"],
        params=params or None,
    )
```

Strands' `OpenAIModel` speaks the OpenAI chat-completions API, which LiteLLM exposes and translates to Bedrock. `GatewayModel` is a thin subclass: instead of a key, its `StsIdentityAuth` hook adds the `X-Amz-Sts-Identity-Url` header, a presigned STS `GetCallerIdentity` URL signed with your own credentials. The gateway replays it, learns you are `bootcamp-participant-alice`, and bills alice's budget. `LITELLM_BASE_URL` is filled in by the CLI; `LITELLM_API_KEY` is optional, only for tools that can't do keyless auth.
