from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from urllib.error import URLError

import pytest

from yantu.database.repository import init_db
from yantu.main import create_app
from yantu.services.research_service import ResearchService
from yantu.services.zotero_service import ZoteroService


class MemoryZoteroCredentials:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}

    def get(self, source_id: str) -> str:
        return self.values.get(source_id, "")

    def set(self, source_id: str, value: str) -> None:
        self.values[source_id] = value

    def delete(self, source_id: str) -> None:
        self.values.pop(source_id, None)


class JsonResponse:
    def __init__(self, payload, headers=None) -> None:
        self.payload = payload
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")


def zotero_item(key: str, *, title: str = "Photon counting LiDAR", version: int = 4):
    return {
        "key": key,
        "version": version,
        "data": {
            "key": key,
            "version": version,
            "itemType": "journalArticle",
            "title": title,
            "abstractNote": "A review.",
            "creators": [{"creatorType": "author", "firstName": "Ada", "lastName": "Li"}],
            "publicationTitle": "Optics Journal",
            "date": "2026",
            "DOI": "10.1000/example",
            "url": "https://example.invalid/paper",
            "dateAdded": "2026-08-20T08:00:00Z",
            "dateModified": "2026-08-21T08:00:00Z",
            "tags": [{"tag": "LiDAR"}],
            "collections": ["COLL1234"],
        },
    }


def test_v6_source_table_upgrades_to_current_without_losing_source(tmp_path: Path) -> None:
    db_path = tmp_path / "v6.db"
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE research_sources (
                id TEXT PRIMARY KEY, provider TEXT NOT NULL, library_type TEXT NOT NULL,
                library_id TEXT NOT NULL, display_name TEXT NOT NULL, enabled INTEGER NOT NULL,
                sync_cursor TEXT, last_synced_at TEXT, last_sync_status TEXT NOT NULL,
                last_sync_error TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(provider,library_type,library_id)
            )
            """
        )
        connection.execute(
            """INSERT INTO research_sources VALUES
               ('old','zotero','user','','旧文库',1,'9',NULL,'ok','',
                '2026-08-20','2026-08-20')"""
        )
        connection.execute("PRAGMA user_version = 6")
        connection.commit()

    init_db(db_path)
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(research_sources)")}
        assert {"access_mode", "base_url", "server_id", "auto_sync"} <= columns
        assert connection.execute("SELECT sync_cursor FROM research_sources").fetchone()[0] == "9"
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert connection.execute(
            "SELECT COUNT(*) FROM research_sync_runs"
        ).fetchone()[0] == 0


def test_local_connection_and_incremental_sync_are_idempotent(tmp_path: Path) -> None:
    calls: list[str] = []

    def transport(request, timeout):
        calls.append(request.full_url)
        headers = {"Zotero-Server-ID": "LOCAL-1", "Last-Modified-Version": "12"}
        if "/deleted?" in request.full_url:
            return JsonResponse({"items": []}, headers)
        return JsonResponse([zotero_item("ABCD1234")], headers)

    service = ZoteroService(
        tmp_path / "local.db",
        credential_store=MemoryZoteroCredentials(),
        environment={},
        transport=transport,
    )
    source = service.save_connection(
        {"display_name": "本机 Zotero", "access_mode": "local", "library_type": "user"}
    )
    service.repository.update_source_sync(
        source["id"],
        cursor=None,
        server_id=None,
        status="error",
        error="Zotero 连接失败（HTTP 404）",
        synced_at=None,
        updated_at="2026-08-26T00:00:00Z",
    )
    tested = service.test_connection(source["id"])
    assert tested["server_id"] == "LOCAL-1"
    refreshed = service.repository.get_source(source["id"])
    assert refreshed["last_sync_status"] == "never"
    assert refreshed["last_sync_error"] == ""
    assert all(not url.endswith("/api/") for url in calls)
    assert calls[0].endswith("/api/users/0/items/top?limit=1&format=json")
    first = service.sync(source["id"])
    second = service.sync(source["id"])

    assert first["cursor_before"] == "0" and first["cursor_after"] == "12"
    assert second["cursor_before"] == "12"
    assert not any("/deleted?" in url for url in calls)
    assert not any("since=" in url for url in calls)
    research = ResearchService(tmp_path / "local.db")
    assert len(research.list_items()) == 1
    assert len(research.list_inbox()) == 1
    item = research.list_items()[0]
    assert item["metadata"]["tags"] == [{"tag": "LiDAR"}]


def test_sync_applies_remote_deletions_and_keeps_cursor_on_failure(tmp_path: Path) -> None:
    state = {"fail": False, "deleted": False}

    def transport(request, timeout):
        if state["fail"]:
            raise URLError("offline")
        headers = {"Zotero-Server-ID": "LOCAL-2", "Last-Modified-Version": "8"}
        return JsonResponse(
            [] if state["deleted"] else [zotero_item("DEAD1234")], headers
        )

    db_path = tmp_path / "deleted.db"
    service = ZoteroService(
        db_path,
        credential_store=MemoryZoteroCredentials(),
        environment={},
        transport=transport,
    )
    source = service.save_connection({"display_name": "本机", "access_mode": "local"})
    assert service.sync(source["id"])["imported_count"] == 1
    state["deleted"] = True
    result = service.sync(source["id"])
    assert result["deleted_count"] == 1
    assert ResearchService(db_path).list_items() == []

    state["fail"] = True
    with pytest.raises(ValueError, match="无法连接本机 Zotero"):
        service.sync(source["id"])
    saved = service.repository.get_source(source["id"])
    assert saved["sync_cursor"] == "8"
    assert saved["last_sync_status"] == "error"


def test_web_key_is_header_only_and_never_exported(tmp_path: Path) -> None:
    credentials = MemoryZoteroCredentials()
    seen = []

    def transport(request, timeout):
        seen.append((request.full_url, request.get_header("Zotero-api-key")))
        return JsonResponse([], {"Last-Modified-Version": "3"})

    db_path = tmp_path / "web.db"
    service = ZoteroService(
        db_path, credential_store=credentials, environment={}, transport=transport
    )
    secret = "zotero-secret-key-1234"
    source = service.save_connection(
        {
            "display_name": "Zotero Web",
            "access_mode": "web",
            "library_type": "user",
            "library_id": "98765",
            "api_key": secret,
        }
    )
    assert source["configured"] is True and secret not in json.dumps(source)
    service.test_connection(source["id"])
    assert seen[0][0].startswith("https://api.zotero.org/users/98765/items/top")
    assert seen[0][1] == secret
    assert secret not in json.dumps(ResearchService(db_path).export_backup())
    with sqlite3.connect(db_path) as connection:
        assert secret not in "".join(str(row) for row in connection.iterdump())


def test_server_identity_change_is_rejected_before_writing(tmp_path: Path) -> None:
    def transport(request, timeout):
        return JsonResponse(
            [zotero_item("NEWK1234")],
            {"Zotero-Server-ID": "OTHER", "Last-Modified-Version": "2"},
        )

    db_path = tmp_path / "identity.db"
    service = ZoteroService(
        db_path,
        credential_store=MemoryZoteroCredentials(),
        environment={},
        transport=transport,
    )
    source = service.save_connection(
        {"display_name": "本机", "access_mode": "local", "server_id": "EXPECTED"}
    )
    with pytest.raises(ValueError, match="另一套 Zotero 数据库"):
        service.sync(source["id"])
    assert ResearchService(db_path).list_items() == []


def test_inbox_task_preview_confirm_is_validated_atomic_and_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "convert.db"
    research = ResearchService(db_path)
    source = research.save_source({"display_name": "Zotero", "access_mode": "local"})
    item = research.save_item(
        {
            "source_id": source["id"],
            "external_key": "READ1234",
            "title": "A paper to read",
            "publication_title": "Journal",
            "published_at": "2026",
        }
    )
    preview = research.preview_task(item["id"], {"estimated_minutes": 90})
    assert preview["task"]["title"] == "阅读：A paper to read"
    assert preview["task"]["estimated_minutes"] == 90
    with pytest.raises(ValueError, match="开始日期"):
        research.confirm_task(
            item["id"],
            {"task": {**preview["task"], "start_date": "2026-09-02", "due_date": "2026-09-01"}},
        )
    assert research.tasks.count() == 0

    first = research.confirm_task(item["id"], {"task": preview["task"]})
    second = research.confirm_task(item["id"], {"task": preview["task"]})
    assert first["created"] is True and second["created"] is False
    assert first["task"]["id"] == second["task"]["id"]
    assert research.tasks.count() == 1
    assert research.list_task_items(first["task"]["id"])[0]["relation_type"] == "reading"


def test_inbox_task_preview_and_confirm_api(tmp_path: Path) -> None:
    db_path = tmp_path / "api.db"
    research = ResearchService(db_path)
    source = research.save_source({"display_name": "Zotero", "access_mode": "local"})
    item = research.save_item(
        {"source_id": source["id"], "external_key": "APIK1234", "title": "API paper"}
    )
    client = create_app(db_path).test_client()
    preview = client.post(
        f"/api/research/inbox/{item['id']}/task-preview",
        json={"estimated_minutes": 45, "due_date": "2026-09-01"},
    )
    assert preview.status_code == 200
    task = preview.get_json()["preview"]["task"]
    confirmed = client.post(
        f"/api/research/inbox/{item['id']}/task-confirm", json={"task": task}
    )
    assert confirmed.status_code == 201
    assert confirmed.get_json()["created"] is True
    assert client.get("/api/research/inbox").get_json()["items"] == []


def test_v7_database_adds_project_paper_links_idempotently(tmp_path: Path) -> None:
    db_path = tmp_path / "v7.db"
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE project_research_items")
        connection.execute("PRAGMA user_version = 7")
        connection.commit()

    init_db(db_path)
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert connection.execute(
            "SELECT COUNT(*) FROM project_research_items"
        ).fetchone()[0] == 0


def test_collection_preview_search_and_project_import_are_idempotent(tmp_path: Path) -> None:
    calls: list[str] = []
    papers = [
        zotero_item("PAPER001", title="Photon counting review"),
        zotero_item("PAPER002", title="SPAD imaging"),
    ]

    def transport(request, timeout):
        calls.append(request.full_url)
        headers = {"Zotero-Server-ID": "LOCAL-PROJECT", "Last-Modified-Version": "20"}
        url = request.full_url
        if "/collections?" in url:
            return JsonResponse(
                [
                    {"key": "ROOT1234", "data": {"key": "ROOT1234", "name": "激光雷达", "parentCollection": False}},
                    {"key": "CHILD123", "data": {"key": "CHILD123", "name": "SPAD", "parentCollection": "ROOT1234"}},
                ],
                headers,
            )
        if "/collections/ROOT1234/items/top?" in url:
            return JsonResponse([papers[0]], headers)
        if "/collections/CHILD123/items/top?" in url:
            return JsonResponse(papers, headers)
        if "itemKey=" in url:
            return JsonResponse(papers, headers)
        if "q=SPAD" in url:
            return JsonResponse([papers[1]], headers)
        return JsonResponse([], headers)

    db_path = tmp_path / "project-import.db"
    service = ZoteroService(
        db_path,
        credential_store=MemoryZoteroCredentials(),
        environment={},
        transport=transport,
    )
    source = service.save_connection({"display_name": "本机", "access_mode": "local"})
    client = create_app(db_path, zotero_service=service).test_client()
    project = client.post(
        "/api/projects", json={"name": "单光子激光雷达", "category": "科研"}
    ).get_json()["project"]

    collections = client.get(
        f"/api/research/sources/{source['id']}/collections"
    ).get_json()["collections"]
    assert [item["path"] for item in collections] == ["激光雷达", "激光雷达 / SPAD"]

    preview_response = client.post(
        f"/api/research/sources/{source['id']}/project-import-preview",
        json={"mode": "collection", "collection_key": "ROOT1234", "include_subcollections": True},
    )
    assert preview_response.status_code == 200
    preview = preview_response.get_json()["preview"]
    assert {item["external_key"] for item in preview["items"]} == {"PAPER001", "PAPER002"}
    assert ResearchService(db_path).list_items() == []

    searched = client.post(
        f"/api/research/sources/{source['id']}/project-import-preview",
        json={"mode": "search", "query": "SPAD"},
    ).get_json()["preview"]
    assert [item["external_key"] for item in searched["items"]] == ["PAPER002"]

    payload = {
        "source_id": source["id"],
        "mode": "collection",
        "collection_key": "ROOT1234",
        "item_keys": ["PAPER001", "PAPER002"],
    }
    first = client.post(f"/api/research/projects/{project['id']}/imports", json=payload)
    second = client.post(f"/api/research/projects/{project['id']}/imports", json=payload)
    assert first.status_code == 201 and first.get_json()["imported_count"] == 2
    assert second.get_json()["imported_count"] == 0
    assert second.get_json()["existing_count"] == 2
    linked = client.get(
        f"/api/research/projects/{project['id']}/items"
    ).get_json()["items"]
    assert {item["external_key"] for item in linked} == {"PAPER001", "PAPER002"}
    assert client.get("/api/research/inbox").get_json()["items"] == []
    assert any("q=SPAD" in url for url in calls)


def test_project_import_rejects_non_research_project(tmp_path: Path) -> None:
    db_path = tmp_path / "wrong-project.db"
    research = ResearchService(db_path)
    source = research.save_source({"display_name": "Zotero", "access_mode": "local"})
    item = research.save_item(
        {"source_id": source["id"], "external_key": "COURSE01", "title": "Course paper", "add_to_inbox": False}
    )
    client = create_app(db_path).test_client()
    project = client.post(
        "/api/projects", json={"name": "课程报告", "category": "课程"}
    ).get_json()["project"]
    response = client.get(f"/api/research/projects/{project['id']}/items")
    assert response.status_code == 400
    with pytest.raises(ValueError, match="科研类型"):
        research.link_project_items(project["id"], [item["id"]])
