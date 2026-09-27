from __future__ import annotations

import re
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

from ..common import utc_now
from ..database.repositories import ProjectRepository, ResearchRepository, TaskRepository


RELATION_TYPES = {"reference", "reading", "review", "citation", "output"}
LIBRARY_TYPES = {"user", "group", "local"}
INBOX_STATUSES = {"pending", "converted", "dismissed"}
TASK_PRIORITIES = {"low", "medium", "high", "urgent"}
TASK_STATUSES = {"not_started", "waiting"}
ITEM_KEY = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class ResearchService:
    """Local research catalogue prepared for a later Zotero sync adapter."""

    def __init__(self, db_path: Path | str) -> None:
        self.repository = ResearchRepository(db_path)
        self.tasks = TaskRepository(db_path)
        self.projects = ProjectRepository(db_path)

    def list_sources(self) -> list[dict[str, Any]]:
        return self.repository.list_sources()

    def save_source(self, values: Mapping[str, Any]) -> dict[str, Any]:
        provider = str(values.get("provider") or "zotero").strip().lower()
        if provider != "zotero":
            raise ValueError("当前仅预留 Zotero 来源")
        library_type = str(values.get("library_type") or "user").strip().lower()
        if library_type not in LIBRARY_TYPES:
            raise ValueError("library_type 必须是 user、group 或 local")
        library_id = str(values.get("library_id") or "").strip()
        if library_type == "group" and not library_id:
            raise ValueError("群组文库必须提供 library_id")
        access_mode = str(values.get("access_mode") or "local").strip().lower()
        if access_mode not in {"local", "web"}:
            raise ValueError("access_mode 必须是 local 或 web")
        if access_mode == "web" and not library_id:
            raise ValueError("Web API 连接必须提供 Zotero 数字文库 ID")
        default_url = (
            "http://127.0.0.1:23119/api"
            if access_mode == "local"
            else "https://api.zotero.org"
        )
        base_url = str(values.get("base_url") or default_url).strip().rstrip("/")
        parsed = urlparse(base_url)
        if access_mode == "local":
            if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
                raise ValueError("本机 Zotero API 必须使用 localhost 或 127.0.0.1")
        elif parsed.scheme != "https" or parsed.hostname != "api.zotero.org":
            raise ValueError("Zotero Web API 地址必须是 https://api.zotero.org")
        elif parsed.port not in (None, 443):
            raise ValueError("Zotero Web API 只允许标准 HTTPS 端口")
        name = str(values.get("display_name") or "Zotero 文库").strip()
        if not name:
            raise ValueError("来源名称不能为空")
        sync_status = str(values.get("last_sync_status") or "never")
        if sync_status not in {"never", "ok", "error", "running"}:
            raise ValueError("无效的同步状态")
        now = utc_now()
        return self.repository.upsert_source(
            {
                "id": str(values.get("id") or uuid.uuid4()),
                "provider": provider,
                "library_type": library_type,
                "library_id": library_id,
                "display_name": name[:120],
                "access_mode": access_mode,
                "base_url": base_url,
                "server_id": self._optional_text(values.get("server_id")),
                "enabled": int(bool(values.get("enabled", True))),
                "auto_sync": int(bool(values.get("auto_sync", False))),
                "sync_cursor": self._optional_text(values.get("sync_cursor")),
                "last_synced_at": self._optional_text(values.get("last_synced_at")),
                "last_sync_status": sync_status,
                "last_sync_error": str(values.get("last_sync_error") or "")[:500],
                "created_at": str(values.get("created_at") or now),
                "updated_at": now,
            }
        )

    def list_items(self, source_id: str | None = None) -> list[dict[str, Any]]:
        return self.repository.list_items(source_id=source_id)

    def save_item(self, values: Mapping[str, Any]) -> dict[str, Any]:
        source_id = str(values.get("source_id") or "")
        source = self.repository.get_source(source_id)
        if not source:
            raise ValueError("科研来源不存在")
        external_key = str(values.get("external_key") or "").strip()
        if not ITEM_KEY.fullmatch(external_key):
            raise ValueError("external_key 格式无效")
        title = str(values.get("title") or "").strip()
        if not title:
            raise ValueError("论文标题不能为空")
        creators = values.get("creators") or []
        metadata = values.get("metadata") or {}
        if not isinstance(creators, list) or not isinstance(metadata, dict):
            raise ValueError("creators 必须是数组，metadata 必须是对象")
        zotero_uri = str(
            values.get("zotero_uri") or self.zotero_select_uri(source, external_key)
        )
        if not zotero_uri.startswith("zotero://select/"):
            raise ValueError("zotero_uri 必须是 Zotero 本地选择链接")
        now = utc_now()
        return self.repository.upsert_item(
            {
                "id": str(values.get("id") or uuid.uuid4()),
                "source_id": source_id,
                "external_key": external_key,
                "item_type": str(values.get("item_type") or "journalArticle")[:80],
                "title": title[:500],
                "abstract": str(values.get("abstract") or ""),
                "creators": creators,
                "publication_title": str(values.get("publication_title") or "")[:300],
                "published_at": self._optional_text(values.get("published_at")),
                "doi": str(values.get("doi") or "")[:200],
                "url": str(values.get("url") or "")[:2000],
                "zotero_uri": zotero_uri,
                "attachment_path": self._optional_text(values.get("attachment_path")),
                "metadata": metadata,
                "external_version": self._optional_int(values.get("external_version")),
                "collected_at": str(values.get("collected_at") or now),
                "last_synced_at": str(values.get("last_synced_at") or now),
                "deleted_at": self._optional_text(values.get("deleted_at")),
                "created_at": str(values.get("created_at") or now),
                "updated_at": now,
            },
            add_to_inbox=bool(values.get("add_to_inbox", True)),
        )

    def link_task(self, task_id: str, item_id: str, values: Mapping[str, Any]) -> None:
        if not self.tasks.get(task_id):
            raise ValueError("任务不存在")
        if not self.repository.get_item(item_id):
            raise ValueError("论文条目不存在")
        relation = str(values.get("relation_type") or "reference")
        if relation not in RELATION_TYPES:
            raise ValueError("无效的论文关联类型")
        self.repository.link_task(
            task_id,
            item_id,
            relation,
            str(values.get("note") or "").strip(),
            utc_now(),
        )

    def list_task_items(self, task_id: str) -> list[dict[str, Any]]:
        if not self.tasks.get(task_id):
            raise ValueError("任务不存在")
        return self.repository.list_task_items(task_id)

    def list_project_items(self, project_id: str) -> list[dict[str, Any]]:
        self._research_project(project_id)
        items = self.repository.list_project_items(project_id)
        history = self.repository.reading_history([str(item["id"]) for item in items])
        for item in items:
            item["reading_history"] = history.get(str(item["id"]), [])
        return items

    def list_folders(self, project_id: str) -> list[dict[str, Any]]:
        self._research_project(project_id)
        return self.repository.list_folders(project_id)

    def create_folder(self, project_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        self._research_project(project_id)
        name = str(values.get("name") or "").strip()
        if not name or len(name) > 120:
            raise ValueError("类目名称必须为 1–120 个字符")
        parent_id = str(values.get("parent_id") or "") or None
        if parent_id:
            parent = self.repository.get_folder(parent_id)
            if not parent or parent["project_id"] != project_id:
                raise ValueError("父类目不属于当前科研项目")
        now = utc_now()
        try:
            return self.repository.save_folder({
                "id": str(uuid.uuid4()), "project_id": project_id,
                "parent_id": parent_id, "name": name, "source_id": None,
                "source_collection_key": None, "created_at": now, "updated_at": now,
            })
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValueError("同一层级已有同名类目") from exc
            raise

    def rename_folder(self, project_id: str, folder_id: str,
                      values: Mapping[str, Any]) -> dict[str, Any]:
        folder = self.repository.get_folder(folder_id)
        if not folder or folder["project_id"] != project_id:
            raise ValueError("类目不存在")
        if folder.get("source_collection_key"):
            raise ValueError("Zotero 导入类目由 Zotero 文件夹名称管理")
        name = str(values.get("name") or "").strip()
        if not name or len(name) > 120:
            raise ValueError("类目名称必须为 1–120 个字符")
        try:
            return self.repository.rename_folder(folder_id, name, utc_now())
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValueError("同一层级已有同名类目") from exc
            raise

    def import_collection_folders(self, project_id: str, source_id: str,
                                  collections: list[dict[str, Any]],
                                  root_key: str, item_ids: list[str]) -> None:
        """Mirror the selected Zotero tree and attach imported papers to its leaves."""
        self._research_project(project_id)
        by_key = {str(item["key"]): item for item in collections}
        if root_key not in by_key:
            raise ValueError("Zotero 文件夹不存在")
        relevant = {root_key}
        for item_id in item_ids:
            item = self.repository.get_item(item_id)
            if item and item["source_id"] == source_id:
                relevant.update(str(key) for key in item["metadata"].get("collections", [])
                                if str(key) in by_key)
        relevant = {key for key in relevant if key == root_key or
                    root_key in self._collection_ancestors(key, by_key)}
        for key in list(relevant):
            relevant.update(self._collection_ancestors(key, by_key) & set(by_key))
        folder_specs = [by_key[key] for key in sorted(
            relevant, key=lambda value: int(by_key[value]["depth"])
        )]
        memberships: dict[str, set[str]] = {}
        for item_id in item_ids:
            item = self.repository.get_item(item_id)
            if not item or item["source_id"] != source_id:
                continue
            keys = set(str(key) for key in item["metadata"].get("collections", [])) & relevant
            memberships[item_id] = keys or {root_key}
        try:
            self.repository.save_imported_tree(
                project_id, source_id, folder_specs, memberships, utc_now()
            )
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                raise ValueError("Zotero 文件夹与已有类目同名，请调整类目名称或关闭层级保留") from exc
            raise

    @staticmethod
    def _collection_ancestors(key: str, by_key: Mapping[str, Mapping[str, Any]]) -> set[str]:
        ancestors: set[str] = set()
        current = str(by_key.get(key, {}).get("parent_key") or "")
        while current and current not in ancestors:
            ancestors.add(current)
            current = str(by_key.get(current, {}).get("parent_key") or "")
        return ancestors

    def add_folder_item(self, project_id: str, folder_id: str, item_id: str) -> None:
        folder = self.repository.get_folder(folder_id)
        if not folder or folder["project_id"] != project_id:
            raise ValueError("类目不存在")
        if item_id not in {item["id"] for item in self.repository.list_project_items(project_id)}:
            raise ValueError("论文不在当前项目中")
        self.repository.add_folder_items(folder_id, [item_id], utc_now())

    def create_linked_task(self, task: dict[str, Any], item_id: str) -> dict[str, Any]:
        if task.get("domain") != "research":
            raise ValueError("论文阅读任务必须属于科研领域")
        self.repository.create_reading_task(item_id, task)
        record = self.tasks.get(str(task["id"]))
        assert record is not None
        return record

    def quick_reading_task(self, item_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        preview = self.preview_task(item_id, {
            "title": values.get("title"), "estimated_minutes": 60,
            "status": "not_started", "subcategory": "论文阅读",
        })
        now = utc_now()
        source = preview["task"]
        task = {
            "id": str(uuid.uuid4()), "parent_id": None, "project_id": None,
            "title": source["title"], "domain": "research",
            "task_kind": "free_learning",
            "subcategory": "论文阅读", "tags": ["Zotero"],
            "description": source["description"], "created_at": now,
            "updated_at": now, "start_date": None, "due_date": None,
            "estimated_minutes": 60, "actual_minutes": 0, "priority": "medium",
            "status": "not_started", "progress": 0, "is_recurring": 0,
            "recurrence_rule": "", "notes": "", "completed_at": None,
            "sort_order": 0,
        }
        resume_task_id = str(values.get("resume_task_id") or "").strip() or None
        task_id, reused = self.repository.get_or_create_quick_reading_task(
            item_id, task, resume_task_id=resume_task_id
        )
        record = self.tasks.get(task_id)
        assert record is not None
        if reused and int(record.get("actual_minutes") or 0) >= max(1, int(record.get("estimated_minutes") or 60)):
            baseline = max(1, int(record.get("estimated_minutes") or 60))
            accumulated = int(record.get("actual_minutes") or 0)
            next_limit = baseline + ((accumulated - baseline) // 60 + 1) * 60
            updated = self.tasks.update(task_id, {
                "estimated_minutes": next_limit,
                "estimated_hours": next_limit / 60,
                "updated_at": now,
            })
            if updated:
                record = updated
        return {"task": record, "reused": reused}

    def link_project_items(
        self,
        project_id: str,
        item_ids: list[str],
        *,
        import_mode: str = "manual",
        collection_key: str | None = None,
        note: str = "",
    ) -> int:
        self._research_project(project_id)
        if import_mode not in {"manual", "collection", "search"}:
            raise ValueError("无效的论文导入方式")
        clean_ids: list[str] = []
        for item_id in dict.fromkeys(str(value or "").strip() for value in item_ids):
            if not item_id:
                continue
            if not self.repository.get_item(item_id):
                raise ValueError("论文条目不存在")
            clean_ids.append(item_id)
        return self.repository.link_project_items(
            project_id,
            clean_ids,
            relation_type="reference",
            import_mode=import_mode,
            source_collection_key=self._optional_text(collection_key),
            note=str(note or "").strip()[:500],
            created_at=utc_now(),
        )

    def list_inbox(self, status: str = "pending") -> list[dict[str, Any]]:
        if status not in INBOX_STATUSES:
            raise ValueError("无效的科研收件箱状态")
        return self.repository.list_inbox(status)

    def dismiss_inbox_item(self, item_id: str) -> bool:
        return self.repository.resolve_inbox(item_id, "dismissed", None, utc_now())

    def preview_task(self, item_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        item = self.repository.get_item(item_id)
        if not item or item.get("deleted_at"):
            raise ValueError("论文条目不存在")
        title = str(values.get("title") or f"阅读：{item['title']}").strip()
        if not title or len(title) > 160:
            raise ValueError("任务标题必须为 1 到 160 个字符")
        due_date = self._optional_date(values.get("due_date"), "due_date")
        start_date = self._optional_date(values.get("start_date"), "start_date")
        if start_date and due_date and start_date > due_date:
            raise ValueError("开始日期不能晚于截止日期")
        try:
            minutes = int(values.get("estimated_minutes", 60))
        except (TypeError, ValueError) as exc:
            raise ValueError("预计耗时必须是整数分钟") from exc
        if not 5 <= minutes <= 10080:
            raise ValueError("预计耗时必须在 5 到 10080 分钟之间")
        priority = str(values.get("priority") or "medium")
        status = str(values.get("status") or "not_started")
        if priority not in TASK_PRIORITIES or status not in TASK_STATUSES:
            raise ValueError("无效的任务优先级或状态")
        citation = " · ".join(
            value
            for value in (
                item.get("publication_title"),
                item.get("published_at"),
                f"DOI: {item['doi']}" if item.get("doi") else "",
            )
            if value
        )
        tags = values.get("tags")
        if tags is None:
            tags = ["Zotero"]
        if not isinstance(tags, list):
            raise ValueError("tags 必须是数组")
        return {
            "item": {
                "id": item["id"],
                "title": item["title"],
                "zotero_uri": item.get("zotero_uri"),
                "creators": item.get("creators", []),
                "citation": citation,
            },
            "task": {
                "title": title,
                "domain": "research",
                "subcategory": str(values.get("subcategory") or "论文阅读").strip()[:80],
                "description": str(values.get("description") or citation).strip(),
                "start_date": start_date,
                "due_date": due_date,
                "estimated_minutes": minutes,
                "priority": priority,
                "status": status,
                "tags": [str(tag).strip() for tag in tags if str(tag).strip()],
            },
            "relation_type": "reading",
        }

    def confirm_task(self, item_id: str, values: Mapping[str, Any]) -> dict[str, Any]:
        preview = self.preview_task(item_id, values.get("task") if isinstance(values.get("task"), Mapping) else values)
        source = preview["task"]
        now = utc_now()
        task_id = str(values.get("task_id") or uuid.uuid4())
        task = {
            "id": task_id,
            "parent_id": None,
            "parent_task_id": None,
            "project_id": None,
            "title": source["title"],
            "domain": "research",
            "subcategory": source["subcategory"],
            "tags": source["tags"],
            "description": source["description"],
            "created_at": now,
            "updated_at": now,
            "start_date": source["start_date"],
            "due_date": source["due_date"],
            "deadline": source["due_date"],
            "estimated_minutes": source["estimated_minutes"],
            "estimated_hours": round(source["estimated_minutes"] / 60, 4),
            "actual_minutes": 0,
            "actual_hours": 0,
            "priority": source["priority"],
            "status": source["status"],
            "progress": 0,
            "is_recurring": 0,
            "recurrence_rule": "",
            "notes": "",
            "completed_at": None,
            "sort_order": 0,
            "deleted_at": None,
        }
        resolved_id, created = self.repository.convert_inbox_to_task(
            item_id,
            task,
            relation_type="reading",
            relation_note=str(values.get("relation_note") or "由科研收件箱创建").strip(),
        )
        record = self.tasks.get_including_deleted(resolved_id)
        assert record is not None
        return {"task": record, "created": created}

    def export_backup(self) -> dict[str, Any]:
        return {
            "sources": self.list_sources(),
            "items": self.repository.list_items(include_deleted=True),
            "links": self.repository.list_links(),
            "project_links": self.repository.list_project_links(),
            "folders": [folder for project in self.projects.list()
                        for folder in self.repository.list_folders(project["id"])],
            "folder_links": self.repository.list_folder_links(),
            "inbox": [
                item
                for status in sorted(INBOX_STATUSES)
                for item in self.repository.list_inbox(status)
            ],
        }

    def import_backup(self, payload: Any) -> dict[str, int]:
        if not isinstance(payload, Mapping):
            return {"research_sources_imported": 0, "research_items_imported": 0}
        source_ids: dict[str, str] = {}
        for source in payload.get("sources") or []:
            if not isinstance(source, Mapping):
                continue
            saved = self.save_source(source)
            source_ids[str(source.get("id") or saved["id"])] = str(saved["id"])
        item_ids: dict[str, str] = {}
        for item in payload.get("items") or []:
            if not isinstance(item, Mapping):
                continue
            source_id = source_ids.get(str(item.get("source_id") or ""))
            if not source_id:
                continue
            saved = self.save_item({**dict(item), "source_id": source_id})
            item_ids[str(item.get("id") or saved["id"])] = str(saved["id"])
        for link in payload.get("links") or []:
            if not isinstance(link, Mapping):
                continue
            item_id = item_ids.get(str(link.get("research_item_id") or ""))
            task_id = str(link.get("task_id") or "")
            if item_id and self.tasks.get(task_id):
                self.link_task(task_id, item_id, link)
        for link in payload.get("project_links") or []:
            if not isinstance(link, Mapping):
                continue
            item_id = item_ids.get(str(link.get("research_item_id") or ""))
            project_id = str(link.get("project_id") or "")
            if item_id and self.projects.get(project_id):
                self.link_project_items(
                    project_id,
                    [item_id],
                    import_mode=str(link.get("import_mode") or "manual"),
                    collection_key=self._optional_text(link.get("source_collection_key")),
                    note=str(link.get("note") or ""),
                )
        folder_ids: dict[str, str] = {}
        pending = [dict(folder) for folder in payload.get("folders") or []
                   if isinstance(folder, Mapping)]
        while pending:
            progressed = False
            for folder in pending[:]:
                project_id = str(folder.get("project_id") or "")
                parent_old = str(folder.get("parent_id") or "")
                if not self.projects.get(project_id):
                    pending.remove(folder)
                    continue
                if parent_old and parent_old not in folder_ids:
                    continue
                name = str(folder.get("name") or "").strip()
                if not name:
                    pending.remove(folder)
                    continue
                now = utc_now()
                saved = self.repository.save_folder({
                    "id": str(folder.get("id") or uuid.uuid4()),
                    "project_id": project_id,
                    "parent_id": folder_ids.get(parent_old),
                    "name": name[:120],
                    "source_id": source_ids.get(str(folder.get("source_id") or "")),
                    "source_collection_key": self._optional_text(folder.get("source_collection_key")),
                    "created_at": str(folder.get("created_at") or now),
                    "updated_at": now,
                })
                folder_ids[str(folder.get("id") or saved["id"])] = saved["id"]
                pending.remove(folder)
                progressed = True
            if not progressed:
                break
        for link in payload.get("folder_links") or []:
            if not isinstance(link, Mapping):
                continue
            folder_id = folder_ids.get(str(link.get("folder_id") or ""))
            item_id = item_ids.get(str(link.get("research_item_id") or ""))
            if folder_id and item_id:
                self.repository.add_folder_items(folder_id, [item_id], utc_now())
        for queued in payload.get("inbox") or []:
            if not isinstance(queued, Mapping):
                continue
            item_id = item_ids.get(str(queued.get("id") or ""))
            status = str(queued.get("inbox_status") or "pending")
            task_id = str(queued.get("generated_task_id") or "") or None
            if item_id and status in {"converted", "dismissed"}:
                self.repository.resolve_inbox(item_id, status, task_id, utc_now())
        return {
            "research_sources_imported": len(source_ids),
            "research_items_imported": len(item_ids),
        }

    @staticmethod
    def zotero_select_uri(source: Mapping[str, Any], item_key: str) -> str:
        if source.get("library_type") == "group":
            return f"zotero://select/groups/{source['library_id']}/items/{item_key}"
        return f"zotero://select/library/items/{item_key}"

    def _research_project(self, project_id: str) -> dict[str, Any]:
        project = self.projects.get(str(project_id or ""))
        if not project:
            raise ValueError("项目不存在")
        if str(project.get("category") or "") != "科研":
            raise ValueError("只有科研类型的项目可以导入论文")
        return project

    @staticmethod
    def _optional_text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _optional_int(value: Any) -> int | None:
        if value in (None, ""):
            return None
        number = int(value)
        if number < 0:
            raise ValueError("external_version 不能为负数")
        return number

    @staticmethod
    def _optional_date(value: Any, field: str) -> str | None:
        if value in (None, ""):
            return None
        try:
            return datetime.strptime(str(value), "%Y-%m-%d").date().isoformat()
        except ValueError as exc:
            raise ValueError(f"{field} 必须使用 YYYY-MM-DD") from exc
