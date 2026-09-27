from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..repository import database, init_db


def _decode(row: Any) -> dict[str, Any] | None:
    if not row:
        return None
    value = dict(row)
    if "allowed_apps_json" in value:
        try:
            value["allowed_apps"] = json.loads(value.pop("allowed_apps_json") or "[]")
        except json.JSONDecodeError:
            value["allowed_apps"] = []
    if "enabled" in value:
        value["enabled"] = bool(value["enabled"])
    return value


class FocusHabitRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def profiles(self, *, include_disabled: bool = False) -> list[dict[str, Any]]:
        where = "" if include_disabled else "WHERE enabled = 1"
        with database(self.db_path) as connection:
            rows = connection.execute(
                f"SELECT * FROM focus_habit_profiles {where} ORDER BY enabled DESC, updated_at DESC"
            ).fetchall()
        return [_decode(row) for row in rows if row]

    def profile(self, profile_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM focus_habit_profiles WHERE id = ?", (profile_id,)
            ).fetchone()
        return _decode(row)

    def save_profile(self, record: dict[str, Any]) -> dict[str, Any]:
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO focus_habit_profiles
                    (id,name,allowed_apps_json,idle_threshold_seconds,
                     switch_warning_count,enabled,created_at,updated_at)
                VALUES (:id,:name,:allowed_apps_json,:idle_threshold_seconds,
                        :switch_warning_count,:enabled,:created_at,:updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    allowed_apps_json=excluded.allowed_apps_json,
                    idle_threshold_seconds=excluded.idle_threshold_seconds,
                    switch_warning_count=excluded.switch_warning_count,
                    enabled=excluded.enabled,
                    updated_at=excluded.updated_at
                """,
                record,
            )
        result = self.profile(str(record["id"]))
        assert result is not None
        return result

    def disable_profile(self, profile_id: str, updated_at: str) -> bool:
        with database(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE focus_habit_profiles SET enabled = 0, updated_at = ? WHERE id = ? AND enabled = 1",
                (updated_at, profile_id),
            )
        return cursor.rowcount > 0

    def start_tracking(self, record: dict[str, Any]) -> dict[str, Any]:
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO focus_habit_sessions
                    (session_id,profile_id,profile_name,allowed_apps_json,
                     idle_threshold_seconds,switch_warning_count,status,platform,
                     last_sampled_at,started_at,unavailable_reason)
                VALUES (:session_id,:profile_id,:profile_name,:allowed_apps_json,
                        :idle_threshold_seconds,:switch_warning_count,:status,:platform,
                        :last_sampled_at,:started_at,:unavailable_reason)
                """,
                record,
            )
        result = self.session(str(record["session_id"]))
        assert result is not None
        return result

    def session(self, session_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM focus_habit_sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            usage = connection.execute(
                """
                SELECT process_name,is_allowed,active_seconds,idle_seconds,sample_count,
                       first_seen_at,last_seen_at
                FROM focus_app_usage WHERE session_id = ?
                ORDER BY active_seconds DESC, idle_seconds DESC, process_name
                """,
                (session_id,),
            ).fetchall()
        value = _decode(row)
        if value is not None:
            value["apps"] = [
                {**dict(item), "is_allowed": bool(item["is_allowed"])} for item in usage
            ]
        return value

    def monitoring_ids(self) -> list[str]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT session_id FROM focus_habit_sessions WHERE status = 'monitoring'"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def completed_between(self, start: str, end: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        with database(self.db_path) as connection:
            sessions = connection.execute(
                """
                SELECT * FROM focus_habit_sessions
                WHERE status = 'completed' AND started_at >= ? AND started_at < ?
                ORDER BY started_at
                """,
                (start, end),
            ).fetchall()
            usage = connection.execute(
                """
                SELECT u.process_name, u.is_allowed,
                       SUM(u.active_seconds) AS active_seconds,
                       SUM(u.idle_seconds) AS idle_seconds,
                       SUM(u.sample_count) AS sample_count
                FROM focus_app_usage u
                JOIN focus_habit_sessions h ON h.session_id = u.session_id
                WHERE h.status = 'completed' AND h.started_at >= ? AND h.started_at < ?
                GROUP BY u.process_name, u.is_allowed
                ORDER BY active_seconds DESC, idle_seconds DESC
                """,
                (start, end),
            ).fetchall()
        return [dict(row) for row in sessions], [dict(row) for row in usage]

    def touch(self, session_id: str, sampled_at: str) -> None:
        with database(self.db_path) as connection:
            connection.execute(
                "UPDATE focus_habit_sessions SET last_sampled_at = ? WHERE session_id = ? AND status = 'monitoring'",
                (sampled_at, session_id),
            )

    def add_sample(
        self,
        session_id: str,
        *,
        process_name: str,
        is_allowed: bool,
        active_seconds: int,
        idle_seconds: int,
        distraction_seconds: int,
        switched: bool,
        violation: bool,
        sampled_at: str,
    ) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM focus_habit_sessions WHERE session_id = ? AND status = 'monitoring'",
                (session_id,),
            ).fetchone()
            if not row:
                return None
            active_total = int(row["active_seconds"]) + active_seconds
            idle_total = int(row["idle_seconds"]) + idle_seconds
            distraction_total = int(row["distraction_seconds"]) + distraction_seconds
            usage_active_seconds = active_seconds + distraction_seconds
            denominator = active_total + idle_total + distraction_total
            quality = round(active_total / denominator * 100) if denominator else 100
            connection.execute(
                """
                UPDATE focus_habit_sessions
                SET active_seconds=?, idle_seconds=?, distraction_seconds=?,
                    switch_count=switch_count+?, violation_count=violation_count+?,
                    quality_score=?, last_process_name=?, last_sampled_at=?
                WHERE session_id=?
                """,
                (
                    active_total, idle_total, distraction_total, int(switched),
                    int(violation), quality, process_name, sampled_at, session_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO focus_app_usage
                    (session_id,process_name,is_allowed,active_seconds,idle_seconds,
                     sample_count,first_seen_at,last_seen_at)
                VALUES (?,?,?,?,?,1,?,?)
                ON CONFLICT(session_id,process_name) DO UPDATE SET
                    is_allowed=excluded.is_allowed,
                    active_seconds=focus_app_usage.active_seconds+excluded.active_seconds,
                    idle_seconds=focus_app_usage.idle_seconds+excluded.idle_seconds,
                    sample_count=focus_app_usage.sample_count+1,
                    last_seen_at=excluded.last_seen_at
                """,
                (
                    session_id, process_name, int(is_allowed), usage_active_seconds,
                    idle_seconds, sampled_at, sampled_at,
                ),
            )
        return self.session(session_id)

    def finish(self, session_id: str, *, status: str, ended_at: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            connection.execute(
                """
                UPDATE focus_habit_sessions
                SET status = ?, ended_at = ?, last_sampled_at = ?
                WHERE session_id = ? AND status = 'monitoring'
                """,
                (status, ended_at, ended_at, session_id),
            )
        return self.session(session_id)

    def unavailable(self, session_id: str, *, reason: str, sampled_at: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            connection.execute(
                """
                UPDATE focus_habit_sessions
                SET status = 'unavailable', unavailable_reason = ?, last_sampled_at = ?
                WHERE session_id = ? AND status = 'monitoring'
                """,
                (reason[:240], sampled_at, session_id),
            )
        return self.session(session_id)

    def export_backup(self) -> dict[str, Any]:
        with database(self.db_path) as connection:
            profiles = connection.execute("SELECT * FROM focus_habit_profiles").fetchall()
            sessions = connection.execute(
                "SELECT * FROM focus_habit_sessions WHERE status IN ('completed','cancelled','unavailable')"
            ).fetchall()
            usage = connection.execute(
                """
                SELECT u.* FROM focus_app_usage u
                JOIN focus_habit_sessions h ON h.session_id = u.session_id
                WHERE h.status IN ('completed','cancelled','unavailable')
                """
            ).fetchall()
        return {
            "profiles": [dict(row) for row in profiles],
            "sessions": [dict(row) for row in sessions],
            "app_usage": [dict(row) for row in usage],
        }

    def import_backup(self, payload: Any) -> dict[str, int]:
        if not isinstance(payload, dict):
            return {"habit_profiles_imported": 0, "habit_sessions_imported": 0}
        profile_columns = {
            "id", "name", "allowed_apps_json", "idle_threshold_seconds",
            "switch_warning_count", "enabled", "created_at", "updated_at",
        }
        session_columns = {
            "session_id", "profile_id", "profile_name", "allowed_apps_json",
            "idle_threshold_seconds", "switch_warning_count", "status", "platform",
            "active_seconds", "idle_seconds", "distraction_seconds", "switch_count",
            "violation_count", "quality_score", "last_process_name", "last_sampled_at",
            "started_at", "ended_at", "unavailable_reason",
        }
        usage_columns = {
            "session_id", "process_name", "is_allowed", "active_seconds",
            "idle_seconds", "sample_count", "first_seen_at", "last_seen_at",
        }
        imported_profiles = imported_sessions = 0
        with database(self.db_path) as connection:
            for source in payload.get("profiles") or []:
                if not isinstance(source, dict) or not profile_columns <= set(source):
                    continue
                record = {key: source[key] for key in profile_columns}
                columns = list(record)
                cursor = connection.execute(
                    f"INSERT OR IGNORE INTO focus_habit_profiles ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [record[key] for key in columns],
                )
                imported_profiles += int(cursor.rowcount > 0)
            for source in payload.get("sessions") or []:
                if not isinstance(source, dict) or not session_columns <= set(source):
                    continue
                if source.get("status") not in {"completed", "cancelled", "unavailable"}:
                    continue
                if not connection.execute(
                    "SELECT 1 FROM focus_sessions WHERE id = ?", (source.get("session_id"),)
                ).fetchone():
                    continue
                record = {key: source[key] for key in session_columns}
                if record["profile_id"] and not connection.execute(
                    "SELECT 1 FROM focus_habit_profiles WHERE id = ?", (record["profile_id"],)
                ).fetchone():
                    record["profile_id"] = None
                columns = list(record)
                cursor = connection.execute(
                    f"INSERT OR IGNORE INTO focus_habit_sessions ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [record[key] for key in columns],
                )
                imported_sessions += int(cursor.rowcount > 0)
            for source in payload.get("app_usage") or []:
                if not isinstance(source, dict) or not usage_columns <= set(source):
                    continue
                if not connection.execute(
                    "SELECT 1 FROM focus_habit_sessions WHERE session_id = ?", (source.get("session_id"),)
                ).fetchone():
                    continue
                record = {key: source[key] for key in usage_columns}
                columns = list(record)
                connection.execute(
                    f"INSERT OR IGNORE INTO focus_app_usage ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    [record[key] for key in columns],
                )
        return {
            "habit_profiles_imported": imported_profiles,
            "habit_sessions_imported": imported_sessions,
        }
