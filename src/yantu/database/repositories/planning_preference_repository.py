from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..repository import database, init_db


class TaskPlanningPreferenceRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def get(self, task_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM task_planning_preferences WHERE task_id=?", (task_id,)
            ).fetchone()
        if not row:
            return None
        record = dict(row)
        record["preferred_weekdays"] = json.loads(
            record.pop("preferred_weekdays_json") or "[]"
        )
        return record

    def list_all(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            task_ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT task_id FROM task_planning_preferences ORDER BY task_id"
                ).fetchall()
            ]
        return [item for task_id in task_ids if (item := self.get(task_id)) is not None]

    def upsert(self, values: dict[str, Any]) -> dict[str, Any]:
        stored = dict(values)
        stored["preferred_weekdays_json"] = json.dumps(
            stored.pop("preferred_weekdays"), ensure_ascii=False
        )
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO task_planning_preferences
                    (task_id,planning_mode,preferred_session_minutes,
                     minimum_session_minutes,daily_limit_minutes,
                     preferred_weekdays_json,earliest_start_time,latest_end_time,updated_at)
                VALUES
                    (:task_id,:planning_mode,:preferred_session_minutes,
                     :minimum_session_minutes,:daily_limit_minutes,
                     :preferred_weekdays_json,:earliest_start_time,:latest_end_time,:updated_at)
                ON CONFLICT(task_id) DO UPDATE SET
                    planning_mode=excluded.planning_mode,
                    preferred_session_minutes=excluded.preferred_session_minutes,
                    minimum_session_minutes=excluded.minimum_session_minutes,
                    daily_limit_minutes=excluded.daily_limit_minutes,
                    preferred_weekdays_json=excluded.preferred_weekdays_json,
                    earliest_start_time=excluded.earliest_start_time,
                    latest_end_time=excluded.latest_end_time,
                    updated_at=excluded.updated_at
                """,
                stored,
            )
        result = self.get(str(values["task_id"]))
        assert result is not None
        return result
