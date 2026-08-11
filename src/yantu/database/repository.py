from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB_PATH = REPOSITORY_ROOT / "data" / "yantu.db"

DOMAINS = {"research", "course", "personal", "inbox"}
STATUSES = {"not_started", "in_progress", "waiting", "completed", "cancelled"}
PRIORITIES = {"low", "medium", "high", "urgent"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                domain TEXT NOT NULL CHECK(domain IN ('research', 'course', 'personal')),
                description TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                parent_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
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
                estimated_minutes INTEGER NOT NULL DEFAULT 0 CHECK(estimated_minutes >= 0),
                actual_minutes INTEGER NOT NULL DEFAULT 0 CHECK(actual_minutes >= 0),
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
        connection.execute("PRAGMA optimize")


def task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    try:
        task["tags"] = json.loads(task.get("tags") or "[]")
    except json.JSONDecodeError:
        task["tags"] = []
    task["is_recurring"] = bool(task["is_recurring"])
    return task


def list_tasks(
    db_path: Path | str,
    *,
    domain: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    parameters: list[str] = []
    if domain:
        clauses.append("domain = ?")
        parameters.append(domain)
    if status:
        clauses.append("status = ?")
        parameters.append(status)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"""
        SELECT * FROM tasks
        {where}
        ORDER BY
            CASE status WHEN 'completed' THEN 1 WHEN 'cancelled' THEN 2 ELSE 0 END,
            CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
            CASE WHEN due_date IS NULL THEN 1 ELSE 0 END,
            due_date,
            created_at DESC
    """
    with database(db_path) as connection:
        return [task_from_row(row) for row in connection.execute(sql, parameters)]


def get_task(db_path: Path | str, task_id: str) -> dict[str, Any] | None:
    with database(db_path) as connection:
        row = connection.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return task_from_row(row) if row else None


def insert_task(db_path: Path | str, task: dict[str, Any]) -> dict[str, Any]:
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
