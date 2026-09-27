from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from yantu.main import create_app
from yantu.database.repository import init_db
from yantu.services.activity_probe import ActivityProbe, ActivitySnapshot
from yantu.services.focus_habit_service import FocusHabitService
from yantu.services.focus_service import FocusService


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 30, 9, 0, tzinfo=timezone(timedelta(hours=8)))

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class FakeProbe(ActivityProbe):
    def __init__(self, process_name: str = "code.exe", idle_seconds: float = 0) -> None:
        self.process_name = process_name
        self.idle_seconds = idle_seconds
        self.available = True

    def capability(self) -> dict[str, object]:
        return {
            "available": self.available,
            "platform": "windows",
            "reason": "" if self.available else "测试环境不可用",
        }

    def snapshot(self) -> ActivitySnapshot:
        return ActivitySnapshot(self.process_name, self.idle_seconds)


def add_task(db_path: Path) -> None:
    client = create_app(db_path).test_client()
    response = client.post(
        "/api/tasks",
        json={"id": "ignored", "title": "阅读与编码", "domain": "research", "estimated_minutes": 60},
    )
    task = response.get_json()["task"]
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE tasks SET id = 'habit-task' WHERE id = ?", (task["id"],))
        connection.commit()


def test_v9_migration_adds_habit_tables_and_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "v8.db"
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE focus_app_usage")
        connection.execute("DROP TABLE focus_habit_sessions")
        connection.execute("DROP TABLE focus_habit_profiles")
        connection.execute("PRAGMA user_version = 8")
        connection.commit()
    init_db(db_path)
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert {"focus_habit_profiles", "focus_habit_sessions", "focus_app_usage"} <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 13


def test_habit_sampling_separates_allowed_idle_and_distraction(tmp_path: Path) -> None:
    db_path = tmp_path / "habit.db"
    add_task(db_path)
    clock = Clock()
    probe = FakeProbe()
    habits = FocusHabitService(db_path, probe=probe, now=clock)
    profile = habits.save_profile({
        "name": "代码深潜",
        "allowed_apps": ["code.exe", "chrome.exe"],
        "idle_threshold_seconds": 60,
        "switch_warning_count": 4,
    })
    focus = FocusService(db_path, now=clock, habits=habits)
    session = focus.start({
        "task_id": "habit-task", "mode": "free", "target_seconds": 0,
        "habit_profile_id": profile["id"],
    })

    clock.advance(5)
    habits.sample_session(session["id"])
    probe.idle_seconds = 90
    clock.advance(5)
    habits.sample_session(session["id"])
    probe.process_name = "chat.exe"
    probe.idle_seconds = 0
    clock.advance(5)
    habits.sample_session(session["id"])

    focus.pause(session["id"])
    clock.advance(20)
    habits.sample_session(session["id"])
    focus.resume(session["id"])
    probe.process_name = "code.exe"
    clock.advance(5)
    result = focus.complete(session["id"])["habit_result"]

    assert result["active_seconds"] == 10
    assert result["idle_seconds"] == 5
    assert result["distraction_seconds"] == 5
    assert result["switch_count"] == 2
    assert result["violation_count"] == 1
    assert result["quality_score"] == 50
    apps = {item["process_name"]: item for item in result["apps"]}
    assert set(apps) == {"code.exe", "chat.exe"}
    assert apps["code.exe"]["active_seconds"] == 10
    assert apps["code.exe"]["idle_seconds"] == 5
    assert apps["chat.exe"]["active_seconds"] == 5
    assert apps["chat.exe"]["is_allowed"] is False
    serialized = json.dumps(result, ensure_ascii=False).lower()
    for forbidden in ("keystroke", "window_title", "mouse_position", "screenshot", "url"):
        assert forbidden not in serialized
    stats = habits.stats(start="2026-08-30", end="2026-08-30")
    assert stats["completed_sessions"] == 1
    assert stats["active_seconds"] == 10
    assert stats["quality_score"] == 50
    assert stats["study_days"] == 1 and stats["current_streak_days"] == 1


def test_default_tracking_records_active_and_idle_time_per_application(tmp_path: Path) -> None:
    db_path = tmp_path / "default-tracking.db"
    add_task(db_path)
    clock = Clock()
    probe = FakeProbe("code.exe")
    habits = FocusHabitService(db_path, probe=probe, now=clock)
    focus = FocusService(db_path, now=clock, habits=habits)

    session = focus.start({"task_id": "habit-task", "mode": "free", "target_seconds": 0})
    assert session["habit"]["profile_id"] is None
    assert session["habit"]["profile_name"] == "基础前台应用记录"

    clock.advance(5)
    habits.sample_session(session["id"])
    probe.process_name = "zotero.exe"
    probe.idle_seconds = 90
    clock.advance(5)
    habits.sample_session(session["id"])
    result = focus.complete(session["id"])["habit_result"]

    assert result["active_seconds"] == 5
    assert result["idle_seconds"] == 5
    assert result["distraction_seconds"] == 0
    apps = {item["process_name"]: item for item in result["apps"]}
    assert apps["code.exe"]["active_seconds"] == 5
    assert apps["code.exe"]["idle_seconds"] == 0
    assert apps["zotero.exe"]["active_seconds"] == 0
    assert apps["zotero.exe"]["idle_seconds"] == 5
    assert all(item["is_allowed"] for item in apps.values())


def test_default_tracking_can_be_explicitly_disabled(tmp_path: Path) -> None:
    db_path = tmp_path / "tracking-disabled.db"
    add_task(db_path)
    clock = Clock()
    habits = FocusHabitService(db_path, probe=FakeProbe(), now=clock)
    focus = FocusService(db_path, now=clock, habits=habits)

    session = focus.start({
        "task_id": "habit-task",
        "mode": "free",
        "target_seconds": 0,
        "monitor_apps": False,
    })
    assert "habit" not in session
    assert habits.session(session["id"]) is None


def test_unavailable_probe_degrades_without_blocking_focus(tmp_path: Path) -> None:
    db_path = tmp_path / "unavailable.db"
    add_task(db_path)
    clock = Clock()
    probe = FakeProbe()
    probe.available = False
    habits = FocusHabitService(db_path, probe=probe, now=clock)
    profile = habits.save_profile({"name": "阅读", "allowed_apps": ["sumatrapdf.exe"]})
    focus = FocusService(db_path, now=clock, habits=habits)
    session = focus.start({
        "task_id": "habit-task", "mode": "free", "target_seconds": 0,
        "habit_profile_id": profile["id"],
    })
    assert session["habit"]["status"] == "unavailable"
    clock.advance(60)
    completed = focus.complete(session["id"])
    assert completed["session"]["status"] == "completed"
    assert completed["habit_result"]["status"] == "unavailable"


def test_habit_api_profile_lifecycle_and_request_privacy(tmp_path: Path) -> None:
    db_path = tmp_path / "api.db"
    clock = Clock()
    probe = FakeProbe("pycharm64.exe")
    habits = FocusHabitService(db_path, probe=probe, now=clock)
    app = create_app(db_path, focus_habit_service=habits)
    client = app.test_client()
    capability = client.get("/api/focus/habits/capability").get_json()["capability"]
    assert capability["available"]
    assert "按键内容" in capability["privacy"]["never_collects"]
    assert client.get("/api/focus/habits/current-app").get_json()["activity"]["process_name"] == "pycharm64.exe"
    created = client.post("/api/focus/habits", json={
        "name": "开发", "allowed_apps": ["pycharm64.exe"], "idle_threshold_seconds": 45,
    })
    assert created.status_code == 201
    profile = created.get_json()["profile"]
    assert client.get("/api/focus/habits").get_json()["profiles"][0]["id"] == profile["id"]

    task = client.post(
        "/api/tasks",
        json={"title": "轮询采样", "domain": "research", "estimated_minutes": 30},
    ).get_json()["task"]
    focus = client.post("/api/focus/sessions", json={
        "task_id": task["id"], "mode": "free", "target_seconds": 0,
        "habit_profile_id": profile["id"],
    }).get_json()["session"]
    clock.advance(5)
    sampled = client.get(f"/api/focus/sessions/{focus['id']}/habit").get_json()["habit"]
    assert sampled["active_seconds"] == 5
    client.post(f"/api/focus/sessions/{focus['id']}/cancel")

    assert client.delete(f"/api/focus/habits/{profile['id']}").status_code == 204
    assert client.get("/api/focus/habits").get_json()["profiles"] == []
    assert client.get("/api/focus/habits/stats").status_code == 200


def test_habit_profile_validation(tmp_path: Path) -> None:
    service = FocusHabitService(tmp_path / "validation.db", probe=FakeProbe())
    with pytest.raises(ValueError, match="1–20"):
        service.save_profile({"name": "空方案", "allowed_apps": []})
    with pytest.raises(ValueError, match="无效"):
        service.save_profile({"name": "危险路径", "allowed_apps": ["C:/secret/file.exe"]})
    with pytest.raises(ValueError, match="15–600"):
        service.save_profile({"name": "过短", "allowed_apps": ["code.exe"], "idle_threshold_seconds": 3})
