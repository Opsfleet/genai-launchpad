"""The golden dataset file behind `bootcamp.py eval`: questions with ground truth, read from YAML or CSV.

Each item has an `id`, a `question`, the `expected` reference answer and optional `assertions` (natural-language
statements the session must satisfy) and `tools` (tool names the agent is expected to call). Items convert to and
from AgentCore dataset examples of schema `AGENTCORE_EVALUATION_PREDEFINED_V1` (one single-turn scenario each), so
the managed dataset in your account holds exactly what the file says.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from bootcamp_cli.config import ROOT

DEFAULT_PATH = ROOT / "phase2" / "evals" / "golden.yaml"
ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
LIST_SEPARATOR = "|"
"""Separates several assertions or tools inside one CSV cell."""
DEFAULT_ASSERTION = "The final answer agrees with this reference answer: {expected}"


@dataclass(frozen=True)
class GoldenItem:
    """One golden question with its ground truth."""

    id: str
    question: str
    expected: str
    assertions: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()

    def checks(self) -> tuple[str, ...]:
        """The assertions GoalSuccessRate judges: the file's, or one derived from the expected answer."""
        return self.assertions or (DEFAULT_ASSERTION.format(expected=self.expected),)


def load_items(path: Path = DEFAULT_PATH) -> list[GoldenItem]:
    """Read and validate a golden dataset file (.yaml/.yml or .csv).

    Raises:
        RuntimeError: The file is missing, has an unknown extension or an invalid item.
    """
    if not path.is_file():
        raise RuntimeError(f"Golden dataset not found: {path}")
    if path.suffix.lower() == ".csv":
        rows = _csv_rows(path)
    elif path.suffix.lower() in {".yaml", ".yml"}:
        rows = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    else:
        raise RuntimeError(f"{path.name}: use a .yaml, .yml or .csv file")
    return _validated([_item(row, path.name) for row in _as_list(rows, path.name)], path.name)


def _csv_rows(path: Path) -> list[dict]:
    """CSV rows as dicts, with `assertions` / `tools` split on LIST_SEPARATOR."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        for key in ("assertions", "tools"):
            row[key] = [part.strip() for part in (row.get(key) or "").split(LIST_SEPARATOR) if part.strip()]
    return rows


def _as_list(rows: object, source: str) -> list[dict]:
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise RuntimeError(f"{source}: expected a list of items with id, question and expected")
    return rows


def _item(row: dict, source: str) -> GoldenItem:
    """One validated item from a parsed row."""
    values = {key: str(row.get(key) or "").strip() for key in ("id", "question", "expected")}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"{source}: item {row.get('id', '?')!r} has no {', '.join(missing)}")
    if not ID_PATTERN.match(values["id"]):
        raise RuntimeError(f"{source}: id {values['id']!r} must be 1-64 letters, digits, - or _")
    return GoldenItem(**values, assertions=_strings(row.get("assertions")), tools=_strings(row.get("tools")))


def _strings(value: object) -> tuple[str, ...]:
    """A list (or single string) of non-empty strings as a tuple."""
    items = value if isinstance(value, list) else [value] if value else []
    return tuple(str(item).strip() for item in items if str(item).strip())


def _validated(items: list[GoldenItem], source: str) -> list[GoldenItem]:
    ids = [item.id for item in items]
    duplicates = sorted({item for item in ids if ids.count(item) > 1})
    if duplicates:
        raise RuntimeError(f"{source}: duplicate ids {', '.join(duplicates)}")
    if not items:
        raise RuntimeError(f"{source}: no items")
    return items


def to_example(item: GoldenItem) -> dict:
    """The item as a predefined-scenario dataset example."""
    example = {
        "scenario_id": item.id,
        "turns": [{"input": item.question, "expected_response": item.expected}],
        "assertions": list(item.checks()),
    }
    return example | ({"expected_trajectory": list(item.tools)} if item.tools else {})


def from_example(example: dict) -> GoldenItem:
    """A dataset example (as `ListDatasetExamples` returns it) back as an item."""
    turn = example["turns"][0]
    return GoldenItem(
        id=example["scenario_id"],
        question=str(turn["input"]),
        expected=str(turn.get("expected_response", "")),
        assertions=tuple(example.get("assertions") or ()),
        tools=tuple(example.get("expected_trajectory") or ()),
    )
