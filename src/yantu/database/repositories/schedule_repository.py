from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..repository import database, init_db


def _decode(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    record = dict(row)
    for source, target in (
        ("periods_json", "periods"),
        ("custom_weeks_json", "custom_weeks"),
    ):
        if source in record:
            try:
                record[target] = json.loads(record.pop(source) or "[]")
            except json.JSONDecodeError:
                record[target] = []
    return record


class ScheduleRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def list_semesters(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM semesters ORDER BY start_date DESC"
            ).fetchall()
            return [_decode(row) for row in rows]  # type: ignore[misc]

    def get_semester(self, semester_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            return _decode(
                connection.execute(
                    "SELECT * FROM semesters WHERE id = ?", (semester_id,)
                ).fetchone()
            )

    def upsert_semester(self, record: dict[str, Any]) -> dict[str, Any]:
        values = dict(record)
        values["periods_json"] = json.dumps(values.pop("periods"), ensure_ascii=False)
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO semesters
                    (id, name, start_date, end_date, timezone, periods_json, created_at, updated_at)
                VALUES
                    (:id, :name, :start_date, :end_date, :timezone, :periods_json, :created_at, :updated_at)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, start_date=excluded.start_date,
                    end_date=excluded.end_date, timezone=excluded.timezone,
                    periods_json=excluded.periods_json, updated_at=excluded.updated_at
                """,
                values,
            )
        result = self.get_semester(str(record["id"]))
        assert result is not None
        return result

    def list_courses(
        self, semester_id: str | None = None, *, deleted: bool = False
    ) -> list[dict[str, Any]]:
        clauses = ["c.deleted_at IS NOT NULL" if deleted else "c.deleted_at IS NULL"]
        params: list[str] = []
        if semester_id:
            clauses.append("c.semester_id = ?")
            params.append(semester_id)
        with database(self.db_path) as connection:
            rows = connection.execute(
                f"SELECT c.* FROM courses c WHERE {' AND '.join(clauses)} ORDER BY c.name",
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def get_course(self, course_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        suffix = "" if include_deleted else " AND deleted_at IS NULL"
        with database(self.db_path) as connection:
            row = connection.execute(
                f"SELECT * FROM courses WHERE id = ?{suffix}", (course_id,)
            ).fetchone()
            if not row:
                return None
            course = dict(row)
            meetings = connection.execute(
                "SELECT * FROM course_meetings WHERE course_id = ? ORDER BY weekday, start_time",
                (course_id,),
            ).fetchall()
            course["meetings"] = []
            for item in meetings:
                meeting = _decode(item)
                assert meeting is not None
                meeting["exceptions"] = [
                    dict(entry)
                    for entry in connection.execute(
                        "SELECT occurrence_date, kind FROM course_exceptions WHERE meeting_id = ?",
                        (meeting["id"],),
                    ).fetchall()
                ]
                course["meetings"].append(meeting)
            return course

    def create_course(self, course: dict[str, Any], meetings: list[dict[str, Any]]) -> dict[str, Any]:
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO courses
                    (id, semester_id, import_id, name, teacher, location, color, notes,
                     created_at, updated_at, deleted_at)
                VALUES
                    (:id, :semester_id, :import_id, :name, :teacher, :location, :color,
                     :notes, :created_at, :updated_at, :deleted_at)
                """,
                course,
            )
            for meeting in meetings:
                values = dict(meeting)
                values["custom_weeks_json"] = json.dumps(
                    values.pop("custom_weeks", []), ensure_ascii=False
                )
                connection.execute(
                    """
                    INSERT INTO course_meetings
                        (id, course_id, weekday, start_period, end_period, start_time,
                         end_time, start_week, end_week, week_pattern, custom_weeks_json)
                    VALUES
                        (:id, :course_id, :weekday, :start_period, :end_period, :start_time,
                         :end_time, :start_week, :end_week, :week_pattern, :custom_weeks_json)
                    """,
                    values,
                )
        result = self.get_course(str(course["id"]))
        assert result is not None
        return result

    def update_course(self, course_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        if not changes:
            return self.get_course(course_id)
        assignments = ", ".join(f"{field} = ?" for field in changes)
        with database(self.db_path) as connection:
            cursor = connection.execute(
                f"UPDATE courses SET {assignments} WHERE id = ? AND deleted_at IS NULL",
                [*changes.values(), course_id],
            )
            if cursor.rowcount == 0:
                return None
        return self.get_course(course_id)

    def replace_meetings(self, course_id: str, meetings: list[dict[str, Any]]) -> None:
        with database(self.db_path) as connection:
            connection.execute("DELETE FROM course_meetings WHERE course_id = ?", (course_id,))
            for meeting in meetings:
                values = dict(meeting)
                values["custom_weeks_json"] = json.dumps(values.pop("custom_weeks", []))
                connection.execute(
                    """INSERT INTO course_meetings VALUES
                    (:id,:course_id,:weekday,:start_period,:end_period,:start_time,
                     :end_time,:start_week,:end_week,:week_pattern,:custom_weeks_json)""",
                    values,
                )

    def meetings_between(self, semester_id: str | None = None) -> list[dict[str, Any]]:
        clause = " AND c.semester_id = ?" if semester_id else ""
        params = [semester_id] if semester_id else []
        with database(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT m.*, c.name, c.teacher, c.location, c.color, c.semester_id,
                       s.start_date AS semester_start, s.end_date AS semester_end
                FROM course_meetings m
                JOIN courses c ON c.id = m.course_id
                JOIN semesters s ON s.id = c.semester_id
                WHERE c.deleted_at IS NULL{clause}
                """,
                params,
            ).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                item = _decode(row)
                assert item is not None
                skipped = connection.execute(
                    "SELECT occurrence_date FROM course_exceptions WHERE meeting_id = ? AND kind = 'skip'",
                    (item["id"],),
                ).fetchall()
                item["skipped_dates"] = [str(entry[0]) for entry in skipped]
                result.append(item)
            return result

    def add_skip(self, meeting_id: str, exception_id: str, date: str, created_at: str) -> bool:
        with database(self.db_path) as connection:
            exists = connection.execute(
                "SELECT 1 FROM course_meetings WHERE id = ?", (meeting_id,)
            ).fetchone()
            if not exists:
                return False
            connection.execute(
                "INSERT OR IGNORE INTO course_exceptions VALUES (?, ?, ?, 'skip', ?)",
                (exception_id, meeting_id, date, created_at),
            )
            return True

    def set_deleted(self, course_id: str, deleted_at: str | None) -> bool:
        with database(self.db_path) as connection:
            cursor = connection.execute(
                "UPDATE courses SET deleted_at = ?, updated_at = COALESCE(?, updated_at) WHERE id = ?",
                (deleted_at, deleted_at, course_id),
            )
            return cursor.rowcount > 0

    def delete_permanently(self, course_id: str) -> bool:
        with database(self.db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM courses WHERE id = ? AND deleted_at IS NOT NULL", (course_id,)
            )
            return cursor.rowcount > 0

    def source_exists(self, source_type: str, source_hash: str) -> bool:
        with database(self.db_path) as connection:
            return connection.execute(
                "SELECT 1 FROM schedule_imports WHERE source_type = ? AND source_hash = ?",
                (source_type, source_hash),
            ).fetchone() is not None

    def create_import(
        self,
        import_record: dict[str, Any],
        semester: dict[str, Any],
        courses: list[tuple[dict[str, Any], list[dict[str, Any]]]],
    ) -> list[str]:
        """Persist an approved preview atomically."""
        with database(self.db_path) as connection:
            semester_values = dict(semester)
            semester_values["periods_json"] = json.dumps(
                semester_values.pop("periods"), ensure_ascii=False
            )
            connection.execute(
                """INSERT INTO semesters VALUES
                (:id,:name,:start_date,:end_date,:timezone,:periods_json,:created_at,:updated_at)
                ON CONFLICT(id) DO UPDATE SET name=excluded.name,start_date=excluded.start_date,
                end_date=excluded.end_date,timezone=excluded.timezone,
                periods_json=excluded.periods_json,updated_at=excluded.updated_at""",
                semester_values,
            )
            connection.execute(
                "INSERT INTO schedule_imports VALUES (:id,:source_type,:source_hash,:imported_at)",
                import_record,
            )
            created: list[str] = []
            for course, meetings in courses:
                connection.execute(
                    """INSERT INTO courses VALUES
                    (:id,:semester_id,:import_id,:name,:teacher,:location,:color,:notes,
                     :created_at,:updated_at,:deleted_at)""",
                    course,
                )
                created.append(str(course["id"]))
                for meeting in meetings:
                    values = dict(meeting)
                    values["custom_weeks_json"] = json.dumps(
                        values.pop("custom_weeks", []), ensure_ascii=False
                    )
                    connection.execute(
                        """INSERT INTO course_meetings VALUES
                        (:id,:course_id,:weekday,:start_period,:end_period,:start_time,
                         :end_time,:start_week,:end_week,:week_pattern,:custom_weeks_json)""",
                        values,
                    )
            return created
