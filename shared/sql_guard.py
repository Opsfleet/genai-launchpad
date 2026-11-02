"""Classify a SQL statement as read-only or as a write, for guards in front of the `query_db` tool.

Used by the Phase 1 approval hook, the Phase 2 agent's read-only guard and the Phase 2 MCP server (copied into
every app zip by bootcamp_cli.build). The rule is an allowlist: after removing comments and string literals, a
statement is read-only only when its first keyword is SELECT or EXPLAIN, it is a WITH (CTE) query that contains
no data-modifying statement, or it is a schema-introspection PRAGMA such as `PRAGMA table_info(employees)` (no `=`
assignment, no other pragma). Anything else (INSERT, UPDATE, DELETE, REPLACE, CREATE, DROP, ALTER, other PRAGMAs,
ATTACH, VACUUM, ..., an empty statement or several statements) counts as a write. Matching is on whole words, so a
column such as `updated_at` or a literal such as 'please delete' never trips it.
"""

import re

READ_ONLY_KEYWORDS = frozenset({"SELECT", "EXPLAIN"})
CTE_KEYWORD = "WITH"
NOISE = re.compile(r"'(?:[^']|'')*'|\"(?:[^\"]|\"\")*\"|--[^\n]*|/\*.*?(?:\*/|$)", re.DOTALL)
FIRST_WORD = re.compile(r"[A-Za-z_]+")
DATA_MODIFYING = re.compile(r"\b(?:INSERT|UPDATE|DELETE)\b|\bREPLACE\b(?!\s*\()", re.IGNORECASE)
"""REPLACE followed by `(` is the string function, not the REPLACE statement."""
READ_ONLY_PRAGMAS = frozenset(
    {
        "TABLE_INFO",
        "TABLE_XINFO",
        "TABLE_LIST",
        "INDEX_LIST",
        "INDEX_INFO",
        "INDEX_XINFO",
        "FOREIGN_KEY_LIST",
        "DATABASE_LIST",
        "COLLATION_LIST",
        "FUNCTION_LIST",
        "MODULE_LIST",
        "PRAGMA_LIST",
        "COMPILE_OPTIONS",
    }
)
"""Introspection pragmas that only read the schema. Others (journal_mode, optimize, wal_checkpoint, ...) may write."""
PRAGMA_QUERY = re.compile(r"\s*PRAGMA\s+(?:\w+\s*\.\s*)?(\w+)\s*(?:\(\s*(?:\w+|'')\s*\))?\s*;?\s*", re.IGNORECASE)
"""`PRAGMA [schema.]name[(argument)]` with nothing else, so an `=` assignment never matches."""


def strip_noise(sql: str) -> str:
    """Replace comments with a space and string/identifier literals with an empty pair of quotes.

    Args:
        sql: The raw SQL text.

    Returns:
        SQL with no comments and no literal contents left to match keywords against.
    """
    return NOISE.sub(lambda match: " " if match.group().startswith(("--", "/*")) else "''", sql)


def first_keyword(sql: str) -> str:
    """The first word of a SQL statement in upper case, ignoring comments.

    Args:
        sql: The raw SQL text.

    Returns:
        The first keyword, or "" for an empty statement.
    """
    match = FIRST_WORD.search(strip_noise(sql))
    return match.group().upper() if match else ""


def is_single_statement(cleaned: str) -> bool:
    """True unless something other than whitespace follows a `;`.

    Args:
        cleaned: SQL already passed through `strip_noise`.

    Returns:
        Whether the text holds at most one statement.
    """
    return not cleaned.rstrip().rstrip(";").count(";")


def is_read_only_pragma(cleaned: str) -> bool:
    """Whether a statement is a schema-introspection PRAGMA such as `PRAGMA table_info(employees)`.

    Args:
        cleaned: SQL already passed through `strip_noise`.

    Returns:
        True only for an allowlisted pragma without assignment.
    """
    match = PRAGMA_QUERY.fullmatch(cleaned)
    return bool(match) and match.group(1).upper() in READ_ONLY_PRAGMAS


def is_read_only(sql: str) -> bool:
    """Whether `sql` is a single read-only statement (SELECT, EXPLAIN, a CTE without data modification or an
    introspection PRAGMA).

    Args:
        sql: The raw SQL text.

    Returns:
        True for read-only queries, False for anything that may write.
    """
    cleaned = strip_noise(sql)
    keyword = first_keyword(cleaned)
    if not is_single_statement(cleaned):
        return False
    if keyword == CTE_KEYWORD:
        return not DATA_MODIFYING.search(cleaned)
    if keyword == "PRAGMA":
        return is_read_only_pragma(cleaned)
    return keyword in READ_ONLY_KEYWORDS


def is_write(sql: str) -> bool:
    """Whether `sql` must be treated as a write (the complement of `is_read_only`).

    Args:
        sql: The raw SQL text.

    Returns:
        True when the statement may modify the database.
    """
    return not is_read_only(sql)
