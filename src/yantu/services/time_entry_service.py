from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from ..common import utc_now
from ..database.models import TimeEntry
from ..database.repositories import TaskRepository, TimeEntryRepository


class TimeEntryService:
    def __init__(self, db_path: Path | str) -> None:
        self.repository = TimeEntryRepository(db_path)
        self.tasks = TaskRepository(db_path)

    def list(self, *, task_id: str | None = None) -> list[TimeEntry]:
        return [TimeEntry.from_record(record) for record in self.repository.list(task_id=task_id)]

    def get(self, entry_id: str) -> TimeEntry | None:
        record = self.repository.get(entry_id)
        return TimeEntry.from_record(record) if record else None

    def create(self, values: Mapping[str, Any]) -> TimeEntry:
        task_id = str(values.get("task_id") or "")
        if not task_id or not self.tasks.get(task_id):
            raise ValueError("任务不存在")
        start_time = self._timestamp(values.get("start_time"), "start_time", required=True)
        end_time = self._timestamp(values.get("end_time"), "end_time", required=False)
        duration = self._duration(values.get("duration", 0))
        self._validate_time_range(start_time, end_time)
        record = self.repository.create(
            {
                "id": str(uuid.uuid4()),
                "task_id": task_id,
                "start_time": start_time,
                "end_time": end_time,
                "duration": duration,
                "note": str(values.get("note") or "").strip(),
                "created_at": utc_now(),
            }
        )
        self._adjust_task_actual(task_id, duration)
        return TimeEntry.from_record(record)

    def update(self, entry_id: str, values: Mapping[str, Any]) -> TimeEntry | None:
        existing = self.repository.get(entry_id)
        if not existing:
            return None
        changes: dict[str, Any] = {}
        if "start_time" in values:
            changes["start_time"] = self._timestamp(
                values["start_time"], "start_time", required=True
            )
        if "end_time" in values:
            changes["end_time"] = self._timestamp(
                values["end_time"], "end_time", required=False
            )
        if "duration" in values:
            changes["duration"] = self._duration(values["duration"])
        if "note" in values:
            changes["note"] = str(values["note"] or "").strip()
        start_time = changes.get("start_time", existing["start_time"])
        end_time = changes.get("end_time", existing["end_time"])
        self._validate_time_range(start_time, end_time)
        record = self.repository.update(entry_id, changes)
        if record and "duration" in changes:
            self._adjust_task_actual(str(existing["task_id"]), int(record["duration"]) - int(existing["duration"]))
        return TimeEntry.from_record(record) if record else None

    def delete(self, entry_id: str) -> bool:
        existing = self.repository.get(entry_id)
        if not existing or not self.repository.delete(entry_id):
            return False
        self._adjust_task_actual(str(existing["task_id"]), -int(existing["duration"] or 0))
        return True

    def _adjust_task_actual(self, task_id: str, delta: int) -> None:
        task = self.tasks.get(task_id)
        if not task:
            return
        actual = max(0, int(task.get("actual_minutes") or 0) + delta)
        self.tasks.update(task_id, {"actual_minutes": actual, "updated_at": utc_now()})

    @staticmethod
    def _timestamp(value: Any, field: str, *, required: bool) -> str | None:
        if value in (None, ""):
            if required:
                raise ValueError(f"{field} 不能为空")
            return None
        try:
            return datetime.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValueError(f"{field} 必须是 ISO 8601 时间") from exc

    @staticmethod
    def _duration(value: Any) -> int:
        try:
            duration = int(value or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError("duration 必须是非负整数分钟") from exc
        if duration < 0:
            raise ValueError("duration 必须是非负整数分钟")
        return duration

    @staticmethod
    def _validate_time_range(start_time: str, end_time: str | None) -> None:
        if not end_time:
            return
        start = datetime.fromisoformat(start_time)
        end = datetime.fromisoformat(end_time)
        try:
            invalid = end < start
        except TypeError as exc:
            raise ValueError("start_time 与 end_time 必须使用一致的时区格式") from exc
        if invalid:
            raise ValueError("end_time 不能早于 start_time")
