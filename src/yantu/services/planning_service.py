from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Mapping

from ..common import utc_now
from ..database.repositories import PlanningRepository, TaskRepository
from .schedule_service import ScheduleService
from .task_service import TaskService


PRIORITY_ORDER = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
BLOCK_TYPES = {"focus", "short_break", "long_break", "buffer"}


class PlanningService:
    def __init__(self, db_path: Path | str) -> None:
        self.repository = PlanningRepository(db_path)
        self.tasks = TaskRepository(db_path)
        self.task_service = TaskService(db_path)
        self.schedule_service = ScheduleService(db_path)

    def get_profile(self) -> dict[str, Any]:
        return self.repository.get_profile()

    def update_profile(self, values: Mapping[str, Any]) -> dict[str, Any]:
        current = self.get_profile()
        allowed = {
            "workday_start", "workday_end", "active_weekdays", "focus_minutes",
            "short_break_minutes", "long_break_minutes", "long_break_after",
            "max_continuous_focus", "buffer_minutes", "use_pomodoro", "timezone",
        }
        candidate = {**current, **{key: values[key] for key in allowed if key in values}}
        normalized = self._validate_profile(candidate)
        normalized["updated_at"] = utc_now()
        return self.repository.update_profile(normalized)

    def preview(self, values: Mapping[str, Any]) -> dict[str, Any]:
        target = self._date(values.get("date") or date.today().isoformat())
        profile = self._validate_profile({**self.get_profile(), **dict(values.get("profile") or {})})
        requested_ids = values.get("task_ids")
        if requested_ids is not None and not isinstance(requested_ids, list):
            raise ValueError("task_ids 必须是数组")
        selected_ids = {str(item) for item in requested_ids} if requested_ids else None
        plan = self.task_service.daily_plan(target.isoformat())
        task_lookup = {str(task["id"]): task for task in self.tasks.list()}
        allocations = [
            {**item, "task": task_lookup[item["task_id"]]}
            for item in plan["allocations"]
            if item["task_id"] in task_lookup
            and (selected_ids is None or item["task_id"] in selected_ids)
            and item["reason"] != "overdue"
        ]
        allocations.sort(
            key=lambda item: (
                PRIORITY_ORDER.get(item["task"].get("priority"), 9),
                item["task"].get("due_date") or "9999-12-31",
                -item["planned_minutes"],
            )
        )
        fixed_events = self.schedule_service.calendar_events(target.isoformat(), target.isoformat())
        warnings: list[str] = []
        if target.isoweekday() not in profile["active_weekdays"]:
            warnings.append("所选日期不是偏好中的工作日，未自动安排任务。")
            windows: list[tuple[datetime, datetime]] = []
        else:
            windows = self._available_windows(target, profile, fixed_events)
        blocks, unscheduled = self._schedule(target, profile, allocations, windows)
        if unscheduled:
            warnings.append(f"当天容量不足，仍有 {unscheduled} 分钟任务尚未安排。")
        if not allocations:
            warnings.append("所选日期没有需要自动安排的任务。")
        capacity = sum(int((end - start).total_seconds() // 60) for start, end in windows)
        snapshot = {
            "date": target.isoformat(),
            "profile": profile,
            "task_allocations": [
                {
                    "task_id": item["task_id"],
                    "title": item["task"]["title"],
                    "priority": item["task"]["priority"],
                    "deadline": item["task"].get("due_date"),
                    "planned_minutes": item["planned_minutes"],
                    "remaining_minutes": item["remaining_minutes"],
                }
                for item in allocations
            ],
            "fixed_events": fixed_events,
            "available_capacity_minutes": capacity,
        }
        return {
            "preview_id": str(uuid.uuid4()),
            "date": target.isoformat(),
            "strategy": "rule",
            "profile": profile,
            "blocks": blocks,
            "fixed_events": fixed_events,
            "warnings": warnings,
            "summary": {
                "task_minutes": sum(item["planned_minutes"] for item in allocations),
                "scheduled_focus_minutes": sum(item["planned_minutes"] for item in blocks if item["block_type"] == "focus"),
                "break_minutes": sum(item["planned_minutes"] for item in blocks if "break" in item["block_type"]),
                "unscheduled_minutes": unscheduled,
                "available_capacity_minutes": capacity,
            },
            "input_snapshot": snapshot,
        }

    def confirm(self, preview: Mapping[str, Any]) -> dict[str, Any]:
        target = self._date(preview.get("date"))
        strategy = str(preview.get("strategy") or "rule")
        if strategy not in {"rule", "ai", "manual"}:
            raise ValueError("无效的规划策略")
        source_blocks = preview.get("blocks")
        if not isinstance(source_blocks, list):
            raise ValueError("规划结果必须包含 blocks 数组")
        run_id = str(preview.get("run_id") or preview.get("preview_id") or uuid.uuid4())
        now = utc_now()
        blocks: list[dict[str, Any]] = []
        previous_end: str | None = None
        for sequence, source in enumerate(source_blocks):
            if not isinstance(source, Mapping):
                raise ValueError("时间块必须是对象")
            block_type = str(source.get("block_type") or "")
            if block_type not in BLOCK_TYPES:
                raise ValueError("无效的时间块类型")
            start_time = self._clock(source.get("start_time"), "start_time")
            end_time = self._clock(source.get("end_time"), "end_time")
            if end_time <= start_time or (previous_end and start_time < previous_end):
                raise ValueError("时间块不能重叠且结束时间必须晚于开始时间")
            previous_end = end_time
            minutes = int((datetime.combine(target, time.fromisoformat(end_time)) - datetime.combine(target, time.fromisoformat(start_time))).total_seconds() // 60)
            task_id = str(source.get("task_id") or "") or None
            if block_type == "focus" and (not task_id or not self.tasks.get(task_id)):
                raise ValueError("专注时间块必须关联有效任务")
            blocks.append(
                {
                    "id": str(uuid.uuid4()), "run_id": run_id, "task_id": task_id,
                    "block_date": target.isoformat(), "start_time": start_time,
                    "end_time": end_time, "block_type": block_type,
                    "planned_minutes": minutes, "source": strategy, "status": "planned",
                    "locked": int(bool(source.get("locked", False))),
                    "rationale": str(source.get("rationale") or "").strip(),
                    "sequence": sequence, "created_at": now, "updated_at": now,
                }
            )
        existing = self.repository.get_run(run_id)
        if existing:
            return existing
        warnings = preview.get("warnings") or []
        if not isinstance(warnings, list):
            raise ValueError("warnings 必须是数组")
        run = {
            "id": run_id, "start_date": target.isoformat(), "end_date": target.isoformat(),
            "status": "confirmed", "strategy": strategy,
            "input_snapshot": dict(preview.get("input_snapshot") or {}),
            "warnings": [str(item) for item in warnings], "created_at": now,
            "confirmed_at": now,
        }
        return self.repository.create_run(run, blocks)

    def list_for_date(self, value: Any) -> list[dict[str, Any]]:
        return self.repository.list_for_date(self._date(value).isoformat())

    def export_backup(self) -> dict[str, Any]:
        return {"profile": self.get_profile(), "runs": self.repository.list_runs()}

    def import_backup(self, payload: Any) -> dict[str, int]:
        if not isinstance(payload, Mapping):
            raise ValueError("planning 备份必须是对象")
        profile = payload.get("profile")
        if isinstance(profile, Mapping):
            self.update_profile(profile)
        imported = 0
        for source in payload.get("runs") or []:
            if not isinstance(source, Mapping) or self.repository.get_run(str(source.get("id") or "")):
                continue
            self.confirm({
                "run_id": source.get("id"), "date": source.get("start_date"),
                "strategy": source.get("strategy", "rule"),
                "blocks": source.get("blocks") or [],
                "warnings": source.get("warnings") or [],
                "input_snapshot": source.get("input_snapshot") or {},
            })
            imported += 1
        return {"planning_runs_imported": imported}

    def _schedule(
        self,
        target: date,
        profile: dict[str, Any],
        allocations: list[dict[str, Any]],
        windows: list[tuple[datetime, datetime]],
    ) -> tuple[list[dict[str, Any]], int]:
        blocks: list[dict[str, Any]] = []
        window_index = 0
        cursor = windows[0][0] if windows else None
        focus_count = 0
        continuous = 0
        total_remaining = sum(item["planned_minutes"] for item in allocations)

        def advance_window() -> bool:
            nonlocal window_index, cursor, focus_count, continuous
            window_index += 1
            if window_index >= len(windows):
                cursor = None
                return False
            cursor = windows[window_index][0]
            focus_count = 0
            continuous = 0
            return True

        for allocation in allocations:
            remaining = int(allocation["planned_minutes"])
            task = allocation["task"]
            while remaining > 0 and cursor is not None:
                window_end = windows[window_index][1]
                available = int((window_end - cursor).total_seconds() // 60)
                if available < 10:
                    if not advance_window():
                        break
                    continue
                focus_length = min(int(profile["focus_minutes"]), remaining, available)
                if focus_length < 10 and remaining >= 10:
                    if not advance_window():
                        break
                    continue
                end = cursor + timedelta(minutes=focus_length)
                blocks.append(self._preview_block(target, cursor, end, "focus", task["id"], f"{task['priority']} 优先级 · 截止 {task.get('due_date') or '未设置'}"))
                cursor = end
                remaining -= focus_length
                total_remaining -= focus_length
                focus_count += 1
                continuous += focus_length
                if total_remaining <= 0:
                    continue
                long_break = focus_count >= int(profile["long_break_after"]) or continuous >= int(profile["max_continuous_focus"])
                break_type = "long_break" if long_break else "short_break"
                break_length = int(profile["long_break_minutes"] if long_break else profile["short_break_minutes"])
                if not profile["use_pomodoro"]:
                    break_length = int(profile["long_break_minutes"] if long_break else profile["buffer_minutes"])
                    break_type = "long_break" if long_break else "buffer"
                if break_length and cursor + timedelta(minutes=break_length) <= window_end:
                    break_end = cursor + timedelta(minutes=break_length)
                    blocks.append(self._preview_block(target, cursor, break_end, break_type, None, "连续工作后的恢复时间"))
                    cursor = break_end
                    if long_break:
                        focus_count = 0
                        continuous = 0
                elif cursor >= window_end:
                    advance_window()
                else:
                    # Do not squeeze another focus block into a fragment that
                    # cannot hold the required recovery period.
                    advance_window()
        return blocks, max(0, total_remaining)

    @staticmethod
    def _preview_block(target: date, start: datetime, end: datetime, block_type: str, task_id: Any, rationale: str) -> dict[str, Any]:
        return {
            "task_id": str(task_id) if task_id else None,
            "block_date": target.isoformat(), "start_time": start.strftime("%H:%M"),
            "end_time": end.strftime("%H:%M"), "block_type": block_type,
            "planned_minutes": int((end - start).total_seconds() // 60),
            "locked": False, "rationale": rationale,
        }

    def _available_windows(self, target: date, profile: dict[str, Any], events: list[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
        start = datetime.combine(target, time.fromisoformat(profile["workday_start"]))
        end = datetime.combine(target, time.fromisoformat(profile["workday_end"]))
        buffer = timedelta(minutes=int(profile["buffer_minutes"]))
        busy = sorted(
            (
                max(start, datetime.combine(target, time.fromisoformat(item["start_time"])) - buffer),
                min(end, datetime.combine(target, time.fromisoformat(item["end_time"])) + buffer),
            )
            for item in events
        )
        windows = [(start, end)]
        for busy_start, busy_end in busy:
            updated: list[tuple[datetime, datetime]] = []
            for window_start, window_end in windows:
                if busy_end <= window_start or busy_start >= window_end:
                    updated.append((window_start, window_end))
                else:
                    if busy_start > window_start:
                        updated.append((window_start, busy_start))
                    if busy_end < window_end:
                        updated.append((busy_end, window_end))
            windows = updated
        return [(left, right) for left, right in windows if (right - left).total_seconds() >= 600]

    def _validate_profile(self, values: Mapping[str, Any]) -> dict[str, Any]:
        start = self._clock(values.get("workday_start"), "workday_start")
        end = self._clock(values.get("workday_end"), "workday_end")
        if end <= start:
            raise ValueError("工作结束时间必须晚于开始时间")
        weekdays = sorted({int(item) for item in values.get("active_weekdays", [])})
        if not weekdays or any(item < 1 or item > 7 for item in weekdays):
            raise ValueError("active_weekdays 必须包含 1 到 7")
        ranges = {
            "focus_minutes": (10, 120), "short_break_minutes": (1, 30),
            "long_break_minutes": (5, 60), "long_break_after": (2, 8),
            "max_continuous_focus": (25, 240), "buffer_minutes": (0, 60),
        }
        result: dict[str, Any] = {
            "workday_start": start, "workday_end": end, "active_weekdays": weekdays,
            "use_pomodoro": bool(values.get("use_pomodoro", True)),
            "timezone": str(values.get("timezone") or "Asia/Shanghai"),
        }
        for field, (minimum, maximum) in ranges.items():
            try:
                number = int(values.get(field))
            except (TypeError, ValueError) as error:
                raise ValueError(f"{field} 必须是整数") from error
            if not minimum <= number <= maximum:
                raise ValueError(f"{field} 必须在 {minimum} 到 {maximum} 之间")
            result[field] = number
        return result

    @staticmethod
    def _date(value: Any) -> date:
        try:
            return date.fromisoformat(str(value))
        except ValueError as error:
            raise ValueError("日期必须使用 YYYY-MM-DD") from error

    @staticmethod
    def _clock(value: Any, field: str) -> str:
        try:
            return time.fromisoformat(str(value)).strftime("%H:%M")
        except ValueError as error:
            raise ValueError(f"{field} 必须使用 HH:MM") from error
