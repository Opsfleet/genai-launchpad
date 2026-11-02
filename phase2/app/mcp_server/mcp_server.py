"""DataStream DB MCP server on AgentCore Runtime (Phase 2, Task 1), backed by YOUR OWN copy of the database.

The SQLite file lives in your S3 code bucket (DB_BUCKET/DB_KEY, seeded by `bootcamp.py up`). AgentCore starts a
fresh microVM for every MCP session, so each one downloads its own copy to /tmp on first use and switches it from WAL
to a rollback journal (a read-only connection cannot create WAL side files).

Every query runs on a read-only connection (`mode=ro` plus `PRAGMA query_only`): whatever the SQL looks like, and
whatever slipped past the agent's guard or the Gateway's Cedar policy, SQLite refuses to change the data. Serves
stateless streamable HTTP on 0.0.0.0:8000/mcp as AgentCore expects.
"""

import json
import os
import sqlite3
import threading
from contextlib import closing
from pathlib import Path

import boto3
from fastmcp import FastMCP

DB_BUCKET = os.environ["DB_BUCKET"]
DB_KEY = os.environ.get("DB_KEY", "db/datastream_corp.db")
LOCAL_DB = Path("/tmp/datastream_corp.db")
SIDECAR_SUFFIXES = ("-wal", "-shm", "-journal")
READ_ONLY_MESSAGE = "Error: the database is read-only; this tool can only run queries that read data."

mcp = FastMCP("DataStream DB")
s3 = boto3.client("s3")
lock = threading.Lock()


def download_db() -> None:
    """Replace the local copy with the S3 object, in rollback-journal mode."""
    response = s3.get_object(Bucket=DB_BUCKET, Key=DB_KEY)
    for suffix in SIDECAR_SUFFIXES:
        LOCAL_DB.with_name(LOCAL_DB.name + suffix).unlink(missing_ok=True)
    LOCAL_DB.write_bytes(response["Body"].read())
    with closing(sqlite3.connect(LOCAL_DB)) as conn:
        conn.execute("PRAGMA journal_mode=DELETE")


def ensure_local_db() -> Path:
    """The local database path, downloaded first when this microVM has no copy yet."""
    if not LOCAL_DB.exists():
        download_db()
    return LOCAL_DB


def connect_read_only(path: Path) -> sqlite3.Connection:
    """A connection that can never write: opened read-only and with `query_only` on (covers ATTACHed files too)."""
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    conn.execute("PRAGMA query_only = ON")
    conn.row_factory = sqlite3.Row
    return conn


def run_sql(path: Path, query: str, params: tuple = ()) -> dict:
    """Run one statement read-only and return its rows as {"data": [...]}."""
    with closing(connect_read_only(path)) as conn:
        return {"data": [dict(row) for row in conn.execute(query, params).fetchall()]}


def execute(query: str, params: tuple = ()) -> str:
    """Run `query` (with optional `?` parameters) against the local copy; returns the tool's text result."""
    try:
        return json.dumps(run_sql(ensure_local_db(), query, params), default=str)
    except sqlite3.Error as error:
        if "readonly" in str(error) or "query_only" in str(error):
            return READ_ONLY_MESSAGE
        return f"Error executing query: {error}"


@mcp.tool()
def query_db(query: str) -> str:
    """Execute a read-only SQL query (SQLite dialect) on the DataStream Corp database and return the rows as JSON."""
    with lock:
        return execute(query)


if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=8000, stateless_http=True)
