from __future__ import annotations

from pathlib import Path

from yantu.main import create_app
from yantu.services.research_service import ResearchService


def _catalogue(client, db_path: Path):
    project = client.post(
        "/api/projects", json={"name": "单光子研究", "category": "科研"}
    ).get_json()["project"]
    research = ResearchService(db_path)
    source = research.save_source({"display_name": "本机 Zotero", "access_mode": "local"})
    paper = research.save_item({
        "source_id": source["id"], "external_key": "READ001",
        "title": "Photon counting review", "add_to_inbox": True,
    })
    research.link_project_items(project["id"], [paper["id"]])
    return project, paper


def test_quick_and_regular_reading_tasks_share_paper_history(tmp_path: Path) -> None:
    db_path = tmp_path / "reading.db"
    client = create_app(db_path).test_client()
    project, paper = _catalogue(client, db_path)
    assert len(client.get("/api/research/inbox").get_json()["items"]) == 1

    quick = client.post(f"/api/research/items/{paper['id']}/quick-task", json={})
    assert quick.status_code == 201
    quick_task = quick.get_json()["task"]
    assert quick_task["title"] == "阅读：Photon counting review"
    assert quick_task["estimated_minutes"] == 60
    assert quick_task["estimated_hours"] == 1
    assert client.get("/api/research/inbox").get_json()["items"] == []

    regular = client.post("/api/tasks", json={
        "title": "复盘 Photon counting review", "domain": "research",
        "estimated_minutes": 30, "research_item_id": paper["id"],
    })
    assert regular.status_code == 201
    review_task = regular.get_json()["task"]
    client.patch(f"/api/tasks/{review_task['id']}", json={"progress": 40})

    papers = client.get(f"/api/research/projects/{project['id']}/items").get_json()["items"]
    history = papers[0]["reading_history"]
    assert {entry["task_id"] for entry in history} == {quick_task["id"], review_task["id"]}
    assert next(entry for entry in history if entry["task_id"] == review_task["id"])["progress"] == 40
    invalid = client.post("/api/tasks", json={
        "title": "找不到论文", "domain": "research", "research_item_id": "missing",
    })
    assert invalid.status_code == 400
    assert len(client.get("/api/tasks").get_json()["tasks"]) == 2


def test_manual_nested_folders_and_backup_restore(tmp_path: Path) -> None:
    first_db = tmp_path / "folders.db"
    client = create_app(first_db).test_client()
    project, paper = _catalogue(client, first_db)
    root = client.post(f"/api/research/projects/{project['id']}/folders",
                       json={"name": "综述"}).get_json()["folder"]
    renamed = client.put(f"/api/research/projects/{project['id']}/folders/{root['id']}",
                         json={"name": "理论综述"})
    assert renamed.status_code == 200 and renamed.get_json()["folder"]["name"] == "理论综述"
    renamed = client.put(f"/api/research/projects/{project['id']}/folders/{root['id']}",
                         json={"name": "理论综述"})
    assert renamed.status_code == 200 and renamed.get_json()["folder"]["name"] == "理论综述"
    child = client.post(f"/api/research/projects/{project['id']}/folders",
                        json={"name": "探测器", "parent_id": root["id"]}).get_json()["folder"]
    added = client.post(
        f"/api/research/projects/{project['id']}/folders/{child['id']}/items/{paper['id']}"
    )
    assert added.status_code == 204
    papers = client.get(f"/api/research/projects/{project['id']}/items").get_json()["items"]
    assert papers[0]["folder_ids"] == [child["id"]]

    backup = client.get("/api/export").get_json()
    assert backup["version"] == 13 and len(backup["research"]["folders"]) == 2
    restored = create_app(tmp_path / "restored.db").test_client()
    assert restored.post("/api/import", json=backup).status_code == 200
    assert restored.post("/api/import", json=backup).status_code == 200
    folders = restored.get(f"/api/research/projects/{project['id']}/folders").get_json()["folders"]
    assert {folder["id"] for folder in folders} == {root["id"], child["id"]}
    assert next(folder for folder in folders if folder["id"] == root["id"])["name"] == "理论综述"
    assert next(folder for folder in folders if folder["id"] == root["id"])["name"] == "理论综述"
    papers = restored.get(f"/api/research/projects/{project['id']}/items").get_json()["items"]
    assert papers[0]["folder_ids"] == [child["id"]]
