"""Which evaluators `bootcamp.py eval --evaluators` runs, and their short display names.

A spec is a comma-separated list of:
- `builtin`: Builtin.Correctness and Builtin.GoalSuccessRate (+ Builtin.TrajectoryAnyOrderMatch when an item names
  expected tools), the default;
- `custom`: every custom evaluator your stack created at stage 6 (the code-based Lambdas `exact_numbers` and
  `rubric_judge`, which grades a phase2/evals/evaluators.yaml rubric through LiteLLM), from the terraform output
  `custom_evaluators`;
- `all`: both;
- one custom evaluator by name (`rubric_judge`), or any evaluator id (`Builtin.Helpfulness`).
"""

import re

from bootcamp_cli.golden import GoldenItem

BUILTIN = ("Builtin.Correctness", "Builtin.GoalSuccessRate")
TRAJECTORY = "Builtin.TrajectoryAnyOrderMatch"
DEFAULT_SPEC = "builtin"
CUSTOM_ID = re.compile(r"^awsworkshop_[a-z][a-z0-9]{0,15}_(?P<name>[A-Za-z0-9_]+?)(?P<suffix>-[A-Za-z0-9]{10})?$")
"""Custom evaluator ids are `<evaluator name>-<10 characters>`; the name is awsworkshop_<you>_<yaml name>."""
NO_CUSTOM = "No custom evaluators yet: your stack creates them at stage 6 (`uv run bootcamp.py up 6`)."


def builtin_for(items: list[GoldenItem]) -> list[str]:
    """The built-in evaluators: trajectory matching only when some item names expected tools."""
    return [*BUILTIN, *([TRAJECTORY] if any(item.tools for item in items) else [])]


def resolve(spec: str, items: list[GoldenItem], custom: dict[str, str]) -> list[str]:
    """Evaluator ids for a `--evaluators` spec, in order and without duplicates.

    Args:
        spec: Comma-separated builtin / custom / all / custom names / evaluator ids.
        items: The golden items being asked (decides whether trajectory matching applies).
        custom: Your custom evaluators, name -> id (terraform output `custom_evaluators`).

    Raises:
        RuntimeError: The spec names an unknown evaluator, or custom ones before stage 6.
    """
    chosen = [
        evaluator for part in spec.split(",") if part.strip() for evaluator in _expand(part.strip(), items, custom)
    ]
    if not chosen:
        raise RuntimeError("--evaluators is empty: use builtin, custom, all or evaluator names.")
    return list(dict.fromkeys(chosen))


def _expand(part: str, items: list[GoldenItem], custom: dict[str, str]) -> list[str]:
    """The evaluator ids one spec entry stands for."""
    if part == "builtin":
        return builtin_for(items)
    if part in {"custom", "all"}:
        if not custom:
            raise RuntimeError(NO_CUSTOM)
        return [*(builtin_for(items) if part == "all" else []), *custom.values()]
    if part in custom:
        return [custom[part]]
    if part.startswith("Builtin.") or ((match := CUSTOM_ID.match(part)) and match.group("suffix")):
        return [part]
    known = ", ".join(custom) or "none yet"
    raise RuntimeError(
        f"Unknown evaluator {part!r}: use builtin, custom, all, Builtin.<Name> or a custom name ({known})."
    )


def short_name(evaluator: str) -> str:
    """Display name: Builtin.GoalSuccessRate -> GoalSuccessRate; a custom id -> its name (rubric_judge)."""
    match = CUSTOM_ID.match(evaluator)
    return match.group("name") if match else evaluator.removeprefix("Builtin.")


def canonical(evaluator: str, requested: list[str]) -> str:
    """The requested id a result event's evaluator name refers to (events may carry a name or an id)."""
    return next((item for item in requested if short_name(item) == short_name(evaluator)), evaluator)
