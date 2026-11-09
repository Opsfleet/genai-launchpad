"""Task 0: download your own copy of the DataStream Corp database and verify the database, AWS identity and gateway.

Phase 1 adds a few rows to its copy (Phase 2 seeds the unchanged download): an empty Research department and six
terminated employees. They make the "active employees only" and "keep empty departments" rules of Tasks 6 and 8
visible; every active count stays as downloaded (1,201 active employees).
"""

import hashlib
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

import boto3
import openai
import requests
from strands import Agent

from common import AWS_REGION, DB_PATH, MODEL_ID, litellm_gateway, make_model

DB_URL = "https://genai-launchpad.aws.opsfleet.com/assets/datastream_corp.db"
DB_SHA256 = "41a50fc1f8a64f41fd476f2c01189c2dec9928ed75e8f85e58ddbc71f3e6b575"
"""Checksum of the published copy: a truncated or wrong download fails loudly instead of as 'no such table'."""
EMPTY_DEPARTMENT = ("Research", "Applied research; the team is hired next quarter", 400000)
TERMINATED_EMPLOYEES = [
    ("DS1202", "Mark", "Ellis", "Senior Software Engineer", "Engineering", 128000, "2021-03-15"),
    ("DS1203", "Priya", "Nair", "Software Engineer", "Engineering", 104000, "2022-07-01"),
    ("DS1204", "Tom", "Becker", "Account Executive", "Sales", 72000, "2020-09-14"),
    ("DS1205", "Lucia", "Romero", "Sales Development Representative", "Sales", 58000, "2023-02-06"),
    ("DS1206", "Owen", "Price", "Marketing Specialist", "Marketing", 66000, "2021-11-22"),
    ("DS1207", "Grace", "Kim", "Operations Coordinator", "Operations", 52000, "2022-04-18"),
]
"""(employee_id, first, last, job title, department, salary, hire date) of the Phase 1 status = 'terminated' rows."""
INSERT_TERMINATED = """INSERT OR IGNORE INTO employees
    (employee_id, first_name, last_name, email, job_title, department_id, salary, hire_date, status)
    SELECT ?, ?, ?, ?, ?, id, ?, ?, 'terminated'
    FROM departments WHERE name = ?"""


def has_database(path: Path) -> bool:
    """Whether `path` holds the real database, not the empty file `sqlite3.connect` creates when something opened it
    before this task downloaded it."""
    if not path.exists():
        return False
    try:
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as conn:
            conn.execute("SELECT 1 FROM employees LIMIT 1")
    except sqlite3.DatabaseError:
        return False
    return True


def download_database() -> str:
    """Download the database unless a usable copy is already here, then add the Phase 1 rows (idempotent)."""
    if not has_database(DB_PATH):
        response = requests.get(DB_URL, timeout=60)
        response.raise_for_status()
        if hashlib.sha256(response.content).hexdigest() != DB_SHA256:
            raise RuntimeError(f"{DB_URL} did not match the expected checksum; download it again")
        DB_PATH.write_bytes(response.content)
    add_phase1_rows()
    return f"{DB_PATH.name} ({DB_PATH.stat().st_size:,} bytes)"


def add_phase1_rows() -> None:
    """Add the empty Research department and the terminated employees unless they are already there."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("INSERT OR IGNORE INTO departments (name, description, budget) VALUES (?, ?, ?)", EMPTY_DEPARTMENT)
        conn.executemany(
            INSERT_TERMINATED,
            [
                (eid, first, last, f"{first}.{last}@datastream.corp".lower(), title, salary, hired, dept)
                for eid, first, last, title, dept, salary, hired in TERMINATED_EMPLOYEES
            ],
        )


def check_database() -> str:
    """Count active and all employees and list the departments."""
    with sqlite3.connect(DB_PATH) as conn:
        active, total = conn.execute("SELECT SUM(status = 'active'), COUNT(*) FROM employees").fetchone()
        departments = [row[0] for row in conn.execute("SELECT name FROM departments ORDER BY id")]
    return f"{active} active employees ({total} in total); departments: {', '.join(departments)}"


def check_aws() -> str:
    """The ARN of the AWS identity in use."""
    return boto3.client("sts", region_name=AWS_REGION).get_caller_identity()["Arn"]


def check_gateway() -> str:
    """One real model call through the LiteLLM gateway (a gateway that is off says so instead of a raw 503)."""
    try:
        reply = Agent(model=make_model(), system_prompt="Reply with exactly: OK", callback_handler=None)("ping")
    except openai.APIStatusError as error:
        hint = litellm_gateway.gateway_down(error.status_code)
        if hint is None:
            raise
        raise RuntimeError(hint) from error
    return f"{MODEL_ID} via LiteLLM gateway replied: {str(reply).strip()[:40]}"


CHECKS = [
    ("Database download", download_database),
    ("Database connection", check_database),
    ("AWS credentials", check_aws),
    ("LiteLLM gateway", check_gateway),
]


def main() -> int:
    failures = 0
    for name, check in CHECKS:
        try:
            print(f"PASS  {name}: {check()}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {name}: {e}")
    print("\nSetup complete, ready for Task 1." if not failures else f"\n{failures} check(s) failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
