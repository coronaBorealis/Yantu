from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from yantu.database.models import ProjectCategory, TaskPriority, TaskStatus
from yantu.database.repositories import TaskRepository, TimeEntryRepository
from yantu.database.repository import init_db
from yantu.services import ProjectService, TaskService, TimeEntryService


def _create_legacy_database(db_path: Path) -> None:
    connection = sqlite3.connect(db_path)
    try:
        connection.executescript(
            """
            CREATE TABLE projects (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, domain TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'active',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE tasks (
                id TEXT PRIMARY KEY, parent_id TEXT REFERENCES tasks(id) ON DELETE SET NULL,
                project_id TEXT REFERENCES projects(id) ON DELETE SET NULL, title TEXT NOT NULL,
                domain TEXT NOT NULL DEFAULT 'inbox', subcategory TEXT NOT NULL DEFAULT '',
                tags TEXT NOT NULL DEFAULT '[]', description TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL, start_date TEXT, due_date TEXT,
                estimated_minutes INTEGER NOT NULL DEFAULT 0, actual_minutes INTEGER NOT NULL DEFAULT 0,
                priority TEXT NOT NULL DEFAULT 'medium', status TEXT NOT NULL DEFAULT 'not_started',
                progress INTEGER NOT NULL DEFAULT 0, is_recurring INTEGER NOT NULL DEFAULT 0,
                recurrence_rule TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
                completed_at TEXT, sort_order INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE time_entries (
                id TEXT PRIMARY KEY, task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
                started_at TEXT NOT NULL, ended_at TEXT, minutes INTEGER NOT NULL DEFAULT 0,
                note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL
            );
            INSERT INTO projects VALUES (
                'legacy-project', '旧科研项目', 'research', '', 'active',
                '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00'
            );
            INSERT INTO tasks VALUES (
                'legacy-task', NULL, 'legacy-project', '旧任务', 'research', '', '[]', '',
                '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00', NULL,
                '2026-08-20', 90, 30, 'high', 'in_progress', 25, 0, '', '', NULL, 0
            );
            INSERT INTO time_entries VALUES (
                'legacy-time', 'legacy-task', '2026-08-01T08:00:00+00:00',
                '2026-08-01T08:30:00+00:00', 30, '旧记录', '2026-08-01T08:00:00+00:00'
            );
            """
        )
        connection.commit()
    finally:
        connection.close()


def test_legacy_database_is_migrated_without_data_loss(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    _create_legacy_database(db_path)

    init_db(db_path)
    init_db(db_path)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        project = dict(connection.execute("SELECT * FROM projects").fetchone())
        task = dict(connection.execute("SELECT * FROM tasks").fetchone())
        entry = dict(connection.execute("SELECT * FROM time_entries").fetchone())
        version = connection.execute("PRAGMA user_version").fetchone()[0]
        task_count = connection.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
    finally:
        connection.close()

    assert version == 8
    assert task_count == 1
    assert project["id"] == "legacy-project"
    assert project["category"] == "科研"
    assert task["id"] == "legacy-task"
    assert task["deadline"] == "2026-08-20"
    assert task["estimated_hours"] == 1.5
    assert task["actual_hours"] == 0.5
    assert entry["start_time"] == entry["started_at"]
    assert entry["duration"] == 30


def test_project_task_and_time_services(tmp_path: Path):
    db_path = tmp_path / "services.db"
    projects = ProjectService(db_path)
    tasks = TaskService(db_path)
    entries = TimeEntryService(db_path)

    project = projects.create(
        {"name": "实验室工作", "description": "设备维护", "category": "工作"}
    )
    assert project.category is ProjectCategory.WORK
    project = projects.update(project.id, {"name": "实验室事务"})
    assert project is not None and project.name == "实验室事务"

    parent = tasks.create(
        {
            "title": "完成激光雷达调研",
            "project_id": project.id,
            "priority": "HIGH",
            "status": "IN_PROGRESS",
            "deadline": "2026-08-20",
            "estimated_hours": 8,
        }
    )
    child = tasks.create(
        {
            "title": "阅读 SPAD 论文",
            "project_id": project.id,
            "parent_task_id": parent.id,
            "priority": TaskPriority.URGENT,
            "status": TaskStatus.TODO,
            "deadline": "2026-08-15",
            "estimated_hours": 3.5,
        }
    )
    no_deadline = tasks.create({"title": "整理研究笔记", "project_id": project.id})

    assert child.parent_task_id == parent.id
    assert child.estimated_hours == 3.5
    stored_child = tasks.repository.get(child.id)
    assert stored_child is not None
    assert stored_child["parent_id"] == parent.id
    assert stored_child["due_date"] == "2026-08-15"
    assert stored_child["estimated_minutes"] == 210
    assert [task.id for task in tasks.list(project_id=project.id, status="TODO")] == [
        child.id,
        no_deadline.id,
    ]
    ordered = tasks.list(project_id=project.id, sort_by_deadline=True)
    assert [task.id for task in ordered] == [child.id, parent.id, no_deadline.id]

    entry = entries.create(
        {
            "task_id": child.id,
            "start_time": "2026-08-12T09:00:00+08:00",
            "end_time": "2026-08-12T10:30:00+08:00",
            "duration": 90,
            "note": "阅读两篇论文",
        }
    )
    assert entry.duration == 90
    assert entries.list(task_id=child.id) == [entry]
    with pytest.raises(ValueError, match="end_time"):
        entries.update(entry.id, {"start_time": "2026-08-12T11:00:00+08:00"})
    updated = entries.update(entry.id, {"duration": 100, "note": "补充笔记"})
    assert updated is not None and updated.duration == 100
    assert entries.delete(entry.id)

    assert projects.delete(project.id)
    detached = tasks.get(parent.id)
    assert detached is not None and detached.project_id is None


def _task_record(task_id: str, title: str) -> dict[str, object]:
    now = "2026-08-11T00:00:00+00:00"
    return {
        "id": task_id,
        "parent_task_id": None,
        "project_id": None,
        "title": title,
        "domain": "research",
        "subcategory": "",
        "tags": [],
        "description": "",
        "created_at": now,
        "updated_at": now,
        "start_date": None,
        "deadline": None,
        "estimated_hours": 1,
        "actual_hours": 0,
        "priority": "MEDIUM",
        "status": "TODO",
        "progress": 0,
        "is_recurring": 0,
        "recurrence_rule": "",
        "notes": "",
        "completed_at": None,
        "sort_order": 0,
    }


def test_task_tree_insert_is_atomic(tmp_path: Path):
    repository = TaskRepository(tmp_path / "atomic.db")
    with pytest.raises(sqlite3.IntegrityError):
        repository.create_many(
            [_task_record("duplicate", "第一项"), _task_record("duplicate", "第二项")]
        )
    assert repository.count() == 0


def test_new_task_fields_win_over_conflicting_legacy_fields(tmp_path: Path):
    repository = TaskRepository(tmp_path / "aliases.db")
    record = _task_record("aliases", "字段冲突")
    record.update(
        {
            "deadline": "2026-08-21",
            "due_date": "2026-08-20",
            "estimated_hours": 2,
            "estimated_minutes": 60,
            "actual_hours": 1,
            "actual_minutes": 30,
        }
    )
    created = repository.create(record)
    assert created["deadline"] == created["due_date"] == "2026-08-21"
    assert created["estimated_hours"] == 2
    assert created["estimated_minutes"] == 120
    assert created["actual_hours"] == 1
    assert created["actual_minutes"] == 60
    connection = sqlite3.connect(repository.db_path)
    try:
        connection.execute(
            "UPDATE tasks SET due_date = '2026-08-01', estimated_minutes = 15 WHERE id = 'aliases'"
        )
        connection.commit()
    finally:
        connection.close()
    init_db(repository.db_path)
    synchronized = repository.get("aliases")
    assert synchronized is not None
    assert synchronized["due_date"] == synchronized["deadline"] == "2026-08-21"
    assert synchronized["estimated_minutes"] == 120


def test_new_time_fields_win_over_conflicting_legacy_fields(tmp_path: Path):
    db_path = tmp_path / "time-aliases.db"
    tasks = TaskRepository(db_path)
    tasks.create(_task_record("task", "计时任务"))
    entries = TimeEntryRepository(db_path)
    created = entries.create(
        {
            "id": "entry",
            "task_id": "task",
            "start_time": "2026-08-11T09:00:00+08:00",
            "started_at": "2026-08-11T08:00:00+08:00",
            "end_time": "2026-08-11T10:00:00+08:00",
            "ended_at": "2026-08-11T09:30:00+08:00",
            "duration": 60,
            "minutes": 30,
            "note": "",
            "created_at": "2026-08-11T09:00:00+08:00",
        }
    )
    assert created["start_time"] == created["started_at"] == "2026-08-11T09:00:00+08:00"
    assert created["end_time"] == created["ended_at"] == "2026-08-11T10:00:00+08:00"
    assert created["duration"] == created["minutes"] == 60


def test_task_service_rejects_direct_two_level_and_multi_level_cycles(tmp_path: Path):
    tasks = TaskService(tmp_path / "cycles.db")
    direct = tasks.create({"title": "直接循环"})
    with pytest.raises(ValueError, match="循环"):
        tasks.update(direct.id, {"parent_task_id": direct.id})

    first = tasks.create({"title": "第一层"})
    second = tasks.create({"title": "第二层", "parent_task_id": first.id})
    with pytest.raises(ValueError, match="循环"):
        tasks.update(first.id, {"parent_task_id": second.id})

    root = tasks.create({"title": "根"})
    middle = tasks.create({"title": "中", "parent_task_id": root.id})
    leaf = tasks.create({"title": "叶", "parent_task_id": middle.id})
    with pytest.raises(ValueError, match="循环"):
        tasks.update(root.id, {"parent_task_id": leaf.id})


def test_higher_database_version_is_preserved_with_warning(tmp_path: Path):
    db_path = tmp_path / "future.db"
    connection = sqlite3.connect(db_path)
    try:
        connection.execute("CREATE TABLE future_marker (id INTEGER PRIMARY KEY)")
        connection.execute("PRAGMA user_version = 9")
        connection.commit()
    finally:
        connection.close()

    with pytest.warns(RuntimeWarning, match="高于当前支持版本"):
        init_db(db_path)

    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 9
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_schema WHERE type = 'table'")
        }
        assert tables == {"future_marker"}
    finally:
        connection.close()
