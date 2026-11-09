"""Phase 1 task logic: which MCP server a run launches, the Task 0 lab rows, Task 4's context line, Task 6's validator.

Run alone: uv run pytest tests/test_phase1_tasks.py
"""

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

PHASE1 = Path(__file__).resolve().parents[1] / "phase1"
sys.path.insert(0, str(PHASE1))
_excepthook = sys.excepthook
import t0_setup  # noqa: E402
import t6_structured_output as t6  # noqa: E402

import common  # noqa: E402

sys.excepthook = _excepthook
sys.path[:] = [entry for entry in sys.path if not entry.startswith(str(PHASE1))]

SCHEMA = """
CREATE TABLE departments (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, description TEXT,
    budget REAL);
CREATE TABLE employees (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT UNIQUE NOT NULL, first_name TEXT,
    last_name TEXT, email TEXT UNIQUE NOT NULL, job_title TEXT, department_id INTEGER NOT NULL, salary REAL,
    hire_date DATE, status TEXT DEFAULT 'active');
INSERT INTO departments (name) VALUES ('Engineering'), ('Sales'), ('Marketing'), ('Operations');
INSERT INTO employees (employee_id, email, department_id) VALUES ('DS0001', 'a@x', 1);
"""


def test_reference_runs_launch_the_reference_server() -> None:
    assert common.mcp_server_path(starter=False, task="t5") == common.MCP_SERVER_PATH


def test_task2_starter_may_launch_its_unfinished_server() -> None:
    assert common.mcp_server_path(starter=True, task="t2") == common.STARTER_SERVER_PATH


def test_later_starters_stop_while_the_task2_server_is_a_stub(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    stub = tmp_path / "mcp_server.py"
    stub.write_text(f'return "{common.UNFINISHED_SERVER}"')
    monkeypatch.setattr(common, "STARTER_SERVER_PATH", stub)
    with pytest.raises(NotImplementedError, match="Task 2 first"):
        common.mcp_server_path(starter=True, task="t3")


def test_later_starters_launch_the_finished_starter_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    server = tmp_path / "mcp_server.py"
    server.write_text("return str(rows)")
    monkeypatch.setattr(common, "STARTER_SERVER_PATH", server)
    assert common.mcp_server_path(starter=True, task="t8") == server


def test_shipped_starter_server_is_still_the_stub() -> None:
    assert common.UNFINISHED_SERVER in common.STARTER_SERVER_PATH.read_text()


def _counts(db: Path) -> tuple[int, int, int]:
    with sqlite3.connect(db) as conn:
        active, total = conn.execute("SELECT SUM(status = 'active'), COUNT(*) FROM employees").fetchone()
        departments = conn.execute("SELECT COUNT(*) FROM departments").fetchone()[0]
    return active, total, departments


def test_phase1_rows_add_terminated_staff_and_an_empty_department_once(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db = tmp_path / "datastream_corp.db"
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA)
    monkeypatch.setattr(t0_setup, "DB_PATH", db)
    t0_setup.add_phase1_rows()
    t0_setup.add_phase1_rows()
    assert _counts(db) == (1, 1 + len(t0_setup.TERMINATED_EMPLOYEES), 5)


class FakeManager(common.SummarizingConversationManager):
    """A summarizing manager whose removed-message count the test sets."""


def _model_call(tokens: int) -> SimpleNamespace:
    return SimpleNamespace(
        projected_input_tokens=tokens, agent=SimpleNamespace(model=SimpleNamespace(context_window_limit=2700))
    )


def test_context_line_only_when_messages_were_just_summarized(capsys: pytest.CaptureFixture[str]) -> None:
    manager = FakeManager()
    printer = common.ContextPrinter(manager)
    printer.show(_model_call(900))
    manager.removed_message_count = 3
    printer.show(_model_call(1500))
    printer.show(_model_call(1100))
    out = capsys.readouterr().out.strip()
    assert out == "[context] prompt ~1,500 of 2,700 tokens: older messages summarized (3 so far)"


def test_report_total_must_equal_the_departments() -> None:
    departments = [{"name": "HR", "active_employees": 84}, {"name": "Research", "active_employees": 0}]
    report = t6.DepartmentReport(title="t", summary="s", departments=departments, total_employees=84)
    assert report.total_employees == 84
    with pytest.raises(ValidationError, match="the departments add up to 84"):
        t6.DepartmentReport(title="t", summary="s", departments=departments, total_employees=1201)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_session_id_prefers_the_cli_session(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(common.SESSION_ENV, raising=False)
    assert common.session_id("alice_session") == "alice_session"
    monkeypatch.setenv(common.SESSION_ENV, "bob")
    assert common.session_id("alice_session") == "bob"


def test_an_empty_database_file_is_not_a_usable_copy(tmp_path: Path) -> None:
    db = tmp_path / "datastream_corp.db"
    assert not t0_setup.has_database(db)
    sqlite3.connect(db).close()
    assert db.exists() and not t0_setup.has_database(db)
    with sqlite3.connect(db) as conn:
        conn.executescript(SCHEMA)
    assert t0_setup.has_database(db)
