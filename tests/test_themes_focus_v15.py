from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from yantu.database.repository import database, init_db
from yantu.main import create_app
from yantu.services.focus_analytics_service import FocusAnalyticsService
from yantu.services.focus_service import FocusService
from yantu.services.task_service import TaskService


def test_theme_migration_and_hierarchy_api(tmp_path: Path) -> None:
    db = tmp_path / "theme.db"
    client = create_app(db).test_client()
    page = client.get("/").get_data(as_text=True)
    assert "长期主题" in page and 'id="task-parent"' in page
    old = client.post("/api/tasks", json={"title": "已有任务", "domain": "research",
                                          "estimated_minutes": 90, "due_date": "2026-11-01"})
    assert old.status_code == 201
    with database(db) as connection:
        connection.execute("PRAGMA user_version = 14")
    init_db(db)
    init_db(db)
    with database(db) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 15
        assert connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert client.get(f"/api/tasks/{old.get_json()['task']['id']}").get_json()["task"]["is_theme"] is False

    theme = client.post("/api/tasks", json={"title": "单光子雷达课题", "domain": "research",
                                            "is_theme": True, "estimated_minutes": 0})
    assert theme.status_code == 201
    theme_id = theme.get_json()["task"]["id"]
    child = client.post("/api/tasks", json={"title": "阅读 SPAD 论文", "domain": "research",
                                            "parent_id": theme_id, "task_kind": "free_learning"})
    assert child.status_code == 201
    child_id = child.get_json()["task"]["id"]
    assert child.get_json()["task"]["parent_task_id"] == theme_id
    assert client.delete(f"/api/tasks/{theme_id}").status_code == 400
    assert client.post("/api/tasks", json={"title": "非法主题", "domain": "research",
                                            "is_theme": True, "due_date": "2026-11-01"}).status_code == 400
    assert client.post("/api/tasks", json={"title": "跨领域子任务", "domain": "personal",
                                            "parent_id": theme_id}).status_code == 400
    assert client.patch(f"/api/tasks/{theme_id}", json={"parent_id": child_id}).status_code == 400
    assert client.patch(f"/api/tasks/{child_id}", json={"parent_id": None}).status_code == 200
    assert client.get(f"/api/tasks/{child_id}").get_json()["task"]["parent_task_id"] is None
    converted = client.patch(f"/api/tasks/{old.get_json()['task']['id']}", json={
        "is_theme": True, "estimated_minutes": 0, "due_date": None,
    })
    assert converted.status_code == 200
    assert converted.get_json()["task"]["is_theme"] is True
    assert client.patch(f"/api/tasks/{child_id}", json={"parent_id": theme_id}).status_code == 200
    backup = client.get("/api/export").get_json()
    assert backup["version"] == 15
    backup["tasks"] = list(reversed(backup["tasks"]))
    restored = create_app(tmp_path / "restored.db").test_client()
    assert restored.post("/api/import", json=backup).status_code == 200
    restored_child = restored.get(f"/api/tasks/{child_id}").get_json()["task"]
    assert restored_child["parent_task_id"] == theme_id
    assert restored.get(f"/api/tasks/{theme_id}").get_json()["task"]["is_theme"] is True


def test_theme_exploration_and_program_review(tmp_path: Path) -> None:
    db = tmp_path / "review.db"
    tasks = TaskService(db)
    now = "2026-08-20T08:00:00+00:00"
    theme = tasks.create_record({"id": "theme", "title": "大横向", "domain": "research",
                                 "task_kind": "standard", "schedule_mode": "flexible", "is_theme": 1,
                                 "created_at": now, "updated_at": now})
    tasks.create_record({"id": "explore", "title": "探索方案", "domain": "research",
                         "parent_id": theme["id"], "task_kind": "free_learning",
                         "created_at": now, "updated_at": now})
    clock = [datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)]
    focus = FocusService(db, now=lambda: clock[0])
    try:
        focus.start({"task_id": "theme", "mode": "free", "monitor_apps": False})
        assert False, "长期主题不应直接进入计时"
    except ValueError:
        pass
    session = focus.start({"task_id": "explore", "mode": "free", "monitor_apps": False})
    assert session["target_seconds"] == 0
    clock[0] += timedelta(seconds=120)
    focus.complete(session["id"])
    with database(db) as connection:
        connection.execute("""
            INSERT INTO focus_app_usage
              (session_id, process_name, is_allowed, active_seconds, idle_seconds,
               sample_count, first_seen_at, last_seen_at)
            VALUES (?, 'code.exe', 1, 60, 30, 3, ?, ?),
                   (?, 'zotero.exe', 1, 10, 20, 2, ?, ?)
        """, (session["id"], now, now, session["id"], now, now))
    report = FocusAnalyticsService(db).report(start="2026-08-20", end="2026-08-20",
                                              theme_id="theme", task_id="explore")
    assert report["summary"]["seconds"] == 120
    assert report["by_theme"] == [{"id": "theme", "name": "大横向", "seconds": 120}]
    assert report["by_subtask"] == [{"id": "explore", "name": "探索方案", "seconds": 120}]
    assert report["apps"] == [
        {"process_name": "code.exe", "active_seconds": 60, "idle_seconds": 30, "total_seconds": 90},
        {"process_name": "zotero.exe", "active_seconds": 10, "idle_seconds": 20, "total_seconds": 30},
    ]
    assert report["app_coverage"] == {"monitored_sessions": 1, "total_sessions": 1,
                                      "sampled_seconds": 120, "unmonitored_seconds": 0}
    client = create_app(db).test_client()
    scoped = client.get("/api/focus/analytics?start=2026-08-20&end=2026-08-20&theme_id=theme&task_id=explore")
    assert scoped.status_code == 200
    assert scoped.get_json()["analytics"]["apps"][0]["process_name"] == "code.exe"
    assert client.get("/api/focus/analytics?theme_id=missing").status_code == 400
    assert FocusAnalyticsService(db).report(start="2026-08-20", end="2026-08-20",
                                           task_id="theme")["summary"]["seconds"] == 0
