from __future__ import annotations

import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from ..common import utc_now
from ..database.constants import DOMAINS
from ..database.models import Task, TaskPriority, TaskStatus
from ..database.repositories import ProjectRepository, TaskRepository


class TaskService:
    def __init__(self, db_path: Path | str) -> None:
        self.repository = TaskRepository(db_path)
        self.projects = ProjectRepository(db_path)

    def list(
        self,
        *,
        project_id: str | None = None,
        status: TaskStatus | str | None = None,
        sort_by_deadline: bool = False,
    ) -> list[Task]:
        records = self.repository.list(
            project_id=project_id,
            status=status,
            sort_by_deadline=sort_by_deadline,
        )
        return [Task.from_record(record) for record in records]

    def list_records(
        self,
        *,
        domain: str | None = None,
        project_id: str | None = None,
        status: TaskStatus | str | None = None,
        sort_by_deadline: bool = False,
    ) -> list[dict[str, Any]]:
        return self.repository.list(
            domain=domain,
            project_id=project_id,
            status=status,
            sort_by_deadline=sort_by_deadline,
        )

    def get(self, task_id: str) -> Task | None:
        record = self.repository.get(task_id)
        return Task.from_record(record) if record else None

    def get_record(self, task_id: str) -> dict[str, Any] | None:
        return self.repository.get(task_id)

    def create_record(self, values: dict[str, Any]) -> dict[str, Any]:
        return self.repository.create(values)

    def update_record(self, task_id: str, values: dict[str, Any]) -> dict[str, Any] | None:
        return self.repository.update(task_id, values)

    def count(self) -> int:
        return self.repository.count()

    def create(self, values: Mapping[str, Any]) -> Task:
        title = self._title(values.get("title"))
        project_id = self._related_id(values.get("project_id"), "项目", self.projects.get)
        parent_id = self._related_id(
            values.get("parent_task_id"), "父任务", self.repository.get
        )
        deadline = self._deadline(values.get("deadline"))
        estimated_hours = self._hours(values.get("estimated_hours", 0), "预计工时")
        actual_hours = self._hours(values.get("actual_hours", 0), "实际工时")
        priority = TaskPriority.parse(values.get("priority"))
        status = TaskStatus.parse(values.get("status"))
        domain = str(values.get("domain") or "inbox")
        if domain not in DOMAINS:
            raise ValueError("无效的任务领域")
        now = utc_now()
        record = self.repository.create(
            {
                "id": str(uuid.uuid4()),
                "parent_task_id": parent_id,
                "project_id": project_id,
                "title": title,
                "domain": domain,
                "subcategory": str(values.get("subcategory") or "").strip(),
                "tags": list(values.get("tags") or []),
                "description": str(values.get("description") or "").strip(),
                "created_at": now,
                "updated_at": now,
                "start_date": values.get("start_date"),
                "deadline": deadline,
                "estimated_hours": estimated_hours,
                "actual_hours": actual_hours,
                "priority": priority.value,
                "status": status.value,
                "progress": 100 if status is TaskStatus.DONE else int(values.get("progress") or 0),
                "is_recurring": int(bool(values.get("is_recurring", False))),
                "recurrence_rule": str(values.get("recurrence_rule") or "").strip(),
                "notes": str(values.get("notes") or "").strip(),
                "completed_at": now if status is TaskStatus.DONE else None,
                "sort_order": int(values.get("sort_order") or 0),
            }
        )
        return Task.from_record(record)

    def update(self, task_id: str, values: Mapping[str, Any]) -> Task | None:
        if not self.repository.get(task_id):
            return None
        changes: dict[str, Any] = {}
        if "title" in values:
            changes["title"] = self._title(values["title"])
        if "project_id" in values:
            changes["project_id"] = self._related_id(
                values["project_id"], "项目", self.projects.get
            )
        if "parent_task_id" in values:
            parent_id = self._related_id(
                values["parent_task_id"], "父任务", self.repository.get
            )
            self._validate_parent(task_id, parent_id)
            changes["parent_task_id"] = parent_id
        if "deadline" in values:
            changes["deadline"] = self._deadline(values["deadline"])
        for field, label in (("estimated_hours", "预计工时"), ("actual_hours", "实际工时")):
            if field in values:
                changes[field] = self._hours(values[field], label)
        if "priority" in values:
            changes["priority"] = TaskPriority.parse(values["priority"]).value
        if "status" in values:
            status = TaskStatus.parse(values["status"])
            changes["status"] = status.value
            changes["progress"] = 100 if status is TaskStatus.DONE else int(values.get("progress") or 0)
            changes["completed_at"] = utc_now() if status is TaskStatus.DONE else None
        for field in ("description", "notes"):
            if field in values:
                changes[field] = str(values[field] or "").strip()
        if not changes:
            return self.get(task_id)
        changes["updated_at"] = utc_now()
        record = self.repository.update(task_id, changes)
        return Task.from_record(record) if record else None

    def delete(self, task_id: str) -> bool:
        return self.repository.delete(task_id)

    @staticmethod
    def _title(value: Any) -> str:
        title = str(value or "").strip()
        if not title:
            raise ValueError("任务标题不能为空")
        if len(title) > 160:
            raise ValueError("任务标题不能超过 160 个字符")
        return title

    @staticmethod
    def _deadline(value: Any) -> str | None:
        if value in (None, ""):
            return None
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError("deadline 必须使用 YYYY-MM-DD") from exc

    @staticmethod
    def _hours(value: Any, label: str) -> float:
        try:
            hours = float(value or 0)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label}必须是非负数字") from exc
        if hours < 0:
            raise ValueError(f"{label}必须是非负数字")
        return round(hours, 4)

    @staticmethod
    def _related_id(value: Any, label: str, getter: Any) -> str | None:
        if value in (None, ""):
            return None
        identifier = str(value)
        if not getter(identifier):
            raise ValueError(f"{label}不存在")
        return identifier

    def _validate_parent(self, task_id: str, parent_id: str | None) -> None:
        visited: set[str] = set()
        current_id = parent_id
        while current_id:
            if current_id == task_id or current_id in visited:
                raise ValueError("任务层级不能形成循环")
            visited.add(current_id)
            current = self.repository.get(current_id)
            if not current:
                break
            current_id = current.get("parent_task_id") or current.get("parent_id")
