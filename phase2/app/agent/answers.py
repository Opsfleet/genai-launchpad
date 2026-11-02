"""The agent's final reply: never empty, never just a title.

Kept free of AgentCore imports so it is unit-testable without the runtime SDK.
"""

EMPTY_ANSWER = "Sorry, the model returned an empty answer (possibly an upstream timeout). Please ask again."


def is_heading(line: str) -> bool:
    """A markdown heading or a line that is bold from end to end, e.g. `**Seattle Weather**`."""
    return line.startswith("#") or (len(line) > 4 and line.startswith("**") and line.endswith("**"))


def has_body(text: str) -> bool:
    """Whether an answer says something beyond headings (a reasoning model sometimes stops after the title)."""
    return any(line.strip() and not is_heading(line.strip()) for line in text.splitlines())


def final_answer(text: str, specialist_results: list[str]) -> str:
    """The orchestrator's answer; if it has no body (empty, or only a heading), the last specialist answer."""
    if has_body(text):
        return text
    return next((answer for answer in reversed(specialist_results) if answer.strip()), EMPTY_ANSWER)
