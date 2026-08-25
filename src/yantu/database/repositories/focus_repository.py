from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..repository import database, init_db


ACTIVE_STATUSES = ("running", "paused", "awaiting_action")


class FocusRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def get(self, session_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM focus_sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return dict(row) if row else None

    def active(self) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT f.*, t.title AS task_title
                FROM focus_sessions f
                LEFT JOIN tasks t ON t.id = f.task_id
                WHERE f.status IN ('running','paused','awaiting_action')
                ORDER BY f.created_at DESC LIMIT 1
                """
            ).fetchone()
        return dict(row) if row else None

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        columns = list(record)
        try:
            with database(self.db_path) as connection:
                connection.execute(
                    f"INSERT INTO focus_sessions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [record[key] for key in columns],
                )
        except sqlite3.IntegrityError as exc:
            if "idx_focus_one_active" in str(exc) or "focus_sessions.1" in str(exc):
                raise ValueError("已有正在进行的专注或休息") from exc
            raise
        result = self.get(str(record["id"]))
        assert result is not None
        return result

    def get_plan_block(self, block_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM plan_blocks WHERE id = ?", (block_id,)
            ).fetchone()
        return dict(row) if row else None

    def update(self, session_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        if not changes:
            return self.get(session_id)
        columns = list(changes)
        with database(self.db_path) as connection:
            cursor = connection.execute(
                f"UPDATE focus_sessions SET {', '.join(f'{key} = ?' for key in columns)} WHERE id = ?",
                [*[changes[key] for key in columns], session_id],
            )
            if cursor.rowcount == 0:
                return None
        return self.get(session_id)

    def finish(
        self,
        session_id: str,
        *,
        elapsed_seconds: int,
        ended_at: str,
        updated_at: str,
        final_status: str,
        time_entry: dict[str, Any] | None,
        break_session: dict[str, Any] | None,
    ) -> dict[str, Any]:
        with database(self.db_path) as connection:
            session = connection.execute(
                "SELECT * FROM focus_sessions WHERE id = ?", (session_id,)
            ).fetchone()
            if not session:
                raise ValueError("专注会话不存在")
            if session["time_entry_id"]:
                return dict(session)
            if session["status"] not in ACTIVE_STATUSES:
                raise ValueError("当前专注会话不能结束")
            time_entry_id = None
            if time_entry:
                time_entry_id = str(time_entry["id"])
                connection.execute(
                    """
                    INSERT INTO time_entries
                        (id,task_id,started_at,ended_at,minutes,start_time,end_time,duration,note,created_at)
                    VALUES
                        (:id,:task_id,:start_time,:end_time,:duration,:start_time,:end_time,:duration,:note,:created_at)
                    """,
                    time_entry,
                )
                task = connection.execute(
                    "SELECT actual_minutes FROM tasks WHERE id = ?", (time_entry["task_id"],)
                ).fetchone()
                if task:
                    actual = max(0, int(task[0] or 0) + int(time_entry["duration"]))
                    connection.execute(
                        """
                        UPDATE tasks
                        SET actual_minutes = ?, actual_hours = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (actual, actual / 60.0, updated_at, time_entry["task_id"]),
                    )
                if session["plan_block_id"]:
                    block = connection.execute(
                        "SELECT planned_minutes FROM plan_blocks WHERE id = ?",
                        (session["plan_block_id"],),
                    ).fetchone()
                    if block and elapsed_seconds >= int(block[0]) * 60:
                        connection.execute(
                            "UPDATE plan_blocks SET status = 'completed', updated_at = ? WHERE id = ?",
                            (updated_at, session["plan_block_id"]),
                        )
            connection.execute(
                """
                UPDATE focus_sessions
                SET status = ?, elapsed_seconds = ?, ended_at = ?,
                    last_resumed_at = NULL, time_entry_id = ?, updated_at = ?
                WHERE id = ?
                """,
                (final_status, elapsed_seconds, ended_at, time_entry_id, updated_at, session_id),
            )
            if break_session:
                columns = list(break_session)
                connection.execute(
                    f"INSERT INTO focus_sessions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [break_session[key] for key in columns],
                )
        result = self.get(session_id)
        assert result is not None
        return result

    def history(
        self, *, start: str | None = None, end: str | None = None,
        task_id: str | None = None, finished_only: bool = False,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[str] = []
        if start:
            clauses.append("f.started_at >= ?")
            params.append(start)
        if end:
            clauses.append("f.started_at < ?")
            params.append(end)
        if task_id:
            clauses.append("f.task_id = ?")
            params.append(task_id)
        if finished_only:
            clauses.append("f.status IN ('completed','cancelled')")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with database(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT f.*, t.title AS task_title, t.domain AS task_domain
                FROM focus_sessions f
                LEFT JOIN tasks t ON t.id = f.task_id
                {where}
                ORDER BY f.started_at DESC
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def import_finished(self, records: list[dict[str, Any]]) -> int:
        imported = 0
        with database(self.db_path) as connection:
            for source in records:
                if source.get("status") not in {"completed", "cancelled"}:
                    continue
                if connection.execute("SELECT 1 FROM focus_sessions WHERE id = ?", (source.get("id"),)).fetchone():
                    continue
                allowed = {
                    "id", "task_id", "plan_block_id", "parent_session_id", "session_type",
                    "mode", "status", "target_seconds", "elapsed_seconds", "paused_seconds",
                    "pause_count", "started_at", "last_resumed_at", "ended_at", "time_entry_id",
                    "note", "created_at", "updated_at",
                }
                record = {key: source.get(key) for key in allowed}
                # A backup restores focus history after tasks, but session parents and
                # old TimeEntry identifiers are intentionally not part of that ledger.
                record["parent_session_id"] = None
                record["plan_block_id"] = None
                record["time_entry_id"] = None
                if record.get("task_id") and not connection.execute(
                    "SELECT 1 FROM tasks WHERE id = ?", (record["task_id"],)
                ).fetchone():
                    record["task_id"] = None
                columns = list(record)
                connection.execute(
                    f"INSERT INTO focus_sessions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [record[key] for key in columns],
                )
                imported += 1
        return imported
