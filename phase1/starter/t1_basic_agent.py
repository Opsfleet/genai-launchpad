"""Task 1 starter: a concierge agent whose only knowledge is its system prompt.

Fill in the TODOs, then run:  uv run bootcamp.py phase1 t1 --starter "What departments do we have?"
Reference solution:            phase1/t1_basic_agent.py  (uv run bootcamp.py phase1 t1)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from strands import Agent  # noqa: E402

from common import make_model, run  # noqa: E402, F401

SYSTEM_PROMPT = ""
"""TODO 1: describe DataStream Corp's departments (Sales, HR, Engineering) and the tone the assistant should use.

Also say it has no company data yet, so it must never invent departments or numbers.
"""


def build_agent() -> Agent:
    """TODO 2: return a Strands Agent named "Concierge" that uses make_model() and SYSTEM_PROMPT."""
    if not SYSTEM_PROMPT.strip():
        raise NotImplementedError("TODO 1: write SYSTEM_PROMPT in phase1/starter/t1_basic_agent.py")
    raise NotImplementedError("TODO 2: create the Agent in build_agent() in phase1/starter/t1_basic_agent.py")


if __name__ == "__main__":
    run(build_agent())
