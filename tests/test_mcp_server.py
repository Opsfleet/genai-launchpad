"""Phase 2 MCP server: reads work on a WAL seed, and no statement can change the data, however it is written."""

import importlib
import io
import json
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import boto3
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "phase2" / "app" / "mcp_server"))


class FakeS3:
    """In-memory S3 holding one database object; counts downloads."""

    def __init__(self, body: bytes) -> None:
        self.body = body
        self.gets = 0

    def get_object(self, **_: str) -> dict:
        self.gets += 1
        return {"ETag": '"etag"', "Body": io.BytesIO(self.body)}


def wal_database(path: Path) -> bytes:
    """A small WAL-mode database like the workshop seed, returned as file bytes."""
    with closing(sqlite3.connect(path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, updated_at TEXT)")
        conn.executemany("INSERT INTO employees (name) VALUES (?)", [("ann",), ("ben",)])
        conn.commit()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return path.read_bytes()


@pytest.fixture
def server(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The MCP server module wired to a FakeS3 seeded with a WAL database and a private /tmp copy."""
    fake = FakeS3(wal_database(tmp_path / "seed.db"))
    monkeypatch.setenv("DB_BUCKET", "bucket")
    monkeypatch.setattr(boto3, "client", lambda *args, **kwargs: fake)
    module = importlib.reload(importlib.import_module("mcp_server"))
    monkeypatch.setattr(module, "LOCAL_DB", tmp_path / "local.db")
    return module, fake


def names(module) -> list[str]:
    """Employee names currently in the server's local copy."""
    return [row["name"] for row in json.loads(module.execute("SELECT name FROM employees ORDER BY id"))["data"]]


def test_reads_return_rows(server) -> None:
    module, _ = server
    assert json.loads(module.execute("SELECT updated_at FROM employees"))["data"] == [{"updated_at": None}] * 2


def test_parameters_are_bound(server) -> None:
    module, _ = server
    result = json.loads(module.execute("SELECT name FROM pragma_table_info(?) ORDER BY cid", ("employees",)))
    assert [row["name"] for row in result["data"]] == ["id", "name", "updated_at"]


def test_downloads_once_per_microvm(server) -> None:
    module, fake = server
    module.execute("SELECT 1")
    module.execute("SELECT 2")
    assert fake.gets == 1


@pytest.mark.parametrize(
    "query",
    [
        "DELETE FROM employees WHERE id = 1",
        "WITH x AS (SELECT 1) Delete FROM employees WHERE id = 1",
        "DELETE\tFROM employees WHERE id = 1",
        "dElEtE/**/FROM employees WHERE id = 1",
        "UPDATE employees SET name = 'zoe'",
        "DROP TABLE employees",
        "CREATE TABLE t (x)",
        "PRAGMA journal_mode=WAL",
    ],
)
def test_writes_are_refused(server, query: str) -> None:
    module, _ = server
    assert module.execute(query) == module.READ_ONLY_MESSAGE
    assert names(module) == ["ann", "ben"]


def test_attached_databases_are_read_only_too(server, tmp_path: Path) -> None:
    module, _ = server
    with closing(module.connect_read_only(module.ensure_local_db())) as conn:
        conn.execute(f"ATTACH DATABASE '{tmp_path / 'new.db'}' AS other")
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            conn.execute("CREATE TABLE other.t (x)")


def test_sql_error_is_plain_text(server) -> None:
    module, _ = server
    assert module.execute("SELECT * FROM nope").startswith("Error executing query")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
