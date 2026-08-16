from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Mapping

from ..common import utc_now
from ..ai.llm_service import LLMService
from ..ai.schemas import TaskBreakdown
from ..database.constants import DOMAINS
from ..database.repositories import TaskRepository


class TaskBreakdownService:
    def __init__(self, db_path: Path | str, llm_service: LLMService) -> None:
        self.db_path = db_path
        self.llm_service = llm_service
        self.task_repository = TaskRepository(db_path)

    def preview(self, task: str) -> TaskBreakdown:
        return self.llm_service.breakdown_task(task)

    def confirm(self, value: Mapping[str, Any], domain: str = "research") -> list[dict[str, Any]]:
        """Persist only an explicitly confirmed, revalidated preview."""
        breakdown = TaskBreakdown.from_mapping(value)
        if domain not in DOMAINS:
            raise ValueError("无效的一级分类")
        now = utc_now()
        parent_id = str(uuid.uuid4())
        estimated_minutes = round(sum(item.estimated_hours for item in breakdown.subtasks) * 60)
        records = [self._record(parent_id, None, breakdown.title, domain, estimated_minutes, "high", now, 0)]
        records.extend(
            self._record(
                str(uuid.uuid4()), parent_id, item.name, domain,
                round(item.estimated_hours * 60), item.priority, now, index,
                notes=("前置依赖：" + "、".join(item.dependencies)) if item.dependencies else "",
            )
            for index, item in enumerate(breakdown.subtasks, start=1)
        )
        return self.task_repository.create_many(records)

    @staticmethod
    def _record(
        task_id: str, parent_id: str | None, title: str, domain: str,
        estimated_minutes: int, priority: str, now: str, sort_order: int, notes: str = "",
    ) -> dict[str, Any]:
        return {
            "id": task_id, "parent_id": parent_id, "project_id": None, "title": title,
            "domain": domain, "subcategory": "AI 拆解", "tags": ["AI拆解"], "description": "",
            "created_at": now, "updated_at": now, "start_date": None, "due_date": None,
            "estimated_minutes": estimated_minutes, "actual_minutes": 0, "priority": priority,
            "status": "not_started", "progress": 0, "is_recurring": 0,
            "recurrence_rule": "", "notes": notes, "sort_order": sort_order,
        }
