"""Task 2 starter MCP server: expose the DataStream SQLite database as a `query_db` tool.

Launched over stdio by phase1/starter/t2_mcp_tools.py. Reference: phase1/mcp_server.py
"""

import sqlite3  # noqa: F401  (you will need it for the TODO)
from pathlib import Path

from fastmcp import FastMCP

DB_PATH = Path(__file__).resolve().parents[1] / "datastream_corp.db"

mcp = FastMCP("DataStream DB")


@mcp.tool()
def query_db(query: str) -> str:
    """TODO 1: describe this tool for the model: what it runs, on which database, what it returns, and the schema.

    The model only sees this text, so list the tables with their key columns and the status values ('active', ...);
    otherwise it has to guess column names. Once TODO 2 works, ask the agent to describe every table and put what
    you learn here.
    """
    return "query_db is not implemented yet: finish TODO 2 in phase1/starter/mcp_server.py."
    # TODO 2: open DB_PATH with sqlite3, run `query`, return str(rows); return errors as text instead of raising.


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
