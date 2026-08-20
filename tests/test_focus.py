from __future__ import annotations

from pathlib import Path

from yantu.main import create_app
from yantu.services.task_service import TaskService


def _task(service: TaskService, task_id: str, **changes):
    record = {
        "id": task_id,
        "title": task_id,
        "domain": "research",
        "created_at": "2026-08-20T00:00:00+00:00",
        "updated_at": "2026-08-20T00:00:00+00:00",
        "estimated_minutes": 240,
        "actual_minutes": 0,
        "priority": "medium",
        "status": "not_started",
        "progress": 0,
    }
    record.update(changes)
    return service.create_record(record)


def test_daily_plan_distributes_long_task_instead_of_charging_today(tmp_path: Path) -> None:
    service = TaskService(tmp_path / "plan.db")
    _task(service, "long", start_date="2026-08-20", due_date="2026-08-23")
    _task(service, "future", start_date="2026-08-21", due_date="2026-08-23")
    _task(service, "deadline-only", start_date=None, due_date="2026-08-23")
    _task(
        service,
        "due-today",
        start_date="2026-08-18",
        due_date="2026-08-20",
        estimated_minutes=120,
        actual_minutes=30,
    )

    plan = service.daily_plan("2026-08-20")
    allocations = {item["task_id"]: item for item in plan["allocations"]}
    assert allocations["long"]["planned_minutes"] == 60
    assert allocations["long"]["reason"] == "distributed"
    assert "future" not in allocations
    assert "deadline-only" not in allocations
    assert allocations["due-today"]["planned_minutes"] == 90
    assert plan["total_minutes"] == 150


def test_daily_plan_rebalances_remaining_time_and_overdue_work(tmp_path: Path) -> None:
    service = TaskService(tmp_path / "rebalance.db")
    _task(
        service,
        "progress",
        start_date="2026-08-18",
        due_date="2026-08-22",
        actual_minutes=60,
    )
    _task(service, "overdue", start_date="2026-08-10", due_date="2026-08-19", estimated_minutes=45)
    allocations = {
        item["task_id"]: item for item in service.daily_plan("2026-08-20")["allocations"]
    }
    assert allocations["progress"]["planned_minutes"] == 60
    assert allocations["overdue"] == {
        "task_id": "overdue",
        "planned_minutes": 45,
        "remaining_minutes": 45,
        "reason": "overdue",
    }


def test_focus_time_entry_api_updates_actual_minutes(tmp_path: Path) -> None:
    client = create_app(tmp_path / "focus.db").test_client()
    task = client.post(
        "/api/tasks",
        json={"title": "阅读论文", "domain": "research", "estimated_minutes": 120},
    ).get_json()["task"]

    created = client.post(
        "/api/time-entries",
        json={
            "task_id": task["id"],
            "start_time": "2026-08-20T09:00:00+08:00",
            "end_time": "2026-08-20T09:25:00+08:00",
            "duration": 25,
            "note": "番茄专注",
        },
    )
    assert created.status_code == 201
    entry = created.get_json()["time_entry"]
    assert client.get(f"/api/tasks/{task['id']}").get_json()["task"]["actual_minutes"] == 25
    assert len(client.get(f"/api/time-entries?task_id={task['id']}").get_json()["time_entries"]) == 1

    assert client.patch(f"/api/time-entries/{entry['id']}", json={"duration": 30}).status_code == 200
    assert client.get(f"/api/tasks/{task['id']}").get_json()["task"]["actual_minutes"] == 30
    assert client.delete(f"/api/time-entries/{entry['id']}").status_code == 204
    assert client.get(f"/api/tasks/{task['id']}").get_json()["task"]["actual_minutes"] == 0
