from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..repository import database, init_db


class SettingsRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def get(self, key: str, default: Any = None) -> Any:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT value_json FROM app_settings WHERE key = ?", (key,)
            ).fetchone()
        if not row:
            return default
        try:
            return json.loads(row[0])
        except json.JSONDecodeError:
            return default

    def set(self, key: str, value: Any, updated_at: str) -> None:
        encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO app_settings (key, value_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (key, encoded, updated_at),
            )

    def list_safe(self) -> dict[str, Any]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT key, value_json FROM app_settings ORDER BY key"
            ).fetchall()
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[str(row["key"])] = json.loads(row["value_json"])
            except json.JSONDecodeError:
                continue
        return result
