from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..repository import database, init_db


class ArchiveRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def upsert_period(self, record: dict[str, Any]) -> dict[str, Any]:
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO archive_periods
                    (id, period_type, period_key, start_date, end_date, relative_path,
                     manifest_version, status, entry_count, created_at, updated_at, sealed_at)
                VALUES
                    (:id, :period_type, :period_key, :start_date, :end_date, :relative_path,
                     :manifest_version, :status, :entry_count, :created_at, :updated_at, :sealed_at)
                ON CONFLICT(period_type, period_key) DO UPDATE SET
                    start_date=excluded.start_date, end_date=excluded.end_date,
                    relative_path=excluded.relative_path, updated_at=excluded.updated_at
                """,
                record,
            )
            row = connection.execute(
                "SELECT * FROM archive_periods WHERE period_type=? AND period_key=?",
                (record["period_type"], record["period_key"]),
            ).fetchone()
        assert row is not None
        return dict(row)

    def list_periods(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM archive_periods ORDER BY start_date DESC, period_type"
            ).fetchall()
        return [dict(row) for row in rows]

    def add_entry(self, record: dict[str, Any]) -> bool:
        values = dict(record)
        if not isinstance(values.get("payload_json"), str):
            values["payload_json"] = json.dumps(
                values.get("payload_json") or {}, ensure_ascii=False, sort_keys=True
            )
        with database(self.db_path) as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO archive_entries
                    (id, period_id, entity_type, entity_id, occurred_at,
                     payload_json, checksum, archived_at)
                VALUES
                    (:id, :period_id, :entity_type, :entity_id, :occurred_at,
                     :payload_json, :checksum, :archived_at)
                """,
                values,
            )
            if cursor.rowcount:
                connection.execute(
                    """UPDATE archive_periods
                    SET entry_count=entry_count+1, updated_at=? WHERE id=?""",
                    (record["archived_at"], record["period_id"]),
                )
            return cursor.rowcount > 0
