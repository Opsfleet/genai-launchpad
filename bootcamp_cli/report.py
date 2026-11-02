"""Pass/warn/fail check reports shared by `bootcamp.py doctor` and `instructor.py preflight`.

Each check is a zero-argument callable returning one or more `Result`s. `run_checks` runs them concurrently (they are
mostly network round trips, so the whole report takes as long as the slowest check), turns an unexpected exception
into a failed result instead of a traceback, and keeps the declared order for printing.
"""

import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from enum import Enum

WORKERS = 12


class Status(Enum):
    """Outcome of one check; only FAIL makes the command exit non-zero."""

    PASS = ("✔", "OK  ")
    WARN = ("!", "WARN")
    FAIL = ("✘", "FAIL")
    SKIP = ("-", "SKIP")


@dataclass(frozen=True)
class Result:
    """One line of a report: what was checked, what was found and, when not passing, how to fix it."""

    name: str
    status: Status
    detail: str
    fix: str = ""


Check = Callable[[], Result | list[Result]]


def passed(name: str, detail: str) -> Result:
    """A passing result."""
    return Result(name, Status.PASS, detail)


def failed(name: str, detail: str, fix: str) -> Result:
    """A failing result with its fix hint."""
    return Result(name, Status.FAIL, detail, fix)


def warned(name: str, detail: str, fix: str = "") -> Result:
    """A warning: worth fixing, but not a blocker."""
    return Result(name, Status.WARN, detail, fix)


def skipped(name: str, reason: str) -> Result:
    """A check that could not run because an earlier one failed."""
    return Result(name, Status.SKIP, reason)


def _guarded(check: Check) -> list[Result]:
    """Run one check; an unexpected exception becomes a failed result named after the check."""
    try:
        outcome = check()
    except Exception as error:  # noqa: BLE001 - a report must list every problem, not stop at the first
        name = getattr(check, "__name__", "check").removeprefix("check_").replace("_", " ")
        return [failed(name, f"{type(error).__name__}: {error}", "rerun with --verbose and ask the instructor")]
    return outcome if isinstance(outcome, list) else [outcome]


def run_checks(checks: Sequence[Check]) -> list[Result]:
    """Run `checks` concurrently and return their results in declaration order."""
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        outcomes = list(pool.map(_guarded, checks))
    return [result for outcome in outcomes for result in outcome]


def _symbols_supported() -> bool:
    """Whether stdout can print ✔/✘ (a redirected Windows console may use a legacy code page)."""
    try:
        "✔✘".encode(sys.stdout.encoding or "ascii")
    except (UnicodeEncodeError, LookupError):
        return False
    return True


def render(results: Sequence[Result], fancy: bool | None = None) -> list[str]:
    """One line per result plus an indented fix hint under each warning or failure."""
    fancy = _symbols_supported() if fancy is None else fancy
    lines = []
    for result in results:
        symbol, word = result.status.value
        lines.append(f"{symbol if fancy else word} {result.name}: {result.detail}")
        if result.fix and result.status in {Status.FAIL, Status.WARN}:
            lines.append(f"    fix: {result.fix}")
    return lines


def summary(results: Sequence[Result]) -> str:
    """Closing line: counts per status."""
    counts = {status: sum(r.status is status for r in results) for status in Status}
    shown = [f"{counts[s]} {s.name.lower()}" for s in Status if counts[s]]
    return ", ".join(shown)


def exit_code(results: Sequence[Result]) -> int:
    """1 when any check failed, else 0 (warnings and skips do not fail the run)."""
    return int(any(result.status is Status.FAIL for result in results))
