from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from yantu.database.repository import init_db
from yantu.main import create_app
from yantu.services.planning_service import PlanningService
from yantu.services.research_service import ResearchService
from yantu.services.task_service import TaskService


def add_task(service: TaskService, task_id: str, **changes):
    record = {
        "id": task_id,
        "title": "阅读论文",
        "domain": "research",
        "created_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00",
        "estimated_minutes": 240,
        "actual_minutes": 0,
        "priority": "medium",
        "status": "waiting",
        "progress": 0,
    }
    record.update(changes)
    return service.create_record(record)


def test_v5_to_v6_migration_is_idempotent_and_preserves_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "v5.db"
    tasks = TaskService(db_path)
    add_task(tasks, "kept", due_date="2026-08-30")
    with sqlite3.connect(db_path) as connection:
        for table in (
            "research_inbox",
            "task_research_items",
            "research_items",
            "research_sources",
            "task_planning_preferences",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("PRAGMA user_version = 5")
        connection.commit()

    init_db(db_path)
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table'"
            )
        }
        assert {
            "task_planning_preferences",
            "research_sources",
            "research_items",
            "task_research_items",
            "research_inbox",
        } <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 8
        assert connection.execute(
            "SELECT title FROM tasks WHERE id='kept'"
        ).fetchone()[0] == "阅读论文"


def test_waiting_task_without_start_date_rebalances_each_day(tmp_path: Path) -> None:
    service = TaskService(tmp_path / "projection.db")
    add_task(service, "paper", due_date="2026-08-23")
    first = service.daily_plan(
        "2026-08-20", now=datetime(2026, 8, 20, 10, 15, 12, tzinfo=timezone.utc)
    )
    second = service.daily_plan(
        "2026-08-21", now=datetime(2026, 8, 21, 10, 15, 12, tzinfo=timezone.utc)
    )

    assert first["allocations"][0]["planned_minutes"] == 60
    assert second["allocations"][0]["planned_minutes"] == 80
    assert first["refresh"]["minute"]["next_at"] == "2026-08-20T10:16:00+00:00"
    assert first["refresh"]["hour"]["next_at"] == "2026-08-20T11:00:00+00:00"
    assert first["refresh"]["day"]["next_at"] == "2026-08-21T00:00:00+00:00"
    assert first["task_metrics"]["paper"]["remaining_days"] == 4


def test_task_planning_preference_controls_dynamic_projection(tmp_path: Path) -> None:
    db_path = tmp_path / "preference.db"
    tasks = TaskService(db_path)
    add_task(tasks, "limited", due_date="2026-08-20", estimated_minutes=180)
    planning = PlanningService(db_path)
    saved = planning.update_task_preference(
        "limited",
        {
            "planning_mode": "auto",
            "daily_limit_minutes": 45,
            "preferred_weekdays": [4],
            "preferred_session_minutes": 25,
        },
    )
    assert saved["daily_limit_minutes"] == 45
    assert tasks.daily_plan("2026-08-20")["allocations"][0]["planned_minutes"] == 45
    planning.update_task_preference("limited", {"planning_mode": "paused"})
    assert tasks.daily_plan("2026-08-20")["allocations"] == []
    planning.update_task_preference("limited", {"planning_mode": "manual"})
    assert tasks.daily_plan("2026-08-20")["allocations"] == []


def test_confirmed_plan_is_marked_stale_after_actual_time_changes(tmp_path: Path) -> None:
    db_path = tmp_path / "stale.db"
    tasks = TaskService(db_path)
    add_task(tasks, "paper", start_date="2026-08-20", due_date="2026-08-20", estimated_minutes=60)
    planning = PlanningService(db_path)
    planning.update_profile({"workday_start": "09:00", "workday_end": "12:00"})
    preview = planning.preview({"date": "2026-08-20"})
    planning.confirm(preview)
    assert planning.plan_state_for_date("2026-08-20")["plan_state"]["needs_refresh"] is False

    tasks.update_record("paper", {"actual_minutes": 30})
    state = planning.plan_state_for_date("2026-08-20")["plan_state"]
    assert state["needs_refresh"] is True
    assert state["reasons"]


def test_research_items_are_upserted_linked_and_queued_once(tmp_path: Path) -> None:
    db_path = tmp_path / "research.db"
    research = ResearchService(db_path)
    source = research.save_source(
        {
            "library_type": "group",
            "library_id": "12345",
            "display_name": "课题组文库",
        }
    )
    item = research.save_item(
        {
            "source_id": source["id"],
            "external_key": "ABCD1234",
            "title": "Single-photon LiDAR review",
            "creators": [{"name": "Researcher"}],
            "external_version": 1,
        }
    )
    updated = research.save_item(
        {
            "source_id": source["id"],
            "external_key": "ABCD1234",
            "title": "Single-photon LiDAR review (updated)",
            "external_version": 2,
        }
    )
    assert updated["id"] == item["id"]
    assert updated["zotero_uri"] == "zotero://select/groups/12345/items/ABCD1234"
    assert len(research.list_items()) == 1
    assert len(research.list_inbox()) == 1

    tasks = TaskService(db_path)
    add_task(tasks, "read-paper", due_date="2026-08-30")
    research.link_task(
        "read-paper", item["id"], {"relation_type": "reading", "note": "先读方法部分"}
    )
    linked = research.list_task_items("read-paper")
    assert linked[0]["relation_type"] == "reading"
    assert linked[0]["relation_note"] == "先读方法部分"


def test_temporal_and_research_api_contracts(tmp_path: Path) -> None:
    client = create_app(tmp_path / "api.db").test_client()
    task = client.post(
        "/api/tasks",
        json={
            "title": "待规划论文",
            "domain": "research",
            "status": "waiting",
            "due_date": "2026-08-30",
            "estimated_minutes": 120,
        },
    ).get_json()["task"]
    preference = client.put(
        f"/api/planning/tasks/{task['id']}/preference",
        json={"planning_mode": "auto", "daily_limit_minutes": 30},
    )
    assert preference.status_code == 200

    source = client.post(
        "/api/research/sources",
        json={"display_name": "我的 Zotero", "library_type": "user"},
    ).get_json()["source"]
    item_response = client.post(
        "/api/research/items",
        json={
            "source_id": source["id"],
            "external_key": "ZXCV5678",
            "title": "论文 A",
        },
    )
    assert item_response.status_code == 201
    item = item_response.get_json()["item"]
    assert item["zotero_uri"] == "zotero://select/library/items/ZXCV5678"
    linked = client.post(
        f"/api/research/tasks/{task['id']}/items/{item['id']}",
        json={"relation_type": "reference"},
    )
    assert linked.status_code == 201
    assert client.get("/api/research/inbox").get_json()["items"][0]["id"] == item["id"]

    backup = client.get("/api/export").get_json()
    assert backup["version"] == 8
    assert backup["research"]["links"][0]["task_id"] == task["id"]
    restored = create_app(tmp_path / "restored.db").test_client()
    response = restored.post("/api/import", json=backup)
    assert response.status_code == 200
    assert response.get_json()["research_items_imported"] == 1
    assert len(restored.get("/api/research/inbox").get_json()["items"]) == 1
    assert len(
        restored.get(f"/api/research/tasks/{task['id']}/items").get_json()["items"]
    ) == 1
