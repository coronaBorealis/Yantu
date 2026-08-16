from __future__ import annotations

from pathlib import Path
from typing import Any

from ..repository import database, init_db


def _with_time_aliases(values: dict[str, Any]) -> dict[str, Any]:
    record = dict(values)
    if "start_time" in record:
        record["started_at"] = record["start_time"]
    elif "started_at" in record:
        record["start_time"] = record["started_at"]
    if "end_time" in record:
        record["ended_at"] = record["end_time"]
    elif "ended_at" in record:
        record["end_time"] = record["ended_at"]
    if "duration" in record:
        record["minutes"] = int(record["duration"] or 0)
    elif "minutes" in record:
        record["duration"] = int(record["minutes"] or 0)
    return record


class TimeEntryRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def list(self, *, task_id: str | None = None) -> list[dict[str, Any]]:
        where = "WHERE task_id = ?" if task_id else ""
        parameters = (task_id,) if task_id else ()
        with database(self.db_path) as connection:
            rows = connection.execute(
                f"SELECT * FROM time_entries {where} ORDER BY start_time DESC",
                parameters,
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, entry_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM time_entries WHERE id = ?", (entry_id,)
            ).fetchone()
        return dict(row) if row else None

    def create(self, entry: dict[str, Any]) -> dict[str, Any]:
        record = _with_time_aliases(entry)
        columns = list(record)
        with database(self.db_path) as connection:
            connection.execute(
                f"INSERT INTO time_entries ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [record[column] for column in columns],
            )
        result = self.get(str(record["id"]))
        assert result is not None
        return result

    def update(self, entry_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        if not changes:
            return self.get(entry_id)
        record = _with_time_aliases(changes)
        columns = list(record)
        with database(self.db_path) as connection:
            cursor = connection.execute(
                f"UPDATE time_entries SET {', '.join(f'{column} = ?' for column in columns)} WHERE id = ?",
                [*[record[column] for column in columns], entry_id],
            )
            if cursor.rowcount == 0:
                return None
        return self.get(entry_id)

    def delete(self, entry_id: str) -> bool:
        with database(self.db_path) as connection:
            cursor = connection.execute(
                "DELETE FROM time_entries WHERE id = ?", (entry_id,)
            )
            return cursor.rowcount > 0
