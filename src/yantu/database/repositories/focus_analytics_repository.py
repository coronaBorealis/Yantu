from __future__ import annotations

from pathlib import Path
from typing import Any

from ..repository import database, init_db


class FocusAnalyticsRepository:
    """Read-only queries for the archived-focus review."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def tasks(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            return [dict(row) for row in connection.execute(
                "SELECT id, title, parent_task_id, parent_id, is_theme, deleted_at FROM tasks"
            )]

    def sessions(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            return [dict(row) for row in connection.execute("""
                SELECT f.id, f.task_id, f.mode, f.status, f.elapsed_seconds,
                       f.target_seconds, f.pause_count, f.paused_seconds,
                       f.started_at, f.ended_at, f.note,
                       COALESCE(f.task_title_snapshot, t.title, '已删除任务') AS task_title,
                       COALESCE(f.task_domain_snapshot, t.domain, 'unknown') AS task_domain,
                       COALESCE(f.project_name_snapshot, p.name, '未归入项目') AS project_name,
                       h.status AS habit_status, h.active_seconds, h.idle_seconds,
                       h.distraction_seconds, h.switch_count, h.quality_score
                FROM focus_sessions f
                LEFT JOIN tasks t ON t.id = f.task_id
                LEFT JOIN projects p ON p.id = t.project_id
                LEFT JOIN focus_habit_sessions h ON h.session_id = f.id
                WHERE f.archived = 1 AND f.session_type = 'focus' AND f.elapsed_seconds > 0
                ORDER BY f.ended_at DESC, f.id DESC
            """)]

    def app_usage(self, session_ids: list[str]) -> list[dict[str, Any]]:
        if not session_ids:
            return []
        result: list[dict[str, Any]] = []
        with database(self.db_path) as connection:
            for offset in range(0, len(session_ids), 900):
                batch = session_ids[offset:offset + 900]
                markers = ",".join("?" for _ in batch)
                result.extend(dict(row) for row in connection.execute(
                    f"SELECT session_id, process_name, active_seconds, idle_seconds "
                    f"FROM focus_app_usage WHERE session_id IN ({markers})", batch
                ))
        return result
