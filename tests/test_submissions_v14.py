from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from yantu.database.repository import init_db
from yantu.main import create_app


def _semester(client):
    response = client.post("/api/semesters", json={
        "name": "秋季学期", "start_date": "2026-09-21", "end_date": "2026-10-11"
    })
    assert response.status_code == 201
    return response.get_json()["semester"]


def _course(client, semester_id):
    response = client.post("/api/courses", json={
        "semester_id": semester_id, "name": "数值分析",
        "meetings": [{"weekday": 1, "start_period": 1, "end_period": 2,
                      "start_time": "08:00", "end_time": "09:35",
                      "start_week": 1, "end_week": 2}],
    })
    assert response.status_code == 201
    return response.get_json()["course"]


def test_course_submission_belongs_to_one_occurrence_and_survives_course_edit(tmp_path: Path):
    client = create_app(tmp_path / "course.db").test_client()
    course = _course(client, _semester(client)["id"])
    meeting = course["meetings"][0]
    url = f"/api/course-meetings/{meeting['id']}/submissions/2026-09-21"
    assert client.put(url, json={"material": "习题三", "submitted": False}).status_code == 200
    events = client.get("/api/calendar/events?start=2026-09-21&end=2026-09-28").get_json()["events"]
    assert events[0]["submission"]["material"] == "习题三"
    assert events[1]["submission"] is None
    assert client.put(url.replace("09-21", "09-22"), json={"material": "错误日期"}).status_code == 400

    update = client.put(f"/api/courses/{course['id']}", json={
        "name": "数值分析（二）", "meetings": course["meetings"]
    })
    assert update.status_code == 200
    events = client.get("/api/calendar/events?start=2026-09-21&end=2026-09-21").get_json()["events"]
    assert events[0]["submission"]["material"] == "习题三"
    submitted = client.put(url, json={"material": "习题三", "submitted": True}).get_json()["submission"]
    assert submitted["completed_at"]
    assert client.delete(url).status_code == 204
    assert client.get("/api/calendar/events?start=2026-09-21&end=2026-09-21").get_json()["events"][0]["submission"] is None


def test_task_submission_and_elapsed_time_block_are_distinct_from_completion(tmp_path: Path):
    client = create_app(tmp_path / "task.db").test_client()
    yesterday = datetime.now(ZoneInfo("Asia/Shanghai")).date() - timedelta(days=1)
    response = client.post("/api/tasks", json={
        "title": "交个人材料", "domain": "personal", "schedule_mode": "time_block",
        "scheduled_date": yesterday.isoformat(), "scheduled_start_time": "09:00",
        "scheduled_end_time": "10:00", "submission_required": True,
        "submission_material": "申请表",
    })
    assert response.status_code == 201
    task = response.get_json()["task"]
    assert task["status"] == "not_started"
    assert task["temporal_state"] == "overdue"
    assert task["submission_required"] is True
    events = client.get(f"/api/calendar/events?start={yesterday}&end={yesterday}").get_json()["events"]
    assert events[0]["submission_material"] == "申请表"
    changed = client.patch(f"/api/tasks/{task['id']}", json={"submission_submitted": True}).get_json()["task"]
    assert changed["submission_completed_at"]
    assert changed["status"] == "not_started"
    removed = client.patch(f"/api/tasks/{task['id']}", json={"submission_required": False}).get_json()["task"]
    assert removed["submission_material"] == ""
    assert removed["submission_completed_at"] is None


def test_v14_migration_is_idempotent_and_backup_keeps_submissions(tmp_path: Path):
    path = tmp_path / "source.db"
    client = create_app(path).test_client()
    course = _course(client, _semester(client)["id"])
    meeting_id = course["meetings"][0]["id"]
    client.put(f"/api/course-meetings/{meeting_id}/submissions/2026-09-21",
               json={"material": "报告", "submitted": False})
    task = client.post("/api/tasks", json={"title": "交资料", "submission_required": True,
                                                 "submission_material": "附件"}).get_json()["task"]
    init_db(path)
    init_db(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 15
        assert connection.execute("SELECT COUNT(*) FROM course_submissions").fetchone()[0] == 1
    backup = client.get("/api/export").get_json()
    assert backup["version"] == 15
    assert backup["course_submissions"][0]["material"] == "报告"
    assert next(item for item in backup["tasks"] if item["id"] == task["id"])["submission_material"] == "附件"
    restored = create_app(tmp_path / "restored.db").test_client()
    assert restored.post("/api/import", json=backup).status_code == 200
    events = restored.get("/api/calendar/events?start=2026-09-21&end=2026-09-21").get_json()["events"]
    assert events[0]["submission"]["material"] == "报告"


def test_v13_database_adds_submission_columns_without_losing_tasks(tmp_path: Path):
    path = tmp_path / "upgrade.db"
    client = create_app(path).test_client()
    task = client.post("/api/tasks", json={"title": "原有个人任务", "domain": "personal"}).get_json()["task"]
    with sqlite3.connect(path) as connection:
        connection.execute("DROP TABLE course_submissions")
        connection.execute("ALTER TABLE tasks DROP COLUMN submission_completed_at")
        connection.execute("ALTER TABLE tasks DROP COLUMN submission_material")
        connection.execute("ALTER TABLE tasks DROP COLUMN submission_required")
        connection.execute("PRAGMA user_version = 13")
    init_db(path)
    init_db(path)
    with sqlite3.connect(path) as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 15
        columns = {row[1] for row in connection.execute("PRAGMA table_info(tasks)")}
        assert {"submission_required", "submission_material", "submission_completed_at"} <= columns
        assert connection.execute("SELECT title FROM tasks WHERE id = ?", (task["id"],)).fetchone()[0] == "原有个人任务"
        assert connection.execute("SELECT submission_required FROM tasks WHERE id = ?", (task["id"],)).fetchone()[0] == 0
