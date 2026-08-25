from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping


class ProjectCategory(str, Enum):
    RESEARCH = "科研"
    COURSE = "课程"
    WORK = "工作"
    PERSONAL = "个人"


class TaskPriority(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    URGENT = "URGENT"

    @classmethod
    def parse(cls, value: object) -> "TaskPriority":
        if isinstance(value, cls):
            return value
        normalized = str(value or cls.MEDIUM.value).strip().upper()
        return cls(normalized)


class TaskStatus(str, Enum):
    TODO = "TODO"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    CANCELLED = "CANCELLED"

    @classmethod
    def parse(cls, value: object) -> "TaskStatus":
        if isinstance(value, cls):
            return value
        normalized = str(value or cls.TODO.value).strip().upper()
        aliases = {
            "NOT_STARTED": cls.TODO,
            "WAITING": cls.IN_PROGRESS,
            "COMPLETED": cls.DONE,
        }
        if normalized in aliases:
            return aliases[normalized]
        return cls(normalized)


STATUS_TO_STORAGE = {
    TaskStatus.TODO: "not_started",
    TaskStatus.IN_PROGRESS: "in_progress",
    TaskStatus.DONE: "completed",
    TaskStatus.CANCELLED: "cancelled",
}


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    description: str
    category: ProjectCategory
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Project":
        return cls(
            id=str(record["id"]),
            name=str(record["name"]),
            description=str(record.get("description") or ""),
            category=ProjectCategory(str(record.get("category") or "个人")),
            created_at=str(record["created_at"]),
            updated_at=str(record["updated_at"]),
        )


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    project_id: str | None
    priority: TaskPriority
    status: TaskStatus
    deadline: str | None
    estimated_hours: float
    actual_hours: float
    parent_task_id: str | None
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "Task":
        return cls(
            id=str(record["id"]),
            title=str(record["title"]),
            project_id=str(record["project_id"]) if record.get("project_id") else None,
            priority=TaskPriority.parse(record.get("priority")),
            status=TaskStatus.parse(record.get("status")),
            deadline=str(record["deadline"]) if record.get("deadline") else None,
            estimated_hours=float(record.get("estimated_hours") or 0),
            actual_hours=float(record.get("actual_hours") or 0),
            parent_task_id=(
                str(record["parent_task_id"]) if record.get("parent_task_id") else None
            ),
            created_at=str(record["created_at"]),
            updated_at=str(record["updated_at"]),
        )


@dataclass(frozen=True)
class TimeEntry:
    id: str
    task_id: str
    start_time: str
    end_time: str | None
    duration: int
    note: str
    created_at: str

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "TimeEntry":
        return cls(
            id=str(record["id"]),
            task_id=str(record["task_id"]),
            start_time=str(record["start_time"]),
            end_time=str(record["end_time"]) if record.get("end_time") else None,
            duration=int(record.get("duration") or 0),
            note=str(record.get("note") or ""),
            created_at=str(record["created_at"]),
        )


@dataclass(frozen=True)
class Semester:
    id: str
    name: str
    start_date: str
    end_date: str
    timezone: str
    periods: list[dict[str, Any]]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class Course:
    id: str
    semester_id: str
    name: str
    teacher: str
    location: str
    color: str
    notes: str
    created_at: str
    updated_at: str
    deleted_at: str | None = None


@dataclass(frozen=True)
class CourseMeeting:
    id: str
    course_id: str
    weekday: int
    start_period: int
    end_period: int
    start_time: str
    end_time: str
    start_week: int
    end_week: int
    week_pattern: str
    custom_weeks: list[int]


class FocusSessionType(str, Enum):
    FOCUS = "focus"
    SHORT_BREAK = "short_break"
    LONG_BREAK = "long_break"


class FocusMode(str, Enum):
    POMODORO = "pomodoro"
    FREE = "free"


class FocusStatus(str, Enum):
    RUNNING = "running"
    PAUSED = "paused"
    AWAITING_ACTION = "awaiting_action"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True)
class FocusSession:
    id: str
    task_id: str | None
    plan_block_id: str | None
    parent_session_id: str | None
    session_type: FocusSessionType
    mode: FocusMode
    status: FocusStatus
    target_seconds: int
    elapsed_seconds: int
    paused_seconds: int
    pause_count: int
    started_at: str
    last_resumed_at: str | None
    ended_at: str | None
    time_entry_id: str | None
    note: str
    created_at: str
    updated_at: str

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> "FocusSession":
        nullable = lambda key: str(record[key]) if record.get(key) else None
        return cls(
            id=str(record["id"]), task_id=nullable("task_id"),
            plan_block_id=nullable("plan_block_id"), parent_session_id=nullable("parent_session_id"),
            session_type=FocusSessionType(str(record["session_type"])),
            mode=FocusMode(str(record["mode"])), status=FocusStatus(str(record["status"])),
            target_seconds=int(record.get("target_seconds") or 0),
            elapsed_seconds=int(record.get("elapsed_seconds") or 0),
            paused_seconds=int(record.get("paused_seconds") or 0),
            pause_count=int(record.get("pause_count") or 0),
            started_at=str(record["started_at"]), last_resumed_at=nullable("last_resumed_at"),
            ended_at=nullable("ended_at"), time_entry_id=nullable("time_entry_id"),
            note=str(record.get("note") or ""), created_at=str(record["created_at"]),
            updated_at=str(record["updated_at"]),
        )
