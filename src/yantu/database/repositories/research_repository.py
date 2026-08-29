from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from ..repository import database, init_db


def _decode_item(row: Any) -> dict[str, Any]:
    item = dict(row)
    for source, target, fallback in (
        ("creators_json", "creators", []),
        ("metadata_json", "metadata", {}),
    ):
        raw = item.pop(source, None)
        try:
            item[target] = json.loads(raw or "")
        except (TypeError, json.JSONDecodeError):
            item[target] = fallback
    return item


class ResearchRepository:
    """Persistence boundary for Zotero-ready research metadata."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = db_path
        init_db(db_path)

    def list_sources(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM research_sources ORDER BY display_name, created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def get_source(self, source_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                "SELECT * FROM research_sources WHERE id = ?", (source_id,)
            ).fetchone()
        return dict(row) if row else None

    def upsert_source(self, values: dict[str, Any]) -> dict[str, Any]:
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO research_sources
                    (id,provider,library_type,library_id,display_name,access_mode,
                     base_url,server_id,enabled,auto_sync,
                     sync_cursor,last_synced_at,last_sync_status,last_sync_error,
                     created_at,updated_at)
                VALUES
                    (:id,:provider,:library_type,:library_id,:display_name,:access_mode,
                     :base_url,:server_id,:enabled,:auto_sync,
                     :sync_cursor,:last_synced_at,:last_sync_status,:last_sync_error,
                     :created_at,:updated_at)
                ON CONFLICT(provider,library_type,library_id) DO UPDATE SET
                    display_name=excluded.display_name,
                    access_mode=excluded.access_mode,
                    base_url=excluded.base_url,
                    server_id=COALESCE(excluded.server_id,research_sources.server_id),
                    enabled=excluded.enabled,
                    auto_sync=excluded.auto_sync,
                    sync_cursor=COALESCE(excluded.sync_cursor,research_sources.sync_cursor),
                    last_synced_at=COALESCE(excluded.last_synced_at,research_sources.last_synced_at),
                    last_sync_status=CASE
                        WHEN excluded.last_sync_status='never'
                             AND research_sources.last_sync_status!='never'
                        THEN research_sources.last_sync_status
                        ELSE excluded.last_sync_status
                    END,
                    last_sync_error=CASE
                        WHEN excluded.last_sync_status='never'
                        THEN research_sources.last_sync_error
                        ELSE excluded.last_sync_error
                    END,
                    updated_at=excluded.updated_at
                """,
                values,
            )
            row = connection.execute(
                """SELECT * FROM research_sources
                   WHERE provider=? AND library_type=? AND library_id=?""",
                (values["provider"], values["library_type"], values["library_id"]),
            ).fetchone()
        assert row is not None
        return dict(row)

    def update_source_sync(
        self,
        source_id: str,
        *,
        cursor: str | None,
        server_id: str | None,
        status: str,
        error: str,
        synced_at: str | None,
        updated_at: str,
    ) -> dict[str, Any]:
        with database(self.db_path) as connection:
            connection.execute(
                """
                UPDATE research_sources
                SET sync_cursor=?, server_id=COALESCE(?,server_id),
                    last_sync_status=?, last_sync_error=?, last_synced_at=?, updated_at=?
                WHERE id=?
                """,
                (cursor, server_id, status, error, synced_at, updated_at, source_id),
            )
        result = self.get_source(source_id)
        assert result is not None
        return result

    def list_items(
        self, *, source_id: str | None = None, include_deleted: bool = False
    ) -> list[dict[str, Any]]:
        clauses = [] if include_deleted else ["i.deleted_at IS NULL"]
        params: list[Any] = []
        if source_id:
            clauses.append("i.source_id = ?")
            params.append(source_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with database(self.db_path) as connection:
            rows = connection.execute(
                f"""
                SELECT i.*, s.display_name AS source_name,
                       s.library_type, s.library_id
                FROM research_items i
                JOIN research_sources s ON s.id = i.source_id
                {where}
                ORDER BY COALESCE(i.collected_at, i.created_at) DESC, i.title
                """,
                params,
            ).fetchall()
        return [_decode_item(row) for row in rows]

    def get_item(self, item_id: str) -> dict[str, Any] | None:
        with database(self.db_path) as connection:
            row = connection.execute(
                """
                SELECT i.*, s.display_name AS source_name,
                       s.library_type, s.library_id
                FROM research_items i
                JOIN research_sources s ON s.id = i.source_id
                WHERE i.id = ?
                """,
                (item_id,),
            ).fetchone()
        return _decode_item(row) if row else None

    def upsert_item(self, values: dict[str, Any], *, add_to_inbox: bool) -> dict[str, Any]:
        stored = dict(values)
        stored["creators_json"] = json.dumps(stored.pop("creators"), ensure_ascii=False)
        stored["metadata_json"] = json.dumps(stored.pop("metadata"), ensure_ascii=False)
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO research_items
                    (id,source_id,external_key,item_type,title,abstract,creators_json,
                     publication_title,published_at,doi,url,zotero_uri,attachment_path,
                     metadata_json,external_version,collected_at,last_synced_at,deleted_at,
                     created_at,updated_at)
                VALUES
                    (:id,:source_id,:external_key,:item_type,:title,:abstract,:creators_json,
                     :publication_title,:published_at,:doi,:url,:zotero_uri,:attachment_path,
                     :metadata_json,:external_version,:collected_at,:last_synced_at,:deleted_at,
                     :created_at,:updated_at)
                ON CONFLICT(source_id,external_key) DO UPDATE SET
                    item_type=excluded.item_type,
                    title=excluded.title,
                    abstract=excluded.abstract,
                    creators_json=excluded.creators_json,
                    publication_title=excluded.publication_title,
                    published_at=excluded.published_at,
                    doi=excluded.doi,
                    url=excluded.url,
                    zotero_uri=excluded.zotero_uri,
                    attachment_path=excluded.attachment_path,
                    metadata_json=excluded.metadata_json,
                    external_version=excluded.external_version,
                    collected_at=COALESCE(excluded.collected_at,research_items.collected_at),
                    last_synced_at=excluded.last_synced_at,
                    deleted_at=excluded.deleted_at,
                    updated_at=excluded.updated_at
                """,
                stored,
            )
            row = connection.execute(
                "SELECT id FROM research_items WHERE source_id=? AND external_key=?",
                (stored["source_id"], stored["external_key"]),
            ).fetchone()
            assert row is not None
            item_id = str(row[0])
            if add_to_inbox:
                connection.execute(
                    """
                    INSERT OR IGNORE INTO research_inbox
                        (research_item_id,status,added_at)
                    VALUES (?, 'pending', ?)
                    """,
                    (item_id, stored["collected_at"] or stored["created_at"]),
                )
        result = self.get_item(item_id)
        assert result is not None
        return result

    def link_task(
        self, task_id: str, item_id: str, relation_type: str, note: str, created_at: str
    ) -> None:
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO task_research_items
                    (task_id,research_item_id,relation_type,note,created_at)
                VALUES (?,?,?,?,?)
                ON CONFLICT(task_id,research_item_id,relation_type)
                DO UPDATE SET note=excluded.note
                """,
                (task_id, item_id, relation_type, note, created_at),
            )

    def list_task_items(self, task_id: str) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT i.*, l.relation_type, l.note AS relation_note,
                       s.display_name AS source_name, s.library_type, s.library_id
                FROM task_research_items l
                JOIN research_items i ON i.id = l.research_item_id
                JOIN research_sources s ON s.id = i.source_id
                WHERE l.task_id = ? AND i.deleted_at IS NULL
                ORDER BY l.created_at, i.title
                """,
                (task_id,),
            ).fetchall()
        return [_decode_item(row) for row in rows]

    def link_project_items(
        self,
        project_id: str,
        item_ids: list[str],
        *,
        relation_type: str,
        import_mode: str,
        source_collection_key: str | None,
        note: str,
        created_at: str,
    ) -> int:
        """Link papers to a project and report only newly created links."""
        if not item_ids:
            return 0
        created = 0
        with database(self.db_path) as connection:
            for item_id in dict.fromkeys(item_ids):
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO project_research_items
                        (project_id,research_item_id,relation_type,import_mode,
                         source_collection_key,note,created_at)
                    VALUES (?,?,?,?,?,?,?)
                    """,
                    (
                        project_id,
                        item_id,
                        relation_type,
                        import_mode,
                        source_collection_key,
                        note,
                        created_at,
                    ),
                )
                created += int(cursor.rowcount)
        return created

    def list_project_items(self, project_id: str) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT i.*, l.relation_type, l.import_mode,
                       l.source_collection_key, l.note AS relation_note,
                       l.created_at AS imported_at,
                       s.display_name AS source_name,
                       s.library_type, s.library_id
                FROM project_research_items l
                JOIN research_items i ON i.id = l.research_item_id
                JOIN research_sources s ON s.id = i.source_id
                WHERE l.project_id = ? AND i.deleted_at IS NULL
                ORDER BY l.created_at DESC, i.title
                """,
                (project_id,),
            ).fetchall()
        return [_decode_item(row) for row in rows]

    def list_project_links(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM project_research_items ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_inbox(self, status: str = "pending") -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                """
                SELECT q.status AS inbox_status, q.task_id AS generated_task_id,
                       q.added_at, q.resolved_at, i.*,
                       s.display_name AS source_name, s.library_type, s.library_id
                FROM research_inbox q
                JOIN research_items i ON i.id = q.research_item_id
                JOIN research_sources s ON s.id = i.source_id
                WHERE q.status = ? AND i.deleted_at IS NULL
                ORDER BY q.added_at DESC
                """,
                (status,),
            ).fetchall()
        return [_decode_item(row) for row in rows]

    def list_links(self) -> list[dict[str, Any]]:
        with database(self.db_path) as connection:
            rows = connection.execute(
                "SELECT * FROM task_research_items ORDER BY created_at"
            ).fetchall()
        return [dict(row) for row in rows]

    def resolve_inbox(
        self, item_id: str, status: str, task_id: str | None, resolved_at: str
    ) -> bool:
        with database(self.db_path) as connection:
            cursor = connection.execute(
                """
                UPDATE research_inbox
                SET status=?, task_id=?, resolved_at=?
                WHERE research_item_id=?
                """,
                (status, task_id, resolved_at, item_id),
            )
        return cursor.rowcount > 0

    def soft_delete_external_items(
        self, source_id: str, external_keys: list[str], deleted_at: str
    ) -> int:
        if not external_keys:
            return 0
        placeholders = ",".join("?" for _ in external_keys)
        with database(self.db_path) as connection:
            cursor = connection.execute(
                f"""
                UPDATE research_items SET deleted_at=?, updated_at=?
                WHERE source_id=? AND external_key IN ({placeholders})
                  AND deleted_at IS NULL
                """,
                (deleted_at, deleted_at, source_id, *external_keys),
            )
        return int(cursor.rowcount)

    def create_sync_run(self, values: dict[str, Any]) -> None:
        with database(self.db_path) as connection:
            connection.execute(
                """
                INSERT INTO research_sync_runs
                    (id,source_id,status,cursor_before,cursor_after,imported_count,
                     deleted_count,error,started_at,ended_at)
                VALUES
                    (:id,:source_id,:status,:cursor_before,:cursor_after,:imported_count,
                     :deleted_count,:error,:started_at,:ended_at)
                """,
                values,
            )

    def finish_sync_run(
        self,
        run_id: str,
        *,
        status: str,
        cursor_after: str | None,
        imported_count: int,
        deleted_count: int,
        error: str,
        ended_at: str,
    ) -> None:
        with database(self.db_path) as connection:
            connection.execute(
                """
                UPDATE research_sync_runs
                SET status=?, cursor_after=?, imported_count=?, deleted_count=?,
                    error=?, ended_at=? WHERE id=?
                """,
                (
                    status,
                    cursor_after,
                    imported_count,
                    deleted_count,
                    error,
                    ended_at,
                    run_id,
                ),
            )

    def convert_inbox_to_task(
        self,
        item_id: str,
        task: dict[str, Any],
        *,
        relation_type: str,
        relation_note: str,
    ) -> tuple[str, bool]:
        """Atomically materialize one inbox item; retries return the same task."""
        with database(self.db_path) as connection:
            queued = connection.execute(
                "SELECT status,task_id FROM research_inbox WHERE research_item_id=?",
                (item_id,),
            ).fetchone()
            if not queued:
                raise ValueError("论文不在科研收件箱中")
            if queued["status"] == "converted" and queued["task_id"]:
                return str(queued["task_id"]), False
            if queued["status"] != "pending":
                raise ValueError("该论文已从科研收件箱移除")
            columns = list(task)
            values = [
                json.dumps(task[key], ensure_ascii=False)
                if key == "tags"
                else task[key]
                for key in columns
            ]
            try:
                connection.execute(
                    f"INSERT INTO tasks ({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
                    values,
                )
                connection.execute(
                    """
                    INSERT INTO task_research_items
                        (task_id,research_item_id,relation_type,note,created_at)
                    VALUES (?,?,?,?,?)
                    """,
                    (
                        task["id"],
                        item_id,
                        relation_type,
                        relation_note,
                        task["created_at"],
                    ),
                )
                connection.execute(
                    """
                    UPDATE research_inbox
                    SET status='converted',task_id=?,resolved_at=?
                    WHERE research_item_id=?
                    """,
                    (task["id"], task["created_at"], item_id),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"创建论文任务失败：{exc}") from exc
        return str(task["id"]), True
