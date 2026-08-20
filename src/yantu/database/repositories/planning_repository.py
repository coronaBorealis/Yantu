from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..repository import database, init_db


def _decode_profile(record: dict[str, Any]) -> dict[str, Any]:
    record["active_weekdays"] = json.loads(record.pop("active_weekdays_json") or "[]")
    record["use_pomodoro"] = bool(record["use_pomodoro"])
    return record


def _decode_run(record: dict[str, Any]) -> dict[str, Any]:
    record["input_snapshot"] = json.loads(record.pop("input_snapshot_json") or "{}")
    record["warnings"] = json.loads(record.pop("warnings_json") or "[]")
    return record


class PlanningRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def get_profile(self) -> dict[str, Any]:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM planning_profiles WHERE id = 'default'"
            ).fetchone()
        assert row is not None
        return _decode_profile(dict(row))

    def update_profile(self, changes: dict[str, Any]) -> dict[str, Any]:
        values = dict(changes)
        if "active_weekdays" in values:
            values["active_weekdays_json"] = json.dumps(values.pop("active_weekdays"))
        if "use_pomodoro" in values:
            values["use_pomodoro"] = int(bool(values["use_pomodoro"]))
        if values:
            with database(self.db_path) as connection:
                connection.execute(
                    f"UPDATE planning_profiles SET {', '.join(f'{key} = ?' for key in values)} WHERE id = 'default'",
                    list(values.values()),
                )
        return self.get_profile()

    def create_run(
        self,
        run: dict[str, Any],
        blocks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        run_values = dict(run)
        run_values["input_snapshot_json"] = json.dumps(
            run_values.pop("input_snapshot"), ensure_ascii=False
        )
        run_values["warnings_json"] = json.dumps(
            run_values.pop("warnings"), ensure_ascii=False
        )
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO planning_runs
                    (id,start_date,end_date,status,strategy,input_snapshot_json,
                     warnings_json,created_at,confirmed_at)
                VALUES
                    (:id,:start_date,:end_date,:status,:strategy,:input_snapshot_json,
                     :warnings_json,:created_at,:confirmed_at)
                """,
                run_values,
            )
            for block in blocks:
                connection.execute(
                    """
                    INSERT INTO plan_blocks
                        (id,run_id,task_id,block_date,start_time,end_time,block_type,
                         planned_minutes,source,status,locked,rationale,sequence,
                         created_at,updated_at)
                    VALUES
                        (:id,:run_id,:task_id,:block_date,:start_time,:end_time,:block_type,
                         :planned_minutes,:source,:status,:locked,:rationale,:sequence,
                         :created_at,:updated_at)
                    """,
                    block,
                )
        result = self.get_run(str(run["id"]))
        assert result is not None
        return result

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM planning_runs WHERE id = ?", (run_id,)
            ).fetchone()
            if not row:
                return None
            result = _decode_run(dict(row))
            result["blocks"] = [
                dict(item)
                for item in connection.execute(
                    "SELECT * FROM plan_blocks WHERE run_id = ? ORDER BY sequence",
                    (run_id,),
                ).fetchall()
            ]
            return result

    def list_for_date(self, block_date: str) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT b.*, t.title AS task_title
                FROM plan_blocks b
                JOIN planning_runs r ON r.id = b.run_id
                LEFT JOIN tasks t ON t.id = b.task_id
                WHERE b.block_date = ? AND r.status = 'confirmed'
                ORDER BY r.confirmed_at DESC, b.sequence
                """,
                (block_date,),
            ).fetchall()
        if not rows:
            return []
        newest_run = rows[0]["run_id"]
        return [dict(row) for row in rows if row["run_id"] == newest_run]

    def list_runs(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            ids = [
                str(row[0])
                for row in connection.execute(
                    "SELECT id FROM planning_runs ORDER BY created_at"
                ).fetchall()
            ]
        return [run for run_id in ids if (run := self.get_run(run_id)) is not None]
