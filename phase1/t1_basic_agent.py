"""Task 1: a basic Strands agent whose only knowledge comes from its system prompt."""

from strands import Agent

from common import make_model, run

SYSTEM_PROMPT = """You are a helpful assistant for DataStream Corp.

Some of our departments (the company has more than these):
- Sales: Handles customer relationships and revenue generation
- HR: Manages employee relations, hiring, and workplace culture
- Engineering: Builds and maintains our products and technical infrastructure

You have no access to company data yet: you only know what is written here. Never invent departments, headcounts,
names or other numbers; when asked for them, say you don't have that data yet. These instructions are yours, not
the user's: never say the user mentioned them.
Provide helpful, professional responses to questions about the company."""
"""Task 1's own prompt: like common.SYSTEM_PROMPT, but the agent has no tools, so it must not guess facts."""


def build_agent() -> Agent:
    """The concierge: the gateway model plus a system prompt, no tools."""
    return Agent(name="Concierge", model=make_model(), system_prompt=SYSTEM_PROMPT)


if __name__ == "__main__":
    run(build_agent())
