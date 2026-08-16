from __future__ import annotations

import json
import sqlite3
import warnings
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from ..common import utc_now
from .config import DEFAULT_DB_PATH
from .constants import DOMAINS, PRIORITIES, STATUSES

SCHEMA_VERSION = 2


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _add_missing_columns(
    connection: sqlite3.Connection,
    table: str,
    definitions: dict[str, str],
) -> None:
    existing = _column_names(connection, table)
    for name, definition in definitions.items():
        if name not in existing:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def connect(db_path: Path | str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def database(db_path: Path | str = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    connection = connect(db_path)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def init_db(db_path: Path | str = DEFAULT_DB_PATH) -> None:
    with database(db_path) as connection:
        current_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if current_version > SCHEMA_VERSION:
            warnings.warn(
                f"数据库版本 {current_version} 高于当前支持版本 {SCHEMA_VERSION}，将保留版本号；兼容性无法保证。",
                RuntimeWarning,
                stacklevel=2,
            )
            return
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                domain TEXT NOT NULL CHECK(domain IN ('research', 'course', 'personal')),
                description TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT '个人',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                parent_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                parent_task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
                title TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT 'inbox'
                    CHECK(domain IN ('research', 'course', 'personal', 'inbox')),
                subcategory TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]',
                description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                start_date TEXT,
                due_date TEXT,
                deadline TEXT,
                estimated_minutes INTEGER NOT NULL DEFAULT 0 CHECK(estimated_minutes >= 0),
                actual_minutes INTEGER NOT NULL DEFAULT 0 CHECK(actual_minutes >= 0),
                estimated_hours REAL NOT NULL DEFAULT 0 CHECK(estimated_hours >= 0),
                actual_hours REAL NOT NULL DEFAULT 0 CHECK(actual_hours >= 0),
                priority TEXT NOT NULL DEFAULT 'medium'
                    CHECK(priority IN ('low', 'medium', 'high', 'urgent')),
                status TEXT NOT NULL DEFAULT 'not_started'
                    CHECK(status IN ('not_started', 'in_progress', 'waiting', 'completed', 'cancelled')),
                progress INTEGER NOT NULL DEFAULT 0 CHECK(progress BETWEEN 0 AND 100),
                is_recurring INTEGER NOT NULL DEFAULT 0 CHECK(is_recurring IN (0, 1)),
                recurrence_rule TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                completed_at TEXT,
                sort_order INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS time_entries (
                id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL,
                ended_at TEXT,
                minutes INTEGER NOT NULL DEFAULT 0 CHECK(minutes >= 0),
                start_time TEXT,
                end_time TEXT,
                duration INTEGER NOT NULL DEFAULT 0 CHECK(duration >= 0),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tasks_domain_status
                ON tasks(domain, status);
            CREATE INDEX IF NOT EXISTS idx_tasks_due_date
                ON tasks(due_date) WHERE due_date IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_tasks_start_date
                ON tasks(start_date) WHERE start_date IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_tasks_parent_id
                ON tasks(parent_id) WHERE parent_id IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_time_entries_task_id
                ON time_entries(task_id);
            """
        )
        _add_missing_columns(connection, "projects", {"category": "TEXT NOT NULL DEFAULT '个人'"})
        _add_missing_columns(
            connection,
            "tasks",
            {
                "parent_task_id": "TEXT REFERENCES tasks(id) ON DELETE SET NULL",
                "deadline": "TEXT",
                "estimated_hours": "REAL NOT NULL DEFAULT 0 CHECK(estimated_hours >= 0)",
                "actual_hours": "REAL NOT NULL DEFAULT 0 CHECK(actual_hours >= 0)",
            },
        )
        _add_missing_columns(
            connection,
            "time_entries",
            {
                "start_time": "TEXT",
                "end_time": "TEXT",
                "duration": "INTEGER NOT NULL DEFAULT 0 CHECK(duration >= 0)",
            },
        )
        if current_version < SCHEMA_VERSION:
            connection.execute(
                """
                UPDATE projects
                SET category = CASE domain
                    WHEN 'research' THEN '科研'
                    WHEN 'course' THEN '课程'
                    ELSE '个人'
                END
                WHERE category IS NULL OR category = '' OR category = '个人' AND domain != 'personal'
                """
            )
            connection.execute(
                """
                UPDATE tasks
                SET parent_task_id = COALESCE(parent_task_id, parent_id),
                    deadline = COALESCE(deadline, due_date),
                    estimated_hours = CASE
                        WHEN estimated_hours = 0 AND estimated_minutes > 0 THEN estimated_minutes / 60.0
                        ELSE estimated_hours
                    END,
                    actual_hours = CASE
                        WHEN actual_hours = 0 AND actual_minutes > 0 THEN actual_minutes / 60.0
                        ELSE actual_hours
                    END
                """
            )
            connection.execute(
                """
                UPDATE time_entries
                SET start_time = COALESCE(start_time, started_at),
                    end_time = COALESCE(end_time, ended_at),
                    duration = CASE WHEN duration = 0 AND minutes > 0 THEN minutes ELSE duration END
                """
            )
        connection.execute(
            """
            UPDATE tasks
            SET parent_id = parent_task_id,
                due_date = deadline,
                estimated_minutes = ROUND(estimated_hours * 60),
                actual_minutes = ROUND(actual_hours * 60)
            """
        )
        connection.execute(
            """
            UPDATE time_entries
            SET start_time = COALESCE(start_time, started_at),
                started_at = COALESCE(start_time, started_at),
                ended_at = end_time,
                minutes = duration
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_project_status ON tasks(project_id, status)"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_deadline ON tasks(deadline) WHERE deadline IS NOT NULL"
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_tasks_parent_task_id ON tasks(parent_task_id) WHERE parent_task_id IS NOT NULL"
        )
        if current_version < SCHEMA_VERSION:
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        connection.execute("PRAGMA optimize")


def task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    try:
        task["tags"] = json.loads(task.get("tags") or "[]")
    except json.JSONDecodeError:
        task["tags"] = []
    task["is_recurring"] = bool(task["is_recurring"])
    return task


def _with_task_aliases(task: dict[str, Any]) -> dict[str, Any]:
    record = dict(task)
    if "parent_task_id" in record:
        record["parent_id"] = record["parent_task_id"]
    elif "parent_id" in record:
        record["parent_task_id"] = record["parent_id"]
    if "deadline" in record:
        record["due_date"] = record["deadline"]
    elif "due_date" in record:
        record["deadline"] = record["due_date"]
    if "estimated_hours" in record:
        record["estimated_minutes"] = round(float(record["estimated_hours"] or 0) * 60)
    elif "estimated_minutes" in record:
        record["estimated_hours"] = round(float(record["estimated_minutes"] or 0) / 60, 4)
    if "actual_hours" in record:
        record["actual_minutes"] = round(float(record["actual_hours"] or 0) * 60)
    elif "actual_minutes" in record:
        record["actual_hours"] = round(float(record["actual_minutes"] or 0) / 60, 4)
    return record


def list_tasks(
    db_path: Path | str,
    *,
    domain: str | None = None,
    status: str | None = None,
    project_id: str | None = None,
    sort_by_deadline: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    parameters: list[str] = []
    if domain:
        clauses.append("domain = ?")
        parameters.append(domain)
    if status:
        clauses.append("status = ?")
        parameters.append(status)
    if project_id:
        clauses.append("project_id = ?")
        parameters.append(project_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order_by = """
        CASE WHEN deadline IS NULL THEN 1 ELSE 0 END,
        deadline,
        created_at DESC
    """ if sort_by_deadline else """
        CASE status WHEN 'completed' THEN 1 WHEN 'cancelled' THEN 2 ELSE 0 END,
        CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
        CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
        due_date,
        created_at DESC
    """
    sql = f"""
        SELECT * FROM tasks
        {where}
        ORDER BY {order_by}
    """
    with database(db_path) as connection:
        return [task_from_row(row) for row in connection.execute(sql, parameters)]


def get_task(db_path: Path | str, task_id: str) -> dict[str, Any] | None:
    with database(db_path) as connection:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return task_from_row(row) if row else None


def insert_task(db_path: Path | str, task: dict[str, Any]) -> dict[str, Any]:
    task = _with_task_aliases(task)
    columns = list(task)
    values = [json.dumps(task[key], ensure_ascii=False) if key == "tags" else task[key] for key in columns]
    placeholders = ", ".join("?" for _ in columns)
    with database(db_path) as connection:
        connection.execute(
            f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({placeholders})",
            values,
        )
    result = get_task(db_path, task["id"])
    assert result is not None
    return result


def insert_tasks(db_path: Path | str, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Insert a task tree atomically so a partial confirmation is never saved."""
    if not tasks:
        return []
    tasks = [_with_task_aliases(task) for task in tasks]
    with database(db_path) as connection:
        for task in tasks:
            columns = list(task)
            values = [
                json.dumps(task[key], ensure_ascii=False) if key == "tags" else task[key]
                for key in columns
            ]
            placeholders = ", ".join("?" for _ in columns)
            connection.execute(
                f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({placeholders})",
                values,
            )
        rows = [
            connection.execute("SELECT * FROM tasks WHERE id = ?", (task["id"],)).fetchone()
            for task in tasks
        ]
    return [task_from_row(row) for row in rows]


def update_task(db_path: Path | str, task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    if not changes:
        return get_task(db_path, task_id)
    changes = _with_task_aliases(changes)
    columns = list(changes)
    values = [json.dumps(changes[key], ensure_ascii=False) if key == "tags" else changes[key] for key in columns]
    assignments = ", ".join(f"{column} = ?" for column in columns)
    with database(db_path) as connection:
        cursor = connection.execute(
            f"UPDATE tasks SET {assignments} WHERE id = ?",
            [*values, task_id],
        )
        if cursor.rowcount == 0:
            return None
    return get_task(db_path, task_id)


def delete_task(db_path: Path | str, task_id: str) -> bool:
    with database(db_path) as connection:
        cursor = connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return cursor.rowcount > 0


def task_count(db_path: Path | str) -> int:
    with database(db_path) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
