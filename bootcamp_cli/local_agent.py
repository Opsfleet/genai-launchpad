"""Run `phase2/app/agent/agent.py` on this machine against your real Memory, Gateway and model (`invoke --local`).

The local agent gets the same environment variables Terraform sets on the runtime (from your stack's outputs) and your
own AWS credentials instead of the runtime role. The CLI then plays the runtime's part: each request carries a
workload access token for `awsworkshop-<you>-local` (a workload identity created at stage 3) in the
`WorkloadAccessToken` header, which `BedrockAgentCoreApp` hands to `@requires_access_token` to fetch the Gateway token.
Nothing verifies the caller's token locally (the runtime's JWT authorizer does that once deployed), so the CLI always
signs in as a real user, the same way it does for the deployed agent.
"""

import logging
import os
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import boto3
import requests

from bootcamp_cli.aws import CREDENTIAL_VARS, frozen_credentials
from bootcamp_cli.config import ROOT

log = logging.getLogger(__name__)

AGENT_DIR = ROOT / "phase2" / "app" / "agent"
SHARED_DIR = ROOT / "shared"
RUN_DIR = ROOT / ".build" / "local-agent"
LOG_FILE = RUN_DIR / "agent.log"
PORT = 8080
URL = f"http://127.0.0.1:{PORT}"
START_TIMEOUT = 300
"""Seconds to wait for /ping: the first run installs the agent's packages (~1 min), later runs start in seconds."""
OPTIONAL_TOOL_IDS = {"CODE_INTERPRETER_ID": "aws.codeinterpreter.v1", "BROWSER_ID": "aws.browser.v1"}
"""The AWS-managed sandboxes the runtime uses when ENABLE_CODE_INTERPRETER / ENABLE_BROWSER are on (stage 4+)."""
RUNTIME_ONLY_VARS = ("TRUST_ACTOR_HEADER", "GUARDRAIL_ID", "GUARDRAIL_VERSION", "CODE_INTERPRETER_ID", "BROWSER_ID")
"""Variables only your stack decides: never inherited from .env or the shell, set from the outputs instead."""


def agent_env(out: dict, model_id: str) -> dict[str, str]:
    """The runtime's environment variables (terraform/participant/task4_agent_runtime.tf), from stack outputs.

    Raises:
        RuntimeError: The stack has no memory yet (the agent needs Gateway and Memory: stage 3).
    """
    if not out.get("memory_id") or not out.get("local_workload_identity"):
        raise RuntimeError("The local agent needs your Gateway and Memory: run `uv run bootcamp.py up 3` first.")
    env = {
        "MODEL_ID": model_id,
        "LITELLM_BASE_URL": out["litellm_base_url"],
        "GATEWAY_URL": out["gateway_url"],
        "MEMORY_ID": out["memory_id"],
        "MEMORY_STRATEGY_ID": out["memory_strategy_id"],
        "MEMORY_PREFERENCE_STRATEGY_ID": out["memory_preference_strategy_id"],
        "MEMORY_SUMMARY_STRATEGY_ID": out["memory_summary_strategy_id"],
        "CREDENTIAL_PROVIDER_NAME": out["credential_provider_name"],
        "OAUTH_SCOPE": out["oauth_scope"],
    }
    return env | _optional_env(out)


def _optional_env(out: dict) -> dict[str, str]:
    """Sandbox tools, guardrail and the insecure actor-header experiment, exactly as your stack has them."""
    flags = {"CODE_INTERPRETER": out.get("code_interpreter_enabled"), "BROWSER": out.get("browser_enabled")}
    env = {f"{name}_ENABLED": str(on is True).lower() for name, on in flags.items()}
    env |= {var: tool for var, tool in OPTIONAL_TOOL_IDS.items() if flags[var.removesuffix("_ID")] is True}
    if out.get("guardrail_id"):
        env |= {"GUARDRAIL_ID": out["guardrail_id"], "GUARDRAIL_VERSION": str(out["guardrail_version"])}
    return env | ({"TRUST_ACTOR_HEADER": "true"} if out.get("trust_actor_header") is True else {})


def process_env(out: dict, model_id: str, session: boto3.Session) -> dict[str, str]:
    """This shell's environment minus AWS credentials and runtime-only settings, plus your role and the agent's."""
    dropped = (*CREDENTIAL_VARS, *RUNTIME_ONLY_VARS)
    base = {name: value for name, value in os.environ.items() if name not in dropped}
    paths = os.pathsep.join(str(path) for path in (AGENT_DIR, SHARED_DIR))
    region = session.region_name
    aws = {"AWS_REGION": region, "AWS_DEFAULT_REGION": region} | frozen_credentials(session)
    return base | aws | agent_env(out, model_id) | {"PYTHONPATH": paths, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"}


def workload_token(out: dict, session: boto3.Session) -> str:
    """A workload access token for your local workload identity: what the runtime passes its agent on every call."""
    data = session.client("bedrock-agentcore")
    return data.get_workload_access_token(workloadName=out["local_workload_identity"])["workloadAccessToken"]


def command() -> list[str]:
    """`uv run` the agent in its own environment, with the exact package versions the runtime gets."""
    requirements = str(AGENT_DIR / "requirements.txt")
    return ["uv", "run", "--no-project", "--python", "3.13", "--with-requirements", requirements, "python",
            str(AGENT_DIR / "agent.py")]  # fmt: skip


@contextmanager
def running(out: dict, model_id: str, session: boto3.Session) -> Iterator[dict[str, str]]:
    """Start the agent on localhost:8080 and stop it afterwards (its output: agent.log).

    Yields the outputs that aim `agentcore.invoke_agent_body` / `stream_agent` at it: `local_agent_url` and
    `local_workload_token`.

    Raises:
        RuntimeError: Port 8080 is taken, or the agent exited or did not answer /ping in time.
    """
    if _answers_ping():
        raise RuntimeError(f"Port {PORT} is already in use: stop whatever runs there (another local agent?).")
    env, token = process_env(out, model_id, session), workload_token(out, session)
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    log.info("Starting your agent locally (the first run installs its packages, ~1 min; log: %s)", _shown(LOG_FILE))
    with LOG_FILE.open("w") as log_file:
        agent = subprocess.Popen(command(), cwd=RUN_DIR, env=env, stdout=log_file, stderr=subprocess.STDOUT)
    try:
        _wait_until_ready(agent)
        yield {"local_agent_url": URL, "local_workload_token": token}
    finally:
        _stop(agent)


def _stop(agent: subprocess.Popen) -> None:
    """Stop the agent and its children: on Windows `terminate()` ends only `uv`, leaving python bound to the port."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(agent.pid), "/T", "/F"], capture_output=True, check=False)
    else:
        agent.terminate()
    agent.wait(timeout=10)


def _wait_until_ready(agent: subprocess.Popen) -> None:
    """Poll /ping until the agent answers; fail with the log's last lines when it exits or times out."""
    deadline = time.time() + START_TIMEOUT
    while time.time() < deadline:
        if agent.poll() is not None:
            raise RuntimeError(f"Your local agent exited (code {agent.returncode}):\n{log_tail()}")
        if _answers_ping():
            return
        time.sleep(1)
    raise RuntimeError(f"Your local agent did not start within {START_TIMEOUT}s:\n{log_tail()}")


def _answers_ping() -> bool:
    """Whether something answers the agent's health check on the local port."""
    try:
        return requests.get(f"{URL}/ping", timeout=2).ok
    except requests.RequestException:
        return False


def log_tail(lines: int = 15) -> str:
    """The last lines of the local agent's output (where its errors and tracebacks go)."""
    text = LOG_FILE.read_text(errors="replace") if LOG_FILE.exists() else ""
    return "\n".join(text.splitlines()[-lines:]) or "(no output)"


def _shown(path: Path) -> str:
    """`path` relative to the repo root, for messages."""
    return str(path.relative_to(ROOT))
