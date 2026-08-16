from __future__ import annotations

from pathlib import Path
from typing import Any

from ..constants import STATUSES
from ..models import STATUS_TO_STORAGE, TaskPriority, TaskStatus
from ..repository import (
    delete_task,
    get_task,
    init_db,
    insert_task,
    insert_tasks,
    list_tasks,
    task_count,
    update_task,
)


class TaskRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    @staticmethod
    def _to_storage(values: dict[str, Any]) -> dict[str, Any]:
        record = dict(values)
        if "priority" in record:
            record["priority"] = TaskPriority.parse(record["priority"]).value.lower()
        if "status" in record:
            status = record["status"]
            record["status"] = (
                status
                if isinstance(status, str) and status in STATUSES
                else STATUS_TO_STORAGE[TaskStatus.parse(status)]
            )
        return record

    def list(
        self,
        *,
        project_id: str | None = None,
        status: TaskStatus | str | None = None,
        domain: str | None = None,
        sort_by_deadline: bool = False,
    ) -> list[dict[str, Any]]:
        stored_status = None
        if status is not None:
            stored_status = (
                status
                if isinstance(status, str) and status in STATUSES
                else STATUS_TO_STORAGE[TaskStatus.parse(status)]
            )
        return list_tasks(
            self.db_path,
            project_id=project_id,
            status=stored_status,
            domain=domain,
            sort_by_deadline=sort_by_deadline,
        )

    def get(self, task_id: str) -> dict[str, Any] | None:
        return get_task(self.db_path, task_id)

    def create(self, task: dict[str, Any]) -> dict[str, Any]:
        return insert_task(self.db_path, self._to_storage(task))

    def create_many(self, tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return insert_tasks(self.db_path, [self._to_storage(task) for task in tasks])

    def update(self, task_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        return update_task(self.db_path, task_id, self._to_storage(changes))

    def delete(self, task_id: str) -> bool:
        return delete_task(self.db_path, task_id)

    def count(self) -> int:
        return task_count(self.db_path)
