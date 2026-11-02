"""Task 7: the Gateway's `safe_query_policy.cedar`, evaluated offline on the exact SQL strings that matter.

No Cedar engine needed: the policy's `when` clause only combines `context.input.query like "..."` tests with
`&&`, `||` and `!`, so this test translates it to a Python expression and implements Cedar's `like` (`*` matches
any characters, `\\*` a literal star; case-sensitive). Run alone: uv run pytest tests/test_cedar_policy.py
"""

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from bootcamp_cli import checks  # noqa: E402

POLICY = ROOT / "terraform" / "participant" / "safe_query_policy.cedar"
LIKE = re.compile(r'context\.input\.query like "((?:[^"\\]|\\.)*)"')
ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "*": "*", "\\": "\\", '"': '"'}


def like_regex(pattern: str) -> str:
    """A Cedar `like` pattern (as written in the policy source) as an anchored Python regex."""
    parts, chars = [], iter(pattern)
    for char in chars:
        if char == "\\":
            parts.append(re.escape(ESCAPES[next(chars)]))
        else:
            parts.append(".*" if char == "*" else re.escape(char))
    return "".join(parts)


def when_clause() -> str:
    """The policy's `when { ... }` condition as a Python expression over `query`."""
    text = POLICY.read_text().split("when {", 1)[1].rsplit("};", 1)[0]
    text = LIKE.sub(lambda match: f"matches(query, {like_regex(match.group(1))!r})", text)
    return "(" + text.replace("&&", " and ").replace("||", " or ").replace("!(", " not (") + ")"


def permitted(query: str) -> bool:
    """Whether the policy permits a `query_db` call with this exact query text."""

    def matches(value: str, regex: str) -> bool:
        return re.fullmatch(regex, value, re.DOTALL) is not None

    return bool(eval(when_clause(), {"matches": matches, "query": query}))  # noqa: S307 - our own policy file


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT 1",
        "select * from employees",
        "SELECT\tname FROM departments",
        "SELECT\r\nname FROM departments",
        "WITH t AS (SELECT 1) SELECT * FROM t",
        "WITH\r\nt AS (SELECT 1) SELECT * FROM t",
        "EXPLAIN QUERY PLAN SELECT * FROM employees",
        "explain SELECT 1",
        "PRAGMA table_info(employees)",
        "pragma table_info('projects')",
        "SELECT name FROM pragma_table_info('employees')",
        checks.UPDATED_AT_SQL,
        checks.ENGINEERING_COUNT_SQL,
        checks.SELECT_SQL,
    ],
)
def test_harmless_reads_are_permitted(sql: str) -> None:
    assert permitted(sql)


@pytest.mark.parametrize(
    "sql",
    [
        checks.HARMLESS_DELETE_SQL,
        "DROP TABLE employees",
        "UPDATE employees SET salary = 0",
        "PRAGMA writable_schema=ON",
        "PRAGMA writable_schema = 1",
        "PRAGMA table_info(employees); PRAGMA writable_schema=1",
        "PRAGMA journal_mode",
        "EXPLAIN DELETE FROM employees",
        "SELECT 1 -- comment",
        "SELECT 1 /* comment */",
        "WITH x AS (SELECT 1) Delete FROM employees WHERE 1 = 0",
        "WITH x AS (SELECT 1) DELETE\tFROM employees WHERE 1 = 0",
        " SELECT 1",
    ],
)
def test_writes_and_unsafe_statements_are_denied(sql: str) -> None:
    assert not permitted(sql)


@pytest.mark.parametrize(
    "sql",
    [
        "sElEcT 1",
        "SELECT last_update FROM t",
        "SELECT * FROM audit_log WHERE action LIKE '%delete %'",
    ],
)
def test_known_string_matching_false_denials(sql: str) -> None:
    """`like` can neither lower-case nor parse SQL: these harmless reads stay denied (documented on the Task 7 page)."""
    assert not permitted(sql)


def test_mixed_case_write_slips_through_to_the_read_only_database() -> None:
    """The Task 7 challenge: a casing the policy does not list is permitted; the read-only database refuses it."""
    assert permitted("WITH x AS (SELECT 1) dElEtE FROM employees WHERE 1 = 0")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
