"""Expected durations and heartbeats, so long silent waits (terraform, DNS, memory) never look like a hang."""

import logging
import threading
from collections.abc import Iterator
from contextlib import contextmanager

log = logging.getLogger(__name__)

EXPECTED_MINUTES: dict[int | str, float] = {
    0: 6.0,
    1: 1.5,
    2: 1.0,
    3: 11.0,
    4: 5.5,
    5: 0.5,
    6: 1.0,
    7: 4.5,
    "deploy": 1.5,
    "down": 10.5,
}
"""Typical wall-clock minutes, measured in dry runs: an int key is the cost of adding that stage with `up`
(stage 0 includes the ~5 min wait for the new Cognito domain's DNS, stage 7 the ~3 min policy engine); string keys
are whole commands (`deploy` is usually 1-1.5 min, but up to ~10 min while the runtime is still updating)."""
HEARTBEAT_SECONDS = 60
_activity: list[str] = []
"""What the current long wait is doing, when more specific than the heartbeat's own label (see `doing`)."""


def up_minutes(current_stage: int, target_stage: int) -> float:
    """Expected minutes for `up target_stage` from `current_stage` (-1 = nothing provisioned yet).

    Args:
        current_stage: stage of the existing stack, or -1 when there is none.
        target_stage: stage passed to `up`.

    Returns:
        The sum of the stages being added; a short re-apply when nothing new is added.
    """
    added = range(current_stage + 1, target_stage + 1)
    return sum(EXPECTED_MINUTES[stage] for stage in added) or 1.0


def announce(what: str, minutes: float) -> None:
    """Tell the user up front how long `what` usually takes."""
    log.info("%s (usually ~%s min)...", what, f"{minutes:g}")


@contextmanager
def heartbeat(what: str, every: float = HEARTBEAT_SECONDS) -> Iterator[None]:
    """Log "still <what> (N min elapsed)" every `every` seconds until the block exits."""
    stop = threading.Event()

    def beat() -> None:
        ticks = 0
        while not stop.wait(every):
            ticks += 1
            log.info("  ... still %s (%s min elapsed)", (_activity or [what])[-1], f"{ticks * every / 60:g}")

    thread = threading.Thread(target=beat, daemon=True)
    thread.start()
    try:
        yield
    finally:
        stop.set()


@contextmanager
def doing(what: str) -> Iterator[None]:
    """Make a running heartbeat report `what` (e.g. "waiting for Cognito DNS") until the block exits."""
    _activity.append(what)
    try:
        yield
    finally:
        _activity.remove(what)
