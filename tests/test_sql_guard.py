"""Read/write classification shared by the approval hook, the agent's read-only guard and the MCP server."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "shared"))
import sql_guard  # noqa: E402

READS = [
    "SELECT * FROM employees",
    "  select count(*) from employees",
    "SELECT updated_at FROM employees LIMIT 1",
    "SELECT * FROM audit_log WHERE action = 'delete'",
    "SELECT replace(first_name, 'a', 'b') FROM employees",
    "-- headcount\nSELECT COUNT(*) FROM employees",
    "/* note */ SELECT 1;",
    "WITH eng AS (SELECT * FROM employees) SELECT COUNT(*) FROM eng",
    "EXPLAIN QUERY PLAN SELECT * FROM employees",
    "PRAGMA table_info(employees)",
    "pragma TABLE_INFO('employees');",
    "PRAGMA main.index_list(employees)",
    "PRAGMA table_list",
    "PRAGMA foreign_key_list(employees)",
    "/* schema */ PRAGMA table_xinfo ( employees )",
]
WRITES = [
    "DELETE FROM employees",
    "/* c */ DELETE FROM employees",
    "-- x\nDELETE FROM employees",
    "WITH old AS (SELECT id FROM employees) DELETE FROM employees WHERE id IN old",
    "WITH x AS (SELECT '--') DELETE FROM employees",
    "UPDATE employees SET salary = 0",
    "insert into departments(name) values ('x')",
    "REPLACE INTO departments(id, name) VALUES (1, 'x')",
    "CREATE TABLE t (id INT)",
    "DROP TABLE employees",
    "ALTER TABLE employees ADD COLUMN x INT",
    "PRAGMA journal_mode=DELETE",
    "PRAGMA journal_mode = WAL",
    "PRAGMA user_version(5)",
    "PRAGMA table_info=1",
    "PRAGMA optimize",
    "PRAGMA wal_checkpoint(TRUNCATE)",
    "PRAGMA table_info(employees); DELETE FROM employees",
    "WITH x AS (SELECT 1) Delete FROM employees",
    "DELETE\tFROM employees",
    "DELETE\nFROM employees",
    "\tdelete\r\nfrom employees",
    "ATTACH DATABASE 'x.db' AS x",
    "VACUUM",
    "SELECT 1; DELETE FROM employees",
    "",
]


@pytest.mark.parametrize("sql", READS)
def test_reads_are_read_only(sql: str) -> None:
    assert sql_guard.is_read_only(sql)
    assert not sql_guard.is_write(sql)


@pytest.mark.parametrize("sql", WRITES)
def test_writes_are_writes(sql: str) -> None:
    assert sql_guard.is_write(sql)


def test_first_keyword_skips_comments() -> None:
    assert sql_guard.first_keyword("/* a */ -- b\n  delete from t") == "DELETE"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
