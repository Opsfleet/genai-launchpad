"""Task 2: an MCP server exposing the DataStream Corp SQLite database as a `query_db` tool."""

import sqlite3
from pathlib import Path

from fastmcp import FastMCP

DB_PATH = Path(__file__).resolve().parent / "datastream_corp.db"

mcp = FastMCP("DataStream DB")


@mcp.tool()
def query_db(query: str) -> str:
    """Run one SQL statement on the DataStream Corp SQLite database; returns the rows, or the error, as text.

    Tables (key columns):
    - departments (id, name, description, manager_id, budget)
    - employees (id, employee_id, first_name, last_name, email, job_title, department_id -> departments.id,
      manager_id -> employees.id, salary, hire_date, status)
    - projects (id, name, description, status, start_date, end_date, budget, department_id, project_manager_id)
    - project_assignments (employee_id -> employees.id, project_id -> projects.id, role, allocation_percentage)
    - user_preferences (user_id, preference_key, preference_value), audit_log (action, table_name, timestamp)

    Status values are lowercase: employees.status is 'active' or 'terminated' (headcount counts only 'active'),
    projects.status is 'planning', 'active' or 'completed'. Department names are capitalized, e.g. 'Engineering'.
    """
    try:
        with sqlite3.connect(DB_PATH) as conn:
            return str(conn.execute(query).fetchall())
    except Exception as e:
        return f"Error executing query: {e}"


if __name__ == "__main__":
    mcp.run(transport="stdio", show_banner=False)
