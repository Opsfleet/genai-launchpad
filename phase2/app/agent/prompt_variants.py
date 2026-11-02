"""Prompt variants for A/B comparison (Phase 2, Task 6 Part C).

One deployed agent serves every variant: the caller names one in the payload (`{"prompt": ..., "variant": "B"}`) and
the orchestrator's system prompt gets that variant's extra instructions. `bootcamp.py eval --variants A,B` asks the
golden questions once per variant and compares the scores side by side. This mirrors AgentCore's managed A/B tests
with configuration bundles, where the Gateway tells one runtime which configuration version to apply per session.

A is the control (the shipped prompt, unchanged). Edit B, or add C, then `deploy` and compare.
"""

CONTROL = "A"
VARIANTS = {
    CONTROL: "",
    "B": (
        "Answer in one or two sentences. State the exact number from the data, unrounded, and name the department, "
        "project or place it is about. No estimates, caveats or extra commentary."
    ),
}


def variant_name(requested: object) -> str:
    """The variant to apply: the requested one if it exists, else the control."""
    name = str(requested or CONTROL).strip().upper()
    return name if name in VARIANTS else CONTROL


def variant_instructions(name: str) -> str:
    """The extra system-prompt lines of variant `name` ("" for the control)."""
    return VARIANTS.get(name, "")


def apply_variant(agent: object, requested: object) -> str:
    """Append the requested variant's instructions to a Strands agent's system prompt; returns the variant applied."""
    name = variant_name(requested)
    extra = variant_instructions(name)
    if extra:
        agent.system_prompt = f"{agent.system_prompt or ''}\n{extra}".strip()
    return name
