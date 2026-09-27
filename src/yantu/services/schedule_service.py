from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping

from ..common import utc_now
from ..database.repositories.schedule_repository import ScheduleRepository
from ..database.repositories.task_repository import TaskRepository


DEFAULT_PERIODS = [
    {"period": 1, "start_time": "08:00", "end_time": "08:45"},
    {"period": 2, "start_time": "08:50", "end_time": "09:35"},
    {"period": 3, "start_time": "09:50", "end_time": "10:35"},
    {"period": 4, "start_time": "10:40", "end_time": "11:25"},
    {"period": 5, "start_time": "11:30", "end_time": "12:15"},
    {"period": 6, "start_time": "14:00", "end_time": "14:45"},
    {"period": 7, "start_time": "14:50", "end_time": "15:35"},
    {"period": 8, "start_time": "15:50", "end_time": "16:35"},
    {"period": 9, "start_time": "16:40", "end_time": "17:25"},
    {"period": 10, "start_time": "17:30", "end_time": "18:15"},
    {"period": 11, "start_time": "19:00", "end_time": "19:45"},
    {"period": 12, "start_time": "19:50", "end_time": "20:35"},
    {"period": 13, "start_time": "20:40", "end_time": "21:25"},
]


class ScheduleService:
    def __init__(self, db_path: Path | str) -> None:
        self.repository = ScheduleRepository(db_path)
        self.tasks = TaskRepository(db_path)

    def list_semesters(self) -> list[dict[str, Any]]:
        return self.repository.list_semesters()

    def get_semester(self, semester_id: str) -> dict[str, Any] | None:
        return self.repository.get_semester(semester_id)

    def list_courses(self, semester_id: str | None = None, *, deleted: bool = False) -> list[dict[str, Any]]:
        return self.repository.list_courses(semester_id, deleted=deleted)

    def get_course(self, course_id: str, *, include_deleted: bool = False) -> dict[str, Any] | None:
        return self.repository.get_course(course_id, include_deleted=include_deleted)

    def delete_course_permanently(self, course_id: str) -> bool:
        return self.repository.delete_permanently(course_id)

    @staticmethod
    def _date(value: Any, field: str) -> str:
        try:
            return date.fromisoformat(str(value)).isoformat()
        except ValueError as exc:
            raise ValueError(f"{field} 必须使用 YYYY-MM-DD") from exc

    @staticmethod
    def _time(value: Any, field: str) -> str:
        try:
            return datetime.strptime(str(value), "%H:%M").strftime("%H:%M")
        except ValueError as exc:
            raise ValueError(f"{field} 必须使用 HH:MM") from exc

    def normalize_semester(self, values: Mapping[str, Any], *, semester_id: str | None = None) -> dict[str, Any]:
        name = str(values.get("name") or "").strip()
        if not name:
            raise ValueError("学期名称不能为空")
        start = self._date(values.get("start_date"), "学期开始日期")
        end = self._date(values.get("end_date"), "学期结束日期")
        if date.fromisoformat(start).isoweekday() != 1:
            raise ValueError("教学第 1 周第一天必须是星期一")
        if end < start:
            raise ValueError("学期结束日期不能早于开始日期")
        periods = values.get("periods") or DEFAULT_PERIODS
        if not isinstance(periods, list) or not periods:
            raise ValueError("至少需要一个节次时间")
        normalized_periods = []
        seen: set[int] = set()
        for item in periods:
            try:
                period = int(item["period"])
            except (TypeError, ValueError, KeyError) as exc:
                raise ValueError("节次编号必须是正整数") from exc
            if period < 1 or period in seen:
                raise ValueError("节次编号必须是唯一的正整数")
            seen.add(period)
            start_time = self._time(item.get("start_time"), "上课时间")
            end_time = self._time(item.get("end_time"), "下课时间")
            if end_time <= start_time:
                raise ValueError("下课时间必须晚于上课时间")
            normalized_periods.append(
                {"period": period, "start_time": start_time, "end_time": end_time}
            )
        now = utc_now()
        return {
            "id": semester_id or str(values.get("id") or uuid.uuid4()),
            "name": name,
            "stage_label": str(values.get("stage_label") or "").strip()[:24],
            "start_date": start,
            "end_date": end,
            "timezone": str(values.get("timezone") or "Asia/Shanghai"),
            "periods": sorted(normalized_periods, key=lambda item: item["period"]),
            "created_at": str(values.get("created_at") or now),
            "updated_at": now,
        }

    def save_semester(self, values: Mapping[str, Any], semester_id: str | None = None) -> dict[str, Any]:
        return self.repository.upsert_semester(self.normalize_semester(values, semester_id=semester_id))

    def normalize_meeting(
        self, values: Mapping[str, Any], *, course_id: str, meeting_id: str | None = None
    ) -> dict[str, Any]:
        try:
            weekday = int(values.get("weekday"))
            start_period = int(values.get("start_period"))
            end_period = int(values.get("end_period", start_period))
            start_week = int(values.get("start_week", 1))
            end_week = int(values.get("end_week", start_week))
        except (TypeError, ValueError) as exc:
            raise ValueError("星期、节次和周次必须是整数") from exc
        if not 1 <= weekday <= 7:
            raise ValueError("weekday 必须在 1 到 7 之间")
        if start_period < 1 or end_period < start_period:
            raise ValueError("课程节次范围无效")
        if start_week < 1 or end_week < start_week:
            raise ValueError("课程周次范围无效")
        start_time = self._time(values.get("start_time"), "上课时间")
        end_time = self._time(values.get("end_time"), "下课时间")
        if end_time <= start_time:
            raise ValueError("下课时间必须晚于上课时间")
        pattern = str(values.get("week_pattern") or "all")
        if pattern not in {"all", "odd", "even", "custom"}:
            raise ValueError("无效的周次规则")
        custom_weeks = sorted({int(item) for item in values.get("custom_weeks", [])})
        if pattern == "custom" and not custom_weeks:
            raise ValueError("指定周规则必须包含周次")
        if any(item < start_week or item > end_week for item in custom_weeks):
            raise ValueError("指定周次必须位于课程周次范围内")
        return {
            "id": meeting_id or str(values.get("id") or uuid.uuid4()),
            "course_id": course_id,
            "weekday": weekday,
            "start_period": start_period,
            "end_period": end_period,
            "start_time": start_time,
            "end_time": end_time,
            "start_week": start_week,
            "end_week": end_week,
            "week_pattern": pattern,
            "custom_weeks": custom_weeks,
            "teacher_override": str(values.get("teacher_override") or "").strip(),
            "location_override": str(values.get("location_override") or "").strip(),
        }

    def create_course(
        self, values: Mapping[str, Any], *, import_id: str | None = None
    ) -> dict[str, Any]:
        semester_id = str(values.get("semester_id") or "")
        if not self.repository.get_semester(semester_id):
            raise ValueError("学期不存在")
        name = str(values.get("name") or "").strip()
        if not name:
            raise ValueError("课程名称不能为空")
        course_id = str(values.get("id") or uuid.uuid4())
        meetings_source = values.get("meetings")
        if not isinstance(meetings_source, list) or not meetings_source:
            raise ValueError("课程至少需要一个上课时段")
        meetings = [
            self.normalize_meeting(item, course_id=course_id) for item in meetings_source
        ]
        now = utc_now()
        course = {
            "id": course_id,
            "semester_id": semester_id,
            "import_id": import_id,
            "name": name,
            "teacher": str(values.get("teacher") or "").strip(),
            "location": str(values.get("location") or "").strip(),
            "color": str(values.get("color") or "#4f77bb"),
            "notes": str(values.get("notes") or "").strip(),
            "created_at": str(values.get("created_at") or now),
            "updated_at": now,
            "deleted_at": values.get("deleted_at"),
        }
        return self.repository.create_course(course, meetings)

    def update_course(self, course_id: str, values: Mapping[str, Any]) -> dict[str, Any] | None:
        if not self.repository.get_course(course_id):
            return None
        allowed = {"name", "teacher", "location", "color", "notes"}
        changes = {key: str(values[key] or "").strip() for key in allowed if key in values}
        if "name" in changes and not changes["name"]:
            raise ValueError("课程名称不能为空")
        if changes:
            changes["updated_at"] = utc_now()
        result = self.repository.update_course(course_id, changes)
        if "meetings" in values:
            source = values["meetings"]
            if not isinstance(source, list) or not source:
                raise ValueError("课程至少需要一个上课时段")
            meetings = [self.normalize_meeting(item, course_id=course_id) for item in source]
            self.repository.replace_meetings(course_id, meetings)
            result = self.repository.get_course(course_id)
        return result

    def duplicate_course(self, course_id: str) -> dict[str, Any] | None:
        source = self.repository.get_course(course_id)
        if not source:
            return None
        source["id"] = str(uuid.uuid4())
        source["name"] = f"{source['name']}（副本）"
        for meeting in source["meetings"]:
            meeting["id"] = str(uuid.uuid4())
        return self.create_course(source)

    def calendar_events(self, start: str, end: str) -> list[dict[str, Any]]:
        start_date = date.fromisoformat(self._date(start, "start"))
        end_date = date.fromisoformat(self._date(end, "end"))
        if end_date < start_date or (end_date - start_date).days > 370:
            raise ValueError("日历查询范围必须为 0 到 370 天")
        events: list[dict[str, Any]] = []
        for meeting in self.repository.meetings_between():
            semester_start = date.fromisoformat(meeting["semester_start"])
            semester_end = date.fromisoformat(meeting["semester_end"])
            week_one_monday = semester_start - timedelta(days=semester_start.weekday())
            cursor = max(start_date, semester_start)
            limit = min(end_date, semester_end)
            while cursor <= limit:
                if cursor.isoweekday() == int(meeting["weekday"]):
                    week = ((cursor - week_one_monday).days // 7) + 1
                    allowed = meeting["start_week"] <= week <= meeting["end_week"]
                    pattern = meeting["week_pattern"]
                    if pattern == "odd":
                        allowed = allowed and week % 2 == 1
                    elif pattern == "even":
                        allowed = allowed and week % 2 == 0
                    elif pattern == "custom":
                        allowed = allowed and week in meeting["custom_weeks"]
                    if allowed and cursor.isoformat() not in meeting["skipped_dates"]:
                        events.append(
                            {
                                "id": f"{meeting['id']}:{cursor.isoformat()}",
                                "source_type": "course",
                                "meeting_id": meeting["id"],
                                "course_id": meeting["course_id"],
                                "semester_id": meeting["semester_id"],
                                "title": meeting["name"],
                                "teacher": meeting["teacher"],
                                "location": meeting["location"],
                                "color": meeting["color"],
                                "date": cursor.isoformat(),
                                "start_time": meeting["start_time"],
                                "end_time": meeting["end_time"],
                                "week": week,
                                "start_period": meeting["start_period"],
                                "end_period": meeting["end_period"],
                            }
                        )
                cursor += timedelta(days=1)
        events.extend(self._task_time_events(start_date, end_date))
        return sorted(events, key=lambda item: (item["date"], item["start_time"], item["title"]))

    def _task_time_events(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        colors = {
            "research": "#5b759d",
            "course": "#b17b42",
            "personal": "#7a6aa6",
            "inbox": "#66736d",
        }
        events: list[dict[str, Any]] = []
        for task in self.tasks.list():
            if task.get("schedule_mode") != "time_block":
                continue
            if task.get("status") in {"completed", "cancelled"}:
                continue
            try:
                first = date.fromisoformat(str(task.get("scheduled_date") or ""))
                start_time = self._time(task.get("scheduled_start_time"), "开始时间")
                end_time = self._time(task.get("scheduled_end_time"), "结束时间")
            except ValueError:
                continue
            if end_time <= start_time:
                continue
            recurring = bool(task.get("is_recurring")) and task.get("recurrence_rule") == "weekly"
            last = first
            if recurring:
                try:
                    last = date.fromisoformat(str(task.get("recurrence_until") or first.isoformat()))
                except ValueError:
                    last = first
            cursor = max(start_date, first)
            limit = min(end_date, last)
            while cursor <= limit:
                allowed = cursor == first or (recurring and cursor >= first and cursor.isoweekday() == first.isoweekday())
                if allowed:
                    events.append({
                        "id": f"task:{task['id']}:{cursor.isoformat()}",
                        "source_type": "task",
                        "task_id": task["id"],
                        "title": task["title"],
                        "date": cursor.isoformat(),
                        "start_time": start_time,
                        "end_time": end_time,
                        "color": colors.get(str(task.get("domain")), colors["inbox"]),
                        "location": "时间段任务",
                        "recurring": recurring,
                    })
                cursor += timedelta(days=1)
        return events

    def skip_occurrence(self, meeting_id: str, occurrence_date: Any) -> bool:
        value = self._date(occurrence_date, "课程日期")
        return self.repository.add_skip(meeting_id, str(uuid.uuid4()), value, utc_now())

    def trash_course(self, course_id: str) -> bool:
        return self.repository.set_deleted(course_id, utc_now())

    def restore_course(self, course_id: str) -> bool:
        return self.repository.set_deleted(course_id, None)
