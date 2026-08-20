from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from yantu.database.repository import init_db
from yantu.main import create_app
from yantu.services.planning_service import PlanningService
from yantu.services.schedule_service import ScheduleService
from yantu.services.task_service import TaskService


def add_task(service: TaskService, task_id: str, minutes: int, priority: str = "medium") -> None:
    service.create_record({
        "id": task_id, "title": task_id, "domain": "research",
        "created_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00",
        "start_date": "2026-08-24", "due_date": "2026-08-24",
        "estimated_minutes": minutes, "actual_minutes": 0,
        "priority": priority, "status": "not_started", "progress": 0,
    })


def test_v4_migration_is_idempotent_and_preserves_tasks(tmp_path: Path) -> None:
    db_path = tmp_path / "planning.db"
    tasks = TaskService(db_path)
    add_task(tasks, "kept", 60)
    init_db(db_path)
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert {"planning_profiles", "planning_runs", "plan_blocks"} <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 4
        assert connection.execute("SELECT title FROM tasks WHERE id='kept'").fetchone()[0] == "kept"
        assert connection.execute("SELECT COUNT(*) FROM planning_profiles").fetchone()[0] == 1


def test_rule_preview_orders_tasks_inserts_breaks_and_avoids_courses(tmp_path: Path) -> None:
    db_path = tmp_path / "preview.db"
    tasks = TaskService(db_path)
    add_task(tasks, "normal", 50, "medium")
    add_task(tasks, "urgent", 75, "urgent")
    schedule = ScheduleService(db_path)
    semester = schedule.save_semester({
        "name": "测试学期", "start_date": "2026-08-24", "end_date": "2026-08-30",
    })
    schedule.create_course({
        "semester_id": semester["id"], "name": "固定课程",
        "meetings": [{
            "weekday": 1, "start_period": 1, "end_period": 2,
            "start_time": "10:00", "end_time": "11:00",
            "start_week": 1, "end_week": 1, "week_pattern": "all",
        }],
    })
    planning = PlanningService(db_path)
    planning.update_profile({"workday_start": "09:00", "workday_end": "14:00", "buffer_minutes": 10})
    preview = planning.preview({"date": "2026-08-24"})

    focus = [block for block in preview["blocks"] if block["block_type"] == "focus"]
    breaks = [block for block in preview["blocks"] if "break" in block["block_type"]]
    assert focus[0]["task_id"] == "urgent"
    assert breaks
    assert preview["fixed_events"][0]["title"] == "固定课程"
    assert all(block["end_time"] <= "09:50" or block["start_time"] >= "11:10" for block in focus)
    assert preview["summary"]["scheduled_focus_minutes"] == 125
    assert preview["summary"]["unscheduled_minutes"] == 0
    assert preview["input_snapshot"]["task_allocations"][0]["task_id"] == "urgent"


def test_long_break_and_non_pomodoro_buffer_are_supported(tmp_path: Path) -> None:
    db_path = tmp_path / "breaks.db"
    tasks = TaskService(db_path)
    add_task(tasks, "deep", 125, "high")
    planning = PlanningService(db_path)
    planning.update_profile({
        "workday_start": "08:00", "workday_end": "14:00",
        "focus_minutes": 25, "long_break_after": 4,
        "long_break_minutes": 15, "buffer_minutes": 7,
    })
    pomodoro = planning.preview({"date": "2026-08-24"})
    assert "long_break" in [block["block_type"] for block in pomodoro["blocks"]]

    planning.update_profile({"use_pomodoro": False})
    free = planning.preview({"date": "2026-08-24"})
    assert "buffer" in [block["block_type"] for block in free["blocks"]]


def test_preview_confirm_and_api_profile_round_trip(tmp_path: Path) -> None:
    db_path = tmp_path / "confirm.db"
    tasks = TaskService(db_path)
    add_task(tasks, "paper", 60, "high")
    client = create_app(db_path).test_client()
    profile = client.put("/api/planning/profile", json={"focus_minutes": 30}).get_json()["profile"]
    assert profile["focus_minutes"] == 30
    preview_response = client.post("/api/planning/preview", json={"date": "2026-08-24"})
    assert preview_response.status_code == 200
    preview = preview_response.get_json()["preview"]
    confirmed = client.post("/api/planning/confirm", json=preview)
    assert confirmed.status_code == 201
    plan = confirmed.get_json()["plan"]
    assert plan["strategy"] == "rule"
    listed = client.get("/api/planning/plans?date=2026-08-24").get_json()["blocks"]
    assert listed and listed[0]["run_id"] == plan["id"]

    backup = client.get("/api/export").get_json()
    assert backup["version"] == 4
    assert backup["planning"]["runs"][0]["blocks"]
    restored_client = create_app(tmp_path / "restored.db").test_client()
    restored = restored_client.post("/api/import", json=backup)
    assert restored.status_code == 200
    assert restored.get_json()["planning_runs_imported"] == 1
    assert restored_client.get("/api/planning/profile").get_json()["profile"]["focus_minutes"] == 30
    assert restored_client.get("/api/planning/plans?date=2026-08-24").get_json()["blocks"]

    invalid = dict(preview)
    invalid["blocks"] = [
        {"task_id": "paper", "block_type": "focus", "start_time": "09:00", "end_time": "10:00"},
        {"task_id": "paper", "block_type": "focus", "start_time": "09:30", "end_time": "10:30"},
    ]
    assert client.post("/api/planning/confirm", json=invalid).status_code == 400


def test_profile_validation(tmp_path: Path) -> None:
    planning = PlanningService(tmp_path / "invalid.db")
    with pytest.raises(ValueError, match="结束时间"):
        planning.update_profile({"workday_start": "18:00", "workday_end": "09:00"})
