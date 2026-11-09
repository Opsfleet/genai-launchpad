"""Participant pre-flight before day 1 (`uv run bootcamp.py doctor`): is this laptop ready for the bootcamp?

Checks the local toolchain (OS, Python, uv, Terraform, AWS CLI, disk), the Phase 1 database copy, the `.env`
settings, the AWS chain (your own credentials, then the bootcamp-participant-<you> role, your gateway secret, one tiny
keyless LiteLLM call and your remaining budget, and that direct Bedrock is denied as designed) and the network
endpoints the tasks reach. It creates nothing, finishes in well under 30 s (checks run concurrently) and exits 1
when anything failed.
"""

import logging
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
from collections.abc import Callable
from contextlib import closing
from functools import partial
from pathlib import Path

import boto3
import httpx
from botocore.exceptions import ClientError

from bootcamp_cli import report
from bootcamp_cli.aws import make_access
from bootcamp_cli.config import ROOT, Settings, load_settings, participant_problem
from bootcamp_cli.errors import ACCESS_DENIED, GATEWAY_DOWN_STATUSES, HANDLED, explain, gateway_hours_hint
from bootcamp_cli.gateway_key import PING_MAX_TOKENS, ping_payload, read_gateway
from bootcamp_cli.report import Result, failed, passed, skipped, warned

PYTHON = (3, 13)
MIN_FREE_GIB = 2.0
NETWORK_TIMEOUT = 6.0
LLM_TIMEOUT = 25.0
TOOL_TIMEOUT = 15.0
DIRECT_BEDROCK_MODEL = "amazon.nova-micro-v1:0"
"""Cheap and enabled in most accounts, so a denial proves the IAM deny rather than missing model access."""
TERRAFORM_VERSIONS = ROOT / "terraform" / "participant" / "versions.tf"
PHASE1_DB = ROOT / "phase1" / "datastream_corp.db"
FRESH_DB = "delete phase1/datastream_corp.db, then run `uv run bootcamp.py phase1 t0`"
SUPPORTED_SYSTEMS = {"Darwin": "macOS", "Linux": "Linux", "Windows": "Windows"}
NETWORK_TARGETS = {
    "Cognito": "https://cognito-idp.{region}.amazonaws.com/",
    "National Weather Service": "https://api.weather.gov/",
    "GitHub": "https://github.com/",
}
"""Endpoints the tasks reach from the laptop: Cognito tokens (Phase 2), the weather tool (Phase 1), the repository."""
INSTALL = {
    "uv": "install uv: https://docs.astral.sh/uv/getting-started/installation/",
    "terraform": "install Terraform: https://developer.hashicorp.com/terraform/install",
    "aws": "install AWS CLI v2: https://docs.aws.amazon.com/cli/latest/userguide/getting-started-install.html",
}
ASK_INSTRUCTOR = "ask the instructor to add you to roster.json and run `uv run instructor.py up`"
GATEWAY_FIXES = {
    401: "the gateway does not know your role yet: ask the instructor to run `uv run instructor.py keys`",
    429: "your LiteLLM budget is used up: ask the instructor to raise it (roster.json, then `instructor.py keys`)",
}


def version_tuple(text: str) -> tuple[int, ...]:
    """(1, 10, 2) from '1.10.2' or 'v1.10.2' (non-numeric parts ignored)."""
    return tuple(int(part) for part in re.findall(r"\d+", text)[:3])


def required_terraform() -> str:
    """The participant stack's `required_version` floor, e.g. '1.9' from '>= 1.9'."""
    match = re.search(r'required_version\s*=\s*">=\s*([\d.]+)"', TERRAFORM_VERSIONS.read_text())
    return match.group(1) if match else "0"


def tool_output(command: list[str]) -> str | None:
    """First line of `command`'s output, or None when the program is not installed."""
    if shutil.which(command[0]) is None:
        return None
    done = subprocess.run(command, capture_output=True, text=True, timeout=TOOL_TIMEOUT, check=False)
    output = (done.stdout or done.stderr).strip()
    return output.splitlines()[0] if output else ""


def check_os() -> Result:
    """macOS, Linux and Windows are supported; anything else is a warning."""
    system = platform.system()
    detail = f"{SUPPORTED_SYSTEMS.get(system, system)} {platform.release()} ({platform.machine()})"
    if system in SUPPORTED_SYSTEMS:
        return passed("Operating system", detail)
    return warned("Operating system", f"{detail} is untested", "use macOS, Linux or Windows if anything fails")


def check_python() -> Result:
    """The interpreter running the CLI is the pinned Python (uv picks it from .python-version)."""
    found = ".".join(map(str, sys.version_info[:3]))
    if sys.version_info[:2] == PYTHON:
        return passed("Python", found)
    wanted = ".".join(map(str, PYTHON))
    return failed("Python", f"{found}, need {wanted}", f"run commands with `uv run` (uv installs Python {wanted})")


def check_uv() -> Result:
    """uv is on PATH (every command runs through `uv run`)."""
    found = tool_output(["uv", "--version"])
    return passed("uv", found) if found else failed("uv", "not found on PATH", INSTALL["uv"])


def check_terraform() -> Result:
    """Terraform is installed and at least the participant stack's required_version."""
    floor, found = required_terraform(), tool_output(["terraform", "version"])
    if found is None:
        return failed("Terraform", "not found on PATH", INSTALL["terraform"])
    if version_tuple(found) < version_tuple(floor):
        return failed("Terraform", f"{found}, need >= {floor}", INSTALL["terraform"])
    return passed("Terraform", f"{found} (>= {floor})")


def check_aws_cli() -> Result:
    """AWS CLI v2 is installed (for `aws configure` and the console-free checks)."""
    found = tool_output(["aws", "--version"])
    if found is None:
        return failed("AWS CLI", "not found on PATH", INSTALL["aws"])
    if not found.startswith("aws-cli/2"):
        return failed("AWS CLI", f"{found}, need v2", INSTALL["aws"])
    return passed("AWS CLI", found.split()[0])


def check_disk() -> Result:
    """Enough free disk for the Phase 2 app builds and terraform providers."""
    free_gib = shutil.disk_usage(ROOT).free / 2**30
    detail = f"{free_gib:.1f} GiB free"
    if free_gib >= MIN_FREE_GIB:
        return passed("Disk space", detail)
    return failed("Disk space", f"{detail}, need {MIN_FREE_GIB:g} GiB for builds", "free some disk space")


def check_network(name: str, url: str) -> Result:
    """Any HTTP answer proves the endpoint is reachable (status codes do not matter here)."""
    try:
        status = httpx.get(url, timeout=NETWORK_TIMEOUT, headers={"User-Agent": "bootcamp-doctor"}).status_code
    except httpx.HTTPError as error:
        fix = "check your connection, VPN or corporate proxy (it must allow this HTTPS host)"
        return failed(f"Network: {name}", f"{url} unreachable ({type(error).__name__})", fix)
    return passed(f"Network: {name}", f"{url} answered HTTP {status}")


def network_checks(region: str) -> list[Callable[[], Result]]:
    """One check per endpoint the tasks reach from the laptop."""
    return [partial(check_network, name, url.format(region=region)) for name, url in NETWORK_TARGETS.items()]


def check_database(path: Path = PHASE1_DB) -> Result:
    """Phase 1's own copy of the database: downloaded, and not the empty file `sqlite3.connect` leaves behind when
    something opens the database before Task 0 has downloaded it. Opened read-only, so this check never creates it."""
    if not path.exists():
        return warned("Phase 1 database", "not downloaded yet", "run `uv run bootcamp.py phase1 t0`")
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
            active = conn.execute("SELECT COUNT(*) FROM employees WHERE status = 'active'").fetchone()[0]
    except sqlite3.DatabaseError as error:
        return failed("Phase 1 database", f"{path.name} is unusable ({error})", FRESH_DB)
    return passed("Phase 1 database", f"{active:,} active employees")


def local_checks() -> list[Callable[[], Result]]:
    """Toolchain and disk checks (no AWS, no network)."""
    return [check_os, check_python, check_uv, check_terraform, check_aws_cli, check_disk, check_database]


class AwsChain:
    """The dependent AWS checks: each step needs the previous one, so a failure skips the rest."""

    STEPS = (
        "AWS credentials",
        ".env PARTICIPANT",
        "Participant role",
        "Gateway settings",
        "LiteLLM call",
        "LiteLLM budget",
        "Bedrock",
    )

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.results: list[Result] = []
        self.session: boto3.Session | None = None
        self.base_url = ""
        self.model_id = settings.model_id
        self.active_hours: dict | None = None

    def run(self) -> list[Result]:
        """Run the steps in order; after the first failure the remaining steps are reported as skipped."""
        steps = (self.credentials, self.participant, self.participant_role, self.gateway, self.llm_call, self.bedrock)
        for step in steps:
            if not self._record(step):
                break
        done = {result.name for result in self.results}
        return self.results + [skipped(name, "an earlier AWS check failed") for name in self.STEPS if name not in done]

    def _record(self, step: Callable[[], list[Result]]) -> bool:
        """Run one step, keep its results, and tell whether the chain may continue."""
        try:
            outcome = step()
        except HANDLED as error:
            outcome = [failed(self.STEPS[len(self.results)], explain(error), _aws_fix(error))]
        self.results += outcome
        return all(result.status is not report.Status.FAIL for result in outcome)

    def credentials(self) -> list[Result]:
        """Your own AWS access key (profile or environment variables) works."""
        base = boto3.Session(profile_name=self.settings.profile or None, region_name=self.settings.region)
        arn = base.client("sts").get_caller_identity()["Arn"]
        profile = self.settings.profile or "environment variables"
        return [passed("AWS credentials", f"{arn} (from {profile})")]

    def participant(self) -> list[Result]:
        """PARTICIPANT is set and well-formed."""
        return [participant_check(self.settings)]

    def participant_role(self) -> list[Result]:
        """The CLI can assume bootcamp-participant-<you> (proves you are on the deployed roster)."""
        self.session = make_access(self.settings).session
        arn = self.session.client("sts").get_caller_identity()["Arn"]
        return [passed("Participant role", f"assumed {arn.split('/')[1]} in {self.settings.region}")]

    def gateway(self) -> list[Result]:
        """Your gateway settings secret is readable in BOOTCAMP_REGION."""
        try:
            gateway = read_gateway(self.session, self.settings.participant)
            self.base_url = gateway["base_url"]
            self.model_id = self.settings.model_id or gateway.get("default_model", "")
            self.active_hours = gateway.get("active_hours")
        except ClientError as error:
            fix = f"{ASK_INSTRUCTOR}, or fix BOOTCAMP_REGION ({self.settings.region}) in .env"
            return [failed("Gateway settings", f"no LiteLLM settings readable ({_code(error)})", fix)]
        return [passed("Gateway settings", self.base_url)]

    def llm_call(self) -> list[Result]:
        """One tiny keyless completion through LiteLLM, then your remaining budget."""
        import litellm_gateway

        auth = litellm_gateway.StsIdentityAuth(self.session)
        with httpx.Client(base_url=self.base_url, auth=auth, timeout=LLM_TIMEOUT) as client:
            try:
                started = _ping_model(client, self.model_id)
            except httpx.HTTPStatusError as error:
                return [self._call_failure(error)]
            info = client.get("/key/info").raise_for_status().json().get("info", {})
        return [passed("LiteLLM call", f"{self.model_id} answered in {started:.1f} s"), budget_result(info)]

    def _call_failure(self, error: httpx.HTTPStatusError) -> Result:
        """A failed ping: the gateway is off (daily hours) or Bedrock reports the model unavailable; else re-raise."""
        import litellm_gateway

        status = error.response.status_code
        down = litellm_gateway.model_unavailable(self.model_id, error.response.text)
        if down is not None:
            return failed("LiteLLM call", f"HTTP {status}: {down}", ASK_INSTRUCTOR)
        if status in GATEWAY_DOWN_STATUSES:
            hint = gateway_hours_hint(self.active_hours)
            return failed("LiteLLM call", f"HTTP {status}: the gateway is not answering", hint)
        raise error

    def bedrock(self) -> list[Result]:
        """Direct Bedrock must be denied: every model call goes through the gateway."""
        runtime = self.session.client("bedrock-runtime")
        message, limits = [{"role": "user", "content": [{"text": "OK"}]}], {"maxTokens": PING_MAX_TOKENS}
        try:
            runtime.converse(modelId=DIRECT_BEDROCK_MODEL, messages=message, inferenceConfig=limits)
        except ClientError as error:
            if _code(error) in ACCESS_DENIED:
                return [passed("Bedrock", "direct Bedrock is denied, as designed (models go through LiteLLM)")]
            return [warned("Bedrock", f"direct call failed with {_code(error)} instead of AccessDenied")]
        fix = "tell the instructor: the participant role should not reach Bedrock directly"
        return [warned("Bedrock", "direct Bedrock call was ALLOWED", fix)]


def _ping_model(client: httpx.Client, model: str) -> float:
    """Seconds one tiny chat completion took (a fraction of a cent)."""
    response = client.post("/v1/chat/completions", json=ping_payload(model))
    response.raise_for_status()
    return response.elapsed.total_seconds()


def budget_result(info: dict) -> Result:
    """Your remaining LiteLLM budget; failing when it is used up (HTTP 429 budget_exceeded on every call)."""
    spend, budget = float(info.get("spend") or 0.0), info.get("max_budget")
    if budget is None:
        return passed("LiteLLM budget", f"${spend:.4f} spent, no personal cap")
    left = float(budget) - spend
    detail = f"${left:.4f} left of ${float(budget):g}"
    if left <= 0:
        return failed("LiteLLM budget", detail, "ask the instructor to raise your budget (roster.json, then `keys`)")
    return passed("LiteLLM budget", detail)


def _code(error: ClientError) -> str:
    """The AWS error code of `error`."""
    return error.response.get("Error", {}).get("Code", "")


def _aws_fix(error: Exception) -> str:
    """Fix hint for a failed AWS or gateway step (the explanation already names the cause)."""
    if isinstance(error, httpx.HTTPStatusError):
        return GATEWAY_FIXES.get(error.response.status_code, "retry in a minute; if it persists, tell the instructor")
    if isinstance(error, httpx.HTTPError):
        return "check your connection, VPN or proxy (the gateway is an HTTPS CloudFront host)"
    if isinstance(error, ClientError) and _code(error) in ACCESS_DENIED:
        return "compare PARTICIPANT in .env with the name your instructor gave you; if it matches, tell them"
    return "run `aws configure --profile bootcamp` with your access key and set AWS_PROFILE=bootcamp in .env"


def participant_check(settings: Settings) -> Result:
    """PARTICIPANT is set and well-formed (roster membership is proven by the role and gateway checks)."""
    problem = participant_problem(settings.participant)
    if problem:
        return failed(".env PARTICIPANT", problem, "edit .env (copy it from .env.example first)")
    where = ".env" if (ROOT / ".env").is_file() else "environment, no .env file"
    return passed(".env PARTICIPANT", f"{settings.participant} ({where}), region {settings.region}")


def run() -> int:
    """Run every check, print the report and return the exit code."""
    settings = load_settings(require_participant=False)
    logging.getLogger("botocore.credentials").setLevel(logging.ERROR)
    print("Checking this laptop for the bootcamp (up to ~30 s; nothing is created)...")
    checks = [*local_checks(), AwsChain(settings).run, *network_checks(settings.region)]
    results = report.run_checks(checks)
    print("\n".join(report.render(results)))
    code = report.exit_code(results)
    print(f"\n{report.summary(results)}.", "Fix the failed lines above." if code else "Ready for day 1.")
    return code
