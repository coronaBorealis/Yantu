from __future__ import annotations

from pathlib import Path
from typing import Any

from ..models import ProjectCategory
from ..repository import database, init_db


CATEGORY_TO_DOMAIN = {
    ProjectCategory.RESEARCH.value: "research",
    ProjectCategory.COURSE.value: "course",
    ProjectCategory.WORK.value: "personal",
    ProjectCategory.PERSONAL.value: "personal",
}


class ProjectRepository:
    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def list(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM projects ORDER BY updated_at DESC, name"
            ).fetchall()
        return [dict(row) for row in rows]

    def get(self, project_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
        return dict(row) if row else None

    def create(self, project: dict[str, Any]) -> dict[str, Any]:
        category = str(project["category"])
        record = {
            **project,
            "category": category,
            "domain": CATEGORY_TO_DOMAIN[category],
            "status": str(project.get("status") or "active"),
        }
        columns = list(record)
        with database(self.db_path) as connection:
            connection.execute(
                f"INSERT INTO projects ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                [record[column] for column in columns],
            )
        result = self.get(str(record["id"]))
        assert result is not None
        return result

    def update(self, project_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
        if not changes:
            return self.get(project_id)
        record = dict(changes)
        if "category" in record:
            category = str(record["category"])
            record["domain"] = CATEGORY_TO_DOMAIN[category]
        columns = list(record)
        with database(self.db_path) as connection:
            cursor = connection.execute(
                f"UPDATE projects SET {', '.join(f'{column} = ?' for column in columns)} WHERE id = ?",
                [*[record[column] for column in columns], project_id],
            )
            if cursor.rowcount == 0:
                return None
        return self.get(project_id)

    def delete(self, project_id: str) -> bool:
        with database(self.db_path) as connection:
            cursor = connection.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            return cursor.rowcount > 0
