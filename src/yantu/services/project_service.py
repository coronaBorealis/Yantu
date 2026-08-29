from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Mapping

from ..common import utc_now
from ..database.models import Project, ProjectCategory
from ..database.repositories import ProjectRepository


class ProjectService:
    def __init__(self, db_path: Path | str) -> None:
        self.repository = ProjectRepository(db_path)

    def list(self) -> list[Project]:
        return [Project.from_record(record) for record in self.repository.list()]

    def get(self, project_id: str) -> Project | None:
        record = self.repository.get(project_id)
        return Project.from_record(record) if record else None

    def create(self, values: Mapping[str, Any]) -> Project:
        name = self._name(values.get("name"))
        category = self._category(values.get("category", ProjectCategory.PERSONAL.value))
        now = utc_now()
        record = self.repository.create(
            {
                "id": str(uuid.uuid4()),
                "name": name,
                "description": str(values.get("description") or "").strip(),
                "category": category.value,
                "created_at": now,
                "updated_at": now,
            }
        )
        return Project.from_record(record)

    def import_record(self, values: Mapping[str, Any]) -> Project:
        project_id = str(values.get("id") or uuid.uuid4())
        existing = self.get(project_id)
        if existing:
            updated = self.update(project_id, values)
            assert updated is not None
            return updated
        name = self._name(values.get("name"))
        category = self._category(values.get("category", ProjectCategory.PERSONAL.value))
        now = utc_now()
        record = self.repository.create(
            {
                "id": project_id,
                "name": name,
                "description": str(values.get("description") or "").strip(),
                "category": category.value,
                "created_at": str(values.get("created_at") or now),
                "updated_at": now,
            }
        )
        return Project.from_record(record)

    def update(self, project_id: str, values: Mapping[str, Any]) -> Project | None:
        changes: dict[str, Any] = {}
        if "name" in values:
            changes["name"] = self._name(values["name"])
        if "description" in values:
            changes["description"] = str(values["description"] or "").strip()
        if "category" in values:
            changes["category"] = self._category(values["category"]).value
        if not changes:
            return self.get(project_id)
        changes["updated_at"] = utc_now()
        record = self.repository.update(project_id, changes)
        return Project.from_record(record) if record else None

    def delete(self, project_id: str) -> bool:
        return self.repository.delete(project_id)

    @staticmethod
    def _name(value: Any) -> str:
        name = str(value or "").strip()
        if not name:
            raise ValueError("项目名称不能为空")
        if len(name) > 160:
            raise ValueError("项目名称不能超过 160 个字符")
        return name

    @staticmethod
    def _category(value: Any) -> ProjectCategory:
        try:
            return ProjectCategory(str(value).strip())
        except ValueError as exc:
            raise ValueError("项目类别必须是科研、课程、工作或个人") from exc
