from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from yantu.database.config import REPOSITORY_ROOT, resolve_app_paths
from yantu.database.repository import init_db
from yantu.main import create_app
from yantu.services.focus_service import FocusService
from yantu.services.planning_service import PlanningService
from yantu.services.settings_service import SettingsService
from yantu.services.task_service import TaskService


class Clock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 20, 9, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += timedelta(seconds=seconds)


class MemoryCredentials:
    def __init__(self, value: str = "") -> None:
        self.value = value

    def get(self) -> str:
        return self.value

    def set(self, value: str) -> None:
        self.value = value

    def delete(self) -> None:
        self.value = ""


class JsonResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self.payload).encode()


def add_task(db_path: Path, task_id: str = "paper") -> None:
    TaskService(db_path).create_record({
        "id": task_id, "title": "阅读论文", "domain": "research",
        "created_at": "2026-08-20T08:00:00+00:00", "updated_at": "2026-08-20T08:00:00+00:00",
        "start_date": "2026-08-20", "due_date": "2026-08-20",
        "estimated_minutes": 60, "actual_minutes": 0, "priority": "high",
        "status": "not_started", "progress": 0,
    })


def make_focus(db_path: Path, clock: Clock, *, auto_break: bool = False) -> FocusService:
    settings = SettingsService(db_path, credential_store=MemoryCredentials(), environment={})
    settings.update_preferences({"auto_start_break": auto_break})
    return FocusService(db_path, now=clock, settings=settings)


def test_schema_v5_migration_is_idempotent_and_preserves_v4_data(tmp_path: Path) -> None:
    db_path = tmp_path / "v4.db"
    init_db(db_path)
    add_task(db_path, "kept")
    with sqlite3.connect(db_path) as connection:
        connection.execute("DROP TABLE focus_sessions")
        connection.execute("DROP TABLE app_settings")
        connection.execute("PRAGMA user_version = 4")
        connection.commit()

    init_db(db_path)
    init_db(db_path)
    with sqlite3.connect(db_path) as connection:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert {"focus_sessions", "app_settings"} <= tables
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 5
        assert connection.execute("SELECT title FROM tasks WHERE id='kept'").fetchone()[0] == "阅读论文"


def test_focus_pause_resume_recovery_and_idempotent_completion(tmp_path: Path) -> None:
    db_path = tmp_path / "focus.db"
    add_task(db_path)
    clock = Clock()
    service = make_focus(db_path, clock)
    session = service.start({"task_id": "paper", "mode": "pomodoro", "target_seconds": 1500})
    with pytest.raises(ValueError, match="已有"):
        service.start({"task_id": "paper", "target_seconds": 60})

    clock.advance(600)
    paused = service.pause(session["id"])
    assert paused["elapsed_seconds"] == 600 and paused["pause_count"] == 1
    clock.advance(120)
    resumed = service.resume(session["id"])
    assert resumed["paused_seconds"] == 120
    clock.advance(900)
    assert service.active()["status"] == "awaiting_action"

    completed = service.complete(session["id"])["session"]
    repeated = service.complete(session["id"])["session"]
    assert completed["time_entry_id"] == repeated["time_entry_id"]
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 1
        assert connection.execute("SELECT actual_minutes FROM tasks WHERE id='paper'").fetchone()[0] == 25


def test_partial_cancel_and_breaks_keep_one_time_ledger(tmp_path: Path) -> None:
    db_path = tmp_path / "break.db"
    add_task(db_path)
    clock = Clock()
    service = make_focus(db_path, clock, auto_break=True)
    session = service.start({"task_id": "paper", "mode": "pomodoro", "target_seconds": 60})
    clock.advance(60)
    result = service.complete(session["id"])
    assert result["next_session"]["session_type"] == "short_break"
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 1
    clock.advance(10)
    service.cancel(result["next_session"]["id"])
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 1

    partial = service.start({"task_id": "paper", "mode": "free", "target_seconds": 0})
    clock.advance(31)
    service.cancel(partial["id"], record_partial=True)
    with pytest.raises(ValueError, match="不能完成"):
        service.complete(partial["id"])
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT COUNT(*) FROM time_entries").fetchone()[0] == 2
        assert connection.execute("SELECT actual_minutes FROM tasks WHERE id='paper'").fetchone()[0] == 2


def test_completed_focus_updates_linked_plan_block_and_cross_midnight_stats(tmp_path: Path) -> None:
    db_path = tmp_path / "linked.db"
    add_task(db_path)
    planning = PlanningService(db_path)
    planning.update_profile({"workday_start": "09:00", "workday_end": "11:00", "focus_minutes": 25})
    preview = planning.preview({"date": "2026-08-20"})
    plan = planning.confirm(preview)
    block = next(item for item in plan["blocks"] if item["block_type"] == "focus")
    clock = Clock()
    service = make_focus(db_path, clock)
    session = service.start({
        "task_id": "paper", "plan_block_id": block["id"], "mode": "pomodoro",
        "target_seconds": block["planned_minutes"] * 60,
    })
    clock.advance(block["planned_minutes"] * 60)
    service.complete(session["id"])
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT status FROM plan_blocks WHERE id = ?", (block["id"],)).fetchone()[0] == "completed"

    # A real elapsed interval spanning midnight is distributed across both dates.
    clock.value = datetime(2026, 8, 20, 23, 50, tzinfo=timezone(timedelta(hours=8)))
    overnight = service.start({"task_id": "paper", "mode": "free", "target_seconds": 0})
    clock.advance(20 * 60)
    service.complete(overnight["id"])
    days = service.stats(start="2026-08-20", end="2026-08-21")["by_day"]
    assert len(days) == 2 and sum(item["minutes"] for item in days) >= 20


def test_settings_never_expose_or_backup_key_and_environment_wins(tmp_path: Path) -> None:
    db_path = tmp_path / "settings.db"
    credentials = MemoryCredentials()
    service = SettingsService(db_path, credential_store=credentials, environment={})
    secret = "sk-test-secret-123456"
    result = service.update_ai({"api_key": secret, "model": "deepseek-chat"})
    assert result["configured"] and secret not in json.dumps(result)
    assert secret not in json.dumps(service.export_backup())
    with sqlite3.connect(db_path) as connection:
        assert secret not in "".join(str(row) for row in connection.iterdump())

    managed = SettingsService(
        db_path, credential_store=credentials,
        environment={"DEEPSEEK_API_KEY": "sk-env-secret-999999"},
    )
    assert managed.get_ai()["credential_source"] == "environment"
    assert managed.resolved_ai()["api_key"] == "sk-env-secret-999999"
    with pytest.raises(ValueError, match="环境变量"):
        managed.update_ai({"api_key": "sk-replacement-12345"})


def test_ai_connection_checks_selected_model_without_chat_request(tmp_path: Path) -> None:
    calls = []

    def transport(request, timeout):
        calls.append((request.full_url, request.get_header("Authorization"), timeout))
        return JsonResponse({"data": [{"id": "deepseek-chat"}]})

    service = SettingsService(
        tmp_path / "connection.db", credential_store=MemoryCredentials("sk-valid-secret-1234"),
        environment={}, transport=transport,
    )
    service.update_ai({"model": "deepseek-chat", "base_url": "https://api.deepseek.com"})
    assert service.test_ai() == {"ok": True, "model_available": True, "models": ["deepseek-chat"]}
    assert calls == [("https://api.deepseek.com/models", "Bearer sk-valid-secret-1234", 60)]
    with pytest.raises(ValueError, match="HTTPS"):
        service.update_ai({"base_url": "http://example.com"})
    with pytest.raises(ValueError, match="布尔值"):
        service.update_preferences({"sound_enabled": "false"})


def test_app_paths_and_request_token_boundary(tmp_path: Path) -> None:
    override = resolve_app_paths(environ={"YANTU_DATA_DIR": str(tmp_path / "中文数据")}, frozen=False)
    assert override.data_root == (tmp_path / "中文数据").resolve()
    frozen = resolve_app_paths(environ={}, frozen=True, local_app_data=tmp_path / "Local")
    assert frozen.data_root == (tmp_path / "Local" / "Yantu").resolve()
    source = resolve_app_paths(environ={}, frozen=False)
    assert source.resource_root == REPOSITORY_ROOT and source.database.name == "yantu.db"

    app = create_app(tmp_path / "secure.db")
    app.config["REQUEST_TOKEN"] = "local-token"
    client = app.test_client()
    assert client.get("/api/tasks").status_code == 200
    assert client.post("/api/tasks", json={"title": "blocked"}).status_code == 403
    allowed = client.post(
        "/api/tasks", json={"title": "allowed"}, headers={"X-Yantu-Token": "local-token"},
    )
    assert allowed.status_code == 201
    html = client.get("/").get_data(as_text=True)
    assert 'content="local-token"' in html


def test_focus_api_history_stats_and_backup_exclude_active_session(tmp_path: Path) -> None:
    db_path = tmp_path / "api.db"
    client = create_app(db_path).test_client()
    task = client.post("/api/tasks", json={"title": "实验", "domain": "research"}).get_json()["task"]
    created = client.post("/api/focus/sessions", json={
        "task_id": task["id"], "mode": "free", "target_seconds": 0,
    })
    assert created.status_code == 201
    session_id = created.get_json()["session"]["id"]
    assert client.get("/api/focus/active").get_json()["session"]["id"] == session_id
    assert client.post(f"/api/focus/sessions/{session_id}/cancel").status_code == 200
    assert client.get("/api/focus/history").get_json()["sessions"]
    stats = client.get("/api/focus/stats?start=2026-01-01&end=2026-12-31").get_json()["stats"]
    assert stats["focus_minutes"] == 0
    backup = client.get("/api/export").get_json()
    assert backup["version"] == 5 and "focus_sessions" in backup and "settings" in backup
    assert "api_key" not in json.dumps(backup).lower()


def test_completed_focus_history_survives_v5_backup_restore(tmp_path: Path) -> None:
    source_path = tmp_path / "source.db"
    add_task(source_path)
    clock = Clock()
    source = make_focus(source_path, clock)
    session = source.start({"task_id": "paper", "mode": "pomodoro", "target_seconds": 60})
    clock.advance(60)
    source.complete(session["id"])
    history = source.export_backup()

    target_path = tmp_path / "target.db"
    add_task(target_path)
    target = make_focus(target_path, Clock())
    assert target.import_backup(history) == 1
    stats = target.stats(start="2026-08-20", end="2026-08-20")
    assert stats["focus_minutes"] == 1 and stats["completed_sessions"] == 1
