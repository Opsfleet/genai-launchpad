"""Thin Terraform wrapper shared by the participant and instructor CLIs (one workspace per participant).

apply/destroy print a short summary by default (plan counts, one line per finished resource, a heartbeat each minute
a resource is still in progress, the final "Apply complete!" line) and the full terraform output with --verbose.
"""

import json
import logging
import random
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path

log = logging.getLogger(__name__)

FAILURE_TAIL_LINES = 40
PLAN_LINE = re.compile(r"^Plan: (\d+) to add, (\d+) to change, (\d+) to destroy")
DONE_LINE = re.compile(r"^(\S+): (Creation|Modifications|Destruction) complete after (\S+)")
STILL_LINE = re.compile(r"^(\S+): Still (\w+)\.\.\. \[(?:[^\]]*, )?(\d+m0?0s) elapsed\]")
FINAL_LINE = re.compile(r"^(Apply|Destroy) complete!|^No changes\.")
DONE_SYMBOLS = {"Creation": "+", "Modifications": "~", "Destruction": "-"}


def _require_terraform() -> None:
    if not shutil.which("terraform"):
        raise SystemExit("terraform not found on PATH (install >= 1.9).")


THROTTLE_MARKERS = ("Too Many Requests", "ThrottlingException", "TooManyRequestsException", "Rate exceeded")
"""Error text AWS uses for rate limits; seen when a whole class runs ``up`` at once (CreateGateway 429)."""
THROTTLE_RETRY_SECONDS = 30
"""Base wait before the single retry; jitter spreads a class's retries apart."""


def terraform(directory: Path, args: list[str], env: dict[str, str], capture: bool = False) -> str:
    """Run terraform in `directory`; on failure echo any captured stderr (init errors would vanish) and raise."""
    _require_terraform()
    try:
        result = subprocess.run(
            ["terraform", f"-chdir={directory}", *args], env=env, check=True, text=True, capture_output=capture
        )
    except subprocess.CalledProcessError as error:
        if capture:
            sys.stderr.write(error.stderr or error.stdout or "")
        raise
    return result.stdout if capture else ""


def run_live(directory: Path, args: list[str], env: dict[str, str], verbose: bool = False) -> None:
    """Run a long terraform command (apply/destroy) with summarised or, when `verbose`, full output.

    Interactive runs (no -auto-approve) always show full output so the approval prompt stays visible.

    Raises:
        subprocess.CalledProcessError: terraform failed; its error block was already printed.
    """
    _require_terraform()
    full = verbose or "-auto-approve" not in args
    command = ["terraform", f"-chdir={directory}", args[0], *_color_flags(full), *args[1:]]
    if full:
        subprocess.run(command, env=env, check=True)
        return
    returncode, output = _stream_summary(command, env)
    if returncode and throttled(output):
        wait = THROTTLE_RETRY_SECONDS + random.uniform(0, THROTTLE_RETRY_SECONDS / 2)
        print(f"AWS throttled a create/delete call (class-wide rush); retrying once in {wait:.0f}s...", flush=True)
        time.sleep(wait)
        returncode, output = _stream_summary(command, env)
    if returncode:
        sys.stderr.write("\n".join(failure_excerpt(output)) + "\n")
        raise subprocess.CalledProcessError(returncode, command)


def throttled(output: list[str]) -> bool:
    """True when terraform failed on an AWS rate limit, which a re-run (apply/destroy are idempotent) clears."""
    return any(marker in line for line in output for marker in THROTTLE_MARKERS)


def _color_flags(full: bool) -> list[str]:
    """Colour only when terraform writes straight to a terminal."""
    return [] if full and sys.stdout.isatty() else ["-no-color"]


def _stream_summary(command: list[str], env: dict[str, str]) -> tuple[int, list[str]]:
    """Run `command`, printing only the summary lines; returns its exit code and every output line."""
    output: list[str] = []
    with subprocess.Popen(
        command, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1
    ) as process:
        for raw in process.stdout or []:
            output.append(raw.rstrip("\n"))
            summary = summarize_line(output[-1])
            if summary:
                print(summary, flush=True)
    return process.returncode, output


def summarize_line(line: str) -> str | None:
    """The concise form of one terraform output line, or None to hide it."""
    if match := PLAN_LINE.match(line):
        return f"terraform plan: +{match[1]} ~{match[2]} -{match[3]}"
    if match := DONE_LINE.match(line):
        return f"  {DONE_SYMBOLS[match[2]]} {match[1]} ({match[3]})"
    if match := STILL_LINE.match(line):
        return f"  ... {match[1]} still {match[2]} ({match[3]})"
    return line if FINAL_LINE.match(line) else None


def failure_excerpt(output: list[str]) -> list[str]:
    """terraform's error blocks (from the first "Error:" line), or the last lines when there are none."""
    starts = [index for index, line in enumerate(output) if line.lstrip("│ ").startswith("Error:")]
    return output[starts[0] :] if starts else output[-FAILURE_TAIL_LINES:]


def prepare(directory: Path, env: dict[str, str], workspace: str | None, init_args: Sequence[str] = ()) -> None:
    """Init the module and pin `env` to the participant's workspace.

    Uses TF_WORKSPACE (per process) rather than `workspace select` (written to the shared
    .terraform dir), so several participants can run from one checkout at the same time.

    Args:
        directory: The terraform module.
        env: Environment for terraform; TF_WORKSPACE is set here.
        workspace: Workspace to select (created when missing), or None for the default one.
        init_args: Extra `terraform init` flags, e.g. `-backend-config=...` for a partial remote backend.
    """
    env.pop("TF_WORKSPACE", None)
    terraform(directory, ["init", "-input=false", "-upgrade=false", *init_args], env, capture=True)
    if not workspace:
        return
    if workspace not in workspaces(directory, env):
        terraform(directory, ["workspace", "new", workspace], env, capture=True)
    env["TF_WORKSPACE"] = workspace


def workspaces(directory: Path, env: dict[str, str]) -> list[str]:
    """Names of the module's terraform workspaces (the module must be initialised)."""
    return terraform(directory, ["workspace", "list"], env, capture=True).replace("*", " ").split()


def state_addresses(directory: Path, env: dict[str, str]) -> list[str]:
    """Managed resource addresses in the current workspace's state ([] when it has no state yet)."""
    state = json.loads(terraform(directory, ["show", "-json"], env, capture=True) or "{}")
    return managed_addresses(state.get("values", {}).get("root_module", {}))


def managed_addresses(module: dict) -> list[str]:
    """Managed (non-data) resource addresses of a `terraform show -json` module, including child modules."""
    own = [resource["address"] for resource in module.get("resources", []) if resource.get("mode") == "managed"]
    return own + [address for child in module.get("child_modules", []) for address in managed_addresses(child)]


def outputs(directory: Path, env: dict[str, str]) -> dict[str, str]:
    """Return terraform outputs as a flat dict (sensitive values included)."""
    raw = json.loads(terraform(directory, ["output", "-json"], env, capture=True) or "{}")
    return {key: item["value"] for key, item in raw.items()}
