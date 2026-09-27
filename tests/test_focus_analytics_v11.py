from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from yantu.database.repository import database, init_db
from yantu.main import create_app
from yantu.services.focus_analytics_service import FocusAnalyticsService
from yantu.services.focus_service import FocusService
from yantu.services.settings_service import SettingsService
from yantu.services.task_service import TaskService


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


def make_task(db_path: Path) -> None:
    TaskService(db_path).create_record({"id": "paper", "title": "旧论文题目", "domain": "research",
                                        "created_at": "2026-08-20T08:00:00+00:00",
                                        "updated_at": "2026-08-20T08:00:00+00:00"})


def test_analytics_uses_only_archived_seconds_and_keeps_task_snapshot(tmp_path: Path) -> None:
    db_path = tmp_path / "focus.db"
    make_task(db_path)
    clock = Clock()
    focus = FocusService(db_path, now=clock)
    first = focus.start({"task_id": "paper", "mode": "free", "target_seconds": 0,
                         "monitor_apps": False})
    clock.advance(60)
    focus.complete(first["id"])
    second = focus.start({"task_id": "paper", "mode": "free", "target_seconds": 0,
                          "monitor_apps": False})
    clock.advance(120)
    focus.cancel(second["id"], record_partial=True)
    third = focus.start({"task_id": "paper", "mode": "free", "target_seconds": 0,
                         "monitor_apps": False})
    clock.advance(90)
    focus.cancel(third["id"], record_partial=False)
    TaskService(db_path).update_record("paper", {"title": "新论文题目"})
    report = FocusAnalyticsService(db_path).report(start="2026-08-20", end="2026-08-20")
    assert report["summary"]["seconds"] == 180
    assert report["summary"]["session_count"] == 2
    assert report["summary"]["partial_sessions"] == 1
    assert report["by_task"] == [{"name": "旧论文题目", "seconds": 180}]
    assert report["daily"] == [{"date": "2026-08-20", "seconds": 180, "sessions": 2}]
    assert report["attention"]["sampled_seconds"] == 0

    history = focus.export_backup()
    target = tmp_path / "restored.db"
    make_task(target)
    assert FocusService(target).import_backup(history) == 3
    restored = FocusAnalyticsService(target).report(start="2026-08-20", end="2026-08-20")
    assert restored["summary"]["seconds"] == 180
    assert restored["by_task"][0]["name"] == "旧论文题目"
    assert FocusService(target).stats(start="2026-08-20", end="2026-08-20")["completed_sessions"] == 2


def test_v11_backfills_finished_focus_and_draft_survives_backup(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy.db"
    make_task(db_path)
    clock = Clock()
    focus = FocusService(db_path, now=clock)
    session = focus.start({"task_id": "paper", "mode": "free", "target_seconds": 0,
                           "monitor_apps": False})
    clock.advance(60)
    focus.complete(session["id"])
    with database(db_path) as connection:
        connection.execute("UPDATE focus_sessions SET archived = 0, task_title_snapshot = NULL")
        connection.execute("PRAGMA user_version = 10")
    init_db(db_path)
    assert FocusAnalyticsService(db_path).report(start="2026-08-20", end="2026-08-20")["summary"]["seconds"] == 60

    settings = SettingsService(db_path, environment={})
    draft = {"taskId": "paper", "preset": "custom", "mode": "pomodoro",
             "minutes": 40, "habitProfileId": "__off__"}
    assert settings.update_focus_draft(draft) == draft
    target = tmp_path / "settings.db"
    SettingsService(target, environment={}).import_backup(settings.export_backup())
    assert SettingsService(target, environment={}).get_focus_draft() == draft


def test_analytics_and_draft_api_contract(tmp_path: Path) -> None:
    client = create_app(tmp_path / "api.db").test_client()
    empty = client.get("/api/focus/analytics?start=2026-08-20&end=2026-08-20")
    assert empty.status_code == 200
    assert empty.get_json()["analytics"]["summary"]["session_count"] == 0
    assert client.get("/api/focus/analytics?start=2026-08-21&end=2026-08-20").status_code == 400
    assert client.get("/api/settings/focus-draft").get_json()["draft"] is None
    assert client.put("/api/settings/focus-draft", json={"preset": "free", "mode": "free",
                                                      "minutes": 50}).status_code == 200
    assert client.get("/api/settings/focus-draft").get_json()["draft"]["preset"] == "free"
    assert client.put("/api/settings/focus-draft", json={"preset": "bad"}).status_code == 400
