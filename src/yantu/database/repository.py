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

SCHEMA_VERSION = 8


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
                ,deleted_at TEXT
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

            CREATE TABLE IF NOT EXISTS semesters (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                periods_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedule_imports (
                id TEXT PRIMARY KEY,
                source_type TEXT NOT NULL,
                source_hash TEXT NOT NULL,
                imported_at TEXT NOT NULL,
                UNIQUE(source_type, source_hash)
            );

            CREATE TABLE IF NOT EXISTS courses (
                id TEXT PRIMARY KEY,
                semester_id TEXT NOT NULL REFERENCES semesters(id) ON DELETE CASCADE,
                import_id TEXT REFERENCES schedule_imports(id) ON DELETE SET NULL,
                name TEXT NOT NULL,
                teacher TEXT NOT NULL DEFAULT '',
                location TEXT NOT NULL DEFAULT '',
                color TEXT NOT NULL DEFAULT '#4f77bb',
                notes TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                deleted_at TEXT
            );

            CREATE TABLE IF NOT EXISTS course_meetings (
                id TEXT PRIMARY KEY,
                course_id TEXT NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
                weekday INTEGER NOT NULL CHECK(weekday BETWEEN 1 AND 7),
                start_period INTEGER NOT NULL CHECK(start_period > 0),
                end_period INTEGER NOT NULL CHECK(end_period >= start_period),
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                start_week INTEGER NOT NULL CHECK(start_week > 0),
                end_week INTEGER NOT NULL CHECK(end_week >= start_week),
                week_pattern TEXT NOT NULL DEFAULT 'all'
                    CHECK(week_pattern IN ('all', 'odd', 'even', 'custom')),
                custom_weeks_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS course_exceptions (
                id TEXT PRIMARY KEY,
                meeting_id TEXT NOT NULL REFERENCES course_meetings(id) ON DELETE CASCADE,
                occurrence_date TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'skip' CHECK(kind IN ('skip')),
                created_at TEXT NOT NULL,
                UNIQUE(meeting_id, occurrence_date, kind)
            );

            CREATE INDEX IF NOT EXISTS idx_courses_semester
                ON courses(semester_id, deleted_at);
            CREATE INDEX IF NOT EXISTS idx_course_meetings_course
                ON course_meetings(course_id);
            CREATE INDEX IF NOT EXISTS idx_course_exceptions_meeting_date
                ON course_exceptions(meeting_id, occurrence_date);

            CREATE TABLE IF NOT EXISTS planning_profiles (
                id TEXT PRIMARY KEY,
                workday_start TEXT NOT NULL DEFAULT '09:00',
                workday_end TEXT NOT NULL DEFAULT '18:00',
                active_weekdays_json TEXT NOT NULL DEFAULT '[1,2,3,4,5,6,7]',
                focus_minutes INTEGER NOT NULL DEFAULT 25 CHECK(focus_minutes BETWEEN 10 AND 120),
                short_break_minutes INTEGER NOT NULL DEFAULT 5 CHECK(short_break_minutes BETWEEN 1 AND 30),
                long_break_minutes INTEGER NOT NULL DEFAULT 15 CHECK(long_break_minutes BETWEEN 5 AND 60),
                long_break_after INTEGER NOT NULL DEFAULT 4 CHECK(long_break_after BETWEEN 2 AND 8),
                max_continuous_focus INTEGER NOT NULL DEFAULT 100 CHECK(max_continuous_focus BETWEEN 25 AND 240),
                buffer_minutes INTEGER NOT NULL DEFAULT 10 CHECK(buffer_minutes BETWEEN 0 AND 60),
                use_pomodoro INTEGER NOT NULL DEFAULT 1 CHECK(use_pomodoro IN (0,1)),
                timezone TEXT NOT NULL DEFAULT 'Asia/Shanghai',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS planning_runs (
                id TEXT PRIMARY KEY,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL CHECK(status IN ('confirmed','cancelled')),
                strategy TEXT NOT NULL CHECK(strategy IN ('rule','ai','manual')),
                input_snapshot_json TEXT NOT NULL DEFAULT '{}',
                warnings_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                confirmed_at TEXT
            );

            CREATE TABLE IF NOT EXISTS plan_blocks (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES planning_runs(id) ON DELETE CASCADE,
                task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                block_date TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                block_type TEXT NOT NULL CHECK(block_type IN ('focus','short_break','long_break','buffer')),
                planned_minutes INTEGER NOT NULL CHECK(planned_minutes > 0),
                source TEXT NOT NULL CHECK(source IN ('rule','ai','manual')),
                status TEXT NOT NULL DEFAULT 'planned' CHECK(status IN ('planned','completed','skipped')),
                locked INTEGER NOT NULL DEFAULT 0 CHECK(locked IN (0,1)),
                rationale TEXT NOT NULL DEFAULT '',
                sequence INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_plan_blocks_date
                ON plan_blocks(block_date, start_time);
            CREATE INDEX IF NOT EXISTS idx_plan_blocks_run
                ON plan_blocks(run_id, sequence);

            CREATE TABLE IF NOT EXISTS app_settings (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS focus_sessions (
                id TEXT PRIMARY KEY,
                task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                plan_block_id TEXT REFERENCES plan_blocks(id) ON DELETE SET NULL,
                parent_session_id TEXT REFERENCES focus_sessions(id) ON DELETE SET NULL,
                session_type TEXT NOT NULL
                    CHECK(session_type IN ('focus','short_break','long_break')),
                mode TEXT NOT NULL CHECK(mode IN ('pomodoro','free')),
                status TEXT NOT NULL
                    CHECK(status IN ('running','paused','awaiting_action','completed','cancelled')),
                target_seconds INTEGER NOT NULL DEFAULT 0 CHECK(target_seconds >= 0),
                elapsed_seconds INTEGER NOT NULL DEFAULT 0 CHECK(elapsed_seconds >= 0),
                paused_seconds INTEGER NOT NULL DEFAULT 0 CHECK(paused_seconds >= 0),
                pause_count INTEGER NOT NULL DEFAULT 0 CHECK(pause_count >= 0),
                started_at TEXT NOT NULL,
                last_resumed_at TEXT,
                ended_at TEXT,
                time_entry_id TEXT REFERENCES time_entries(id) ON DELETE SET NULL,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_focus_sessions_task_started
                ON focus_sessions(task_id, started_at DESC);
            CREATE INDEX IF NOT EXISTS idx_focus_sessions_status
                ON focus_sessions(status, started_at DESC);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_focus_one_active
                ON focus_sessions ((1))
                WHERE status IN ('running','paused','awaiting_action');

            CREATE TABLE IF NOT EXISTS task_planning_preferences (
                task_id TEXT PRIMARY KEY REFERENCES tasks(id) ON DELETE CASCADE,
                planning_mode TEXT NOT NULL DEFAULT 'auto'
                    CHECK(planning_mode IN ('auto','manual','paused')),
                preferred_session_minutes INTEGER
                    CHECK(preferred_session_minutes IS NULL OR preferred_session_minutes BETWEEN 5 AND 240),
                minimum_session_minutes INTEGER NOT NULL DEFAULT 15
                    CHECK(minimum_session_minutes BETWEEN 5 AND 120),
                daily_limit_minutes INTEGER
                    CHECK(daily_limit_minutes IS NULL OR daily_limit_minutes > 0),
                preferred_weekdays_json TEXT NOT NULL DEFAULT '[]',
                earliest_start_time TEXT,
                latest_end_time TEXT,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS research_sources (
                id TEXT PRIMARY KEY,
                provider TEXT NOT NULL DEFAULT 'zotero',
                library_type TEXT NOT NULL DEFAULT 'user'
                    CHECK(library_type IN ('user','group','local')),
                library_id TEXT NOT NULL DEFAULT '',
                display_name TEXT NOT NULL,
                access_mode TEXT NOT NULL DEFAULT 'local'
                    CHECK(access_mode IN ('local','web')),
                base_url TEXT NOT NULL DEFAULT 'http://127.0.0.1:23119/api',
                server_id TEXT,
                enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
                auto_sync INTEGER NOT NULL DEFAULT 0 CHECK(auto_sync IN (0,1)),
                sync_cursor TEXT,
                last_synced_at TEXT,
                last_sync_status TEXT NOT NULL DEFAULT 'never'
                    CHECK(last_sync_status IN ('never','ok','error','running')),
                last_sync_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(provider, library_type, library_id)
            );

            CREATE TABLE IF NOT EXISTS research_items (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
                external_key TEXT NOT NULL,
                item_type TEXT NOT NULL DEFAULT 'journalArticle',
                title TEXT NOT NULL,
                abstract TEXT NOT NULL DEFAULT '',
                creators_json TEXT NOT NULL DEFAULT '[]',
                publication_title TEXT NOT NULL DEFAULT '',
                published_at TEXT,
                doi TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                zotero_uri TEXT NOT NULL DEFAULT '',
                attachment_path TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                external_version INTEGER,
                collected_at TEXT,
                last_synced_at TEXT,
                deleted_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(source_id, external_key)
            );

            CREATE TABLE IF NOT EXISTS task_research_items (
                task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                research_item_id TEXT NOT NULL REFERENCES research_items(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL DEFAULT 'reference'
                    CHECK(relation_type IN ('reference','reading','review','citation','output')),
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY(task_id, research_item_id, relation_type)
            );

            CREATE TABLE IF NOT EXISTS project_research_items (
                project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                research_item_id TEXT NOT NULL REFERENCES research_items(id) ON DELETE CASCADE,
                relation_type TEXT NOT NULL DEFAULT 'reference'
                    CHECK(relation_type IN ('reference','reading','review','citation','output')),
                import_mode TEXT NOT NULL DEFAULT 'manual'
                    CHECK(import_mode IN ('manual','collection','search')),
                source_collection_key TEXT,
                note TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                PRIMARY KEY(project_id, research_item_id)
            );

            CREATE TABLE IF NOT EXISTS research_inbox (
                research_item_id TEXT PRIMARY KEY REFERENCES research_items(id) ON DELETE CASCADE,
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending','converted','dismissed')),
                task_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                added_at TEXT NOT NULL,
                resolved_at TEXT
            );

            CREATE TABLE IF NOT EXISTS research_sync_runs (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL REFERENCES research_sources(id) ON DELETE CASCADE,
                status TEXT NOT NULL CHECK(status IN ('running','completed','failed')),
                cursor_before TEXT,
                cursor_after TEXT,
                imported_count INTEGER NOT NULL DEFAULT 0,
                deleted_count INTEGER NOT NULL DEFAULT 0,
                error TEXT NOT NULL DEFAULT '',
                started_at TEXT NOT NULL,
                ended_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_research_items_source
                ON research_items(source_id, deleted_at, collected_at DESC);
            CREATE INDEX IF NOT EXISTS idx_task_research_task
                ON task_research_items(task_id, relation_type);
            CREATE INDEX IF NOT EXISTS idx_project_research_project
                ON project_research_items(project_id, relation_type, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_research_inbox_status
                ON research_inbox(status, added_at DESC);
            CREATE INDEX IF NOT EXISTS idx_research_sync_source_started
                ON research_sync_runs(source_id, started_at DESC);
            """
        )
        now = utc_now()
        connection.execute(
            """
            INSERT OR IGNORE INTO planning_profiles
                (id, created_at, updated_at)
            VALUES ('default', ?, ?)
            """,
            (now, now),
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
                "deleted_at": "TEXT",
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
        _add_missing_columns(
            connection,
            "research_sources",
            {
                "access_mode": "TEXT NOT NULL DEFAULT 'local' CHECK(access_mode IN ('local','web'))",
                "base_url": "TEXT NOT NULL DEFAULT 'http://127.0.0.1:23119/api'",
                "server_id": "TEXT",
                "auto_sync": "INTEGER NOT NULL DEFAULT 0 CHECK(auto_sync IN (0,1))",
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
    deleted: bool = False,
) -> list[dict[str, Any]]:
    clauses: list[str] = ["deleted_at IS NOT NULL" if deleted else "deleted_at IS NULL"]
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


def get_task(
    db_path: Path | str, task_id: str, *, include_deleted: bool = False
) -> dict[str, Any] | None:
    with database(db_path) as connection:
        suffix = "" if include_deleted else " AND deleted_at IS NULL"
        row = connection.execute(
            f"SELECT * FROM tasks WHERE id = ?{suffix}", (task_id,)
        ).fetchone()
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
        cursor = connection.execute(
            "UPDATE tasks SET deleted_at = ?, updated_at = ? WHERE id = ? AND deleted_at IS NULL",
            (utc_now(), utc_now(), task_id),
        )
        return cursor.rowcount > 0


def restore_task(db_path: Path | str, task_id: str) -> bool:
    with database(db_path) as connection:
        cursor = connection.execute(
            "UPDATE tasks SET deleted_at = NULL, updated_at = ? WHERE id = ? AND deleted_at IS NOT NULL",
            (utc_now(), task_id),
        )
        return cursor.rowcount > 0


def permanently_delete_task(db_path: Path | str, task_id: str) -> bool:
    with database(db_path) as connection:
        cursor = connection.execute(
            "DELETE FROM tasks WHERE id = ? AND deleted_at IS NOT NULL", (task_id,)
        )
        return cursor.rowcount > 0


def task_count(db_path: Path | str) -> int:
    with database(db_path) as connection:
        return int(
            connection.execute(
                "SELECT COUNT(*) FROM tasks WHERE deleted_at IS NULL"
            ).fetchone()[0]
        )
