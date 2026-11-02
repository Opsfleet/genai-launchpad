"""Plumbing shared by both entry points (`bootcamp.py` for participants, `instructor.py` for the platform owner):
global flags, concise logging, the per-invocation context and one-line error reporting."""

import argparse
import logging
import os
import subprocess
import sys
from collections.abc import Callable

from dotenv import load_dotenv

from bootcamp_cli.aws import make_access
from bootcamp_cli.config import ROOT, env_flag, load_settings
from bootcamp_cli.errors import HANDLED, explain

log = logging.getLogger("bootcamp")
LOGGERS = ("bootcamp", "instructor", "bootcamp_cli")


class Context:
    """Settings, AWS session and terraform env for one CLI invocation."""

    def __init__(self, as_participant: bool) -> None:
        self.settings = load_settings(require_participant=as_participant)
        access = make_access(self.settings, as_participant=as_participant)
        self.session = access.session
        self.env = access.child_env()
        self.verbose = self.settings.verbose


def global_options(suppress_defaults: bool) -> argparse.ArgumentParser:
    """--confirm/--verbose, accepted before or after the subcommand.

    Args:
        suppress_defaults: True for the copy every subcommand inherits, so its unset flags never overwrite a flag
            given before the subcommand.

    Returns:
        A parent parser holding just these two options.
    """
    parent = argparse.ArgumentParser(add_help=False)
    default = argparse.SUPPRESS if suppress_defaults else False
    parent.add_argument("--confirm", action="store_true", default=default, help="ask before terraform apply/destroy")
    parent.add_argument("--verbose", action="store_true", default=default, help="full terraform output, debug logs")
    return parent


def approve_flags(args: argparse.Namespace) -> list[str]:
    """`-auto-approve` unless the user asked to confirm terraform's plan."""
    return [] if args.confirm else ["-auto-approve"]


class ConciseFormatter(logging.Formatter):
    """Plain message for our progress lines; a level prefix only for warnings and errors."""

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        return f"{record.levelname}: {message}" if record.levelno >= logging.WARNING else message


def utf8_output() -> None:
    """Print UTF-8 whatever the console's code page (e.g. cp1255 on Hebrew Windows): replies hold any character."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def configure_logging(verbose: bool) -> None:
    """Libraries (botocore, httpx, mcp) log warnings only; our own loggers log progress (debug with --verbose)."""
    handler = logging.StreamHandler()
    handler.setFormatter(ConciseFormatter("%(message)s"))
    logging.basicConfig(level=logging.WARNING, handlers=[handler], force=True)
    for name in LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.INFO)


def run(args: argparse.Namespace, command: Callable[[], int]) -> int:
    """Load .env, set up logging and run `command`, turning expected failures into one actionable line.

    Args:
        args: Parsed arguments (only `verbose` is read here).
        command: The selected subcommand, bound to its arguments.

    Returns:
        The process exit code.
    """
    utf8_output()
    load_dotenv(ROOT / ".env")
    if args.verbose:
        os.environ["BOOTCAMP_VERBOSE"] = "1"
    configure_logging(env_flag("BOOTCAMP_VERBOSE"))
    try:
        return command()
    except subprocess.CalledProcessError as error:
        log.error("%s failed (exit %s); see its output above.", error.cmd[0], error.returncode)
        return error.returncode
    except RuntimeError as error:
        log.error("%s", error)
        return 1
    except HANDLED as error:
        log.error("%s", explain(error))
        return 1
