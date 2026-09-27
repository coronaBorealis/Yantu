from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from yantu.main import create_app
from yantu.services.focus_service import FocusService
from yantu.services.research_service import ResearchService
from yantu.services.settings_service import SettingsService
from yantu.services.task_service import TaskService


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def paper(client, db_path: Path) -> dict:
    research = ResearchService(db_path)
    source = research.save_source({"display_name": "Zotero", "access_mode": "local"})
    return research.save_item({"source_id": source["id"], "external_key": "SLOW001",
                               "title": "Slow paper", "add_to_inbox": True})


def test_quick_reading_resumes_same_free_learning_task_and_extends(tmp_path: Path) -> None:
    db_path = tmp_path / "reading.db"
    client = create_app(db_path).test_client()
    item = paper(client, db_path)
    first = client.post(f"/api/research/items/{item['id']}/quick-task", json={})
    assert first.status_code == 201
    task = first.get_json()["task"]
    assert task["task_kind"] == "free_learning"
    assert task["due_date"] is None and task["estimated_minutes"] == 60
    assert first.get_json()["reused"] is False

    clock = Clock()
    settings = SettingsService(db_path, environment={})
    settings.update_preferences({"auto_start_break": False})
    focus = FocusService(db_path, now=clock, settings=settings)
    session = focus.start({"task_id": task["id"], "mode": "pomodoro",
                           "target_seconds": 3600, "monitor_apps": False})
    clock.advance(3600)
    running = focus.active()
    assert running is not None and running["status"] == "running"
    assert running["target_seconds"] == 7200
    assert TaskService(db_path).get_record(task["id"])["estimated_minutes"] == 120
    clock.advance(1800)
    focus.complete(session["id"])
    recorded = TaskService(db_path).get_record(task["id"])
    assert recorded["actual_minutes"] == 90 and recorded["estimated_minutes"] == 120
    assert recorded["progress"] == 0

    again = client.post(f"/api/research/items/{item['id']}/quick-task", json={})
    assert again.status_code == 200 and again.get_json()["reused"] is True
    assert again.get_json()["task"]["id"] == task["id"]
    assert len(client.get("/api/tasks").get_json()["tasks"]) == 1
    continuation = focus.start({"task_id": task["id"], "mode": "pomodoro",
                                "target_seconds": 1800, "monitor_apps": False})
    clock.advance(1800)
    assert focus.active()["target_seconds"] == 5400
    assert TaskService(db_path).get_record(task["id"])["estimated_minutes"] == 180
    clock.advance(1800)
    focus.complete(continuation["id"])
    assert TaskService(db_path).get_record(task["id"])["actual_minutes"] == 150


def test_free_learning_is_distinct_from_deadline_work_and_survives_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "tasks.db"
    client = create_app(db_path).test_client()
    invalid = client.post("/api/tasks", json={"title": "随时读书", "task_kind": "free_learning",
                                              "due_date": "2026-09-20"})
    assert invalid.status_code == 400
    created = client.post("/api/tasks", json={"title": "随时读书", "domain": "research",
                                              "task_kind": "free_learning", "estimated_minutes": 60,
                                              "start_date": "2026-09-16"})
    assert created.status_code == 201
    task = created.get_json()["task"]
    assert task["task_kind"] == "free_learning"
    assert not TaskService(db_path).daily_plan("2026-09-16")["allocations"]
    assert client.patch(f"/api/tasks/{task['id']}", json={"due_date": "2026-09-20"}).status_code == 400
    assert client.get("/focus-analytics.js").status_code == 200

    backup = client.get("/api/export").get_json()
    assert backup["version"] == 13
    restored = create_app(tmp_path / "restored.db").test_client()
    assert restored.post("/api/import", json=backup).status_code == 200
    assert restored.get(f"/api/tasks/{task['id']}").get_json()["task"]["task_kind"] == "free_learning"


def test_old_default_quick_reading_path_is_reused_on_first_continue(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    client = create_app(db_path).test_client()
    item = paper(client, db_path)
    old = client.post("/api/tasks", json={"title": "阅读：Slow paper", "domain": "research",
                                          "estimated_minutes": 60, "research_item_id": item["id"]})
    assert old.status_code == 201
    old_task = old.get_json()["task"]
    assert old_task["task_kind"] == "standard"
    continuation = client.post(f"/api/research/items/{item['id']}/quick-task", json={})
    assert continuation.status_code == 200
    assert continuation.get_json()["task"]["id"] == old_task["id"]
    assert continuation.get_json()["task"]["task_kind"] == "free_learning"


def test_custom_legacy_reading_can_be_continued_explicitly(tmp_path: Path) -> None:
    db_path = tmp_path / "custom.db"
    client = create_app(db_path).test_client()
    item = paper(client, db_path)
    custom = client.post("/api/tasks", json={"title": "细读实验方法", "domain": "research",
                                             "estimated_minutes": 60, "research_item_id": item["id"]}).get_json()["task"]
    assert client.post(f"/api/research/items/{item['id']}/quick-task",
                       json={"resume_task_id": "missing"}).status_code == 400
    resumed = client.post(f"/api/research/items/{item['id']}/quick-task",
                          json={"resume_task_id": custom["id"]})
    assert resumed.status_code == 200
    assert resumed.get_json()["task"]["id"] == custom["id"]
    assert resumed.get_json()["task"]["task_kind"] == "free_learning"
    assert len(client.get("/api/tasks").get_json()["tasks"]) == 1
