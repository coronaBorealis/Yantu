from __future__ import annotations

import json
import socket
import sqlite3
import tempfile
import unittest
from pathlib import Path


from yantu.database.repository import init_db
from yantu.main import bind_server, create_app


class YantuApiTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test.db"
        self.app = create_app(self.db_path)
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_health_and_sqlite_schema(self):
        response = self.client.get("/api/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["status"], "ok")
        self.assertIn("instance_id", response.get_json())
        connection = sqlite3.connect(self.db_path)
        try:
            tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
            indexes = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='index'")}
        finally:
            connection.close()
        self.assertTrue({"tasks", "projects", "time_entries"}.issubset(tables))
        self.assertIn("idx_tasks_domain_status", indexes)
        self.assertIn("idx_tasks_due_date", indexes)

    def test_task_crud_and_all_mvp_fields(self):
        payload = {
            "title": "准备组会汇报",
            "domain": "research",
            "subcategory": "组会汇报",
            "tags": ["导师", "实验"],
            "description": "整理实验结果并形成三页汇报",
            "start_date": "2026-08-11",
            "due_date": "2026-08-15",
            "estimated_minutes": 180,
            "actual_minutes": 35,
            "priority": "high",
            "status": "in_progress",
            "progress": 30,
            "is_recurring": True,
            "recurrence_rule": "每月一次",
            "notes": "先确认图表",
        }
        created = self.client.post("/api/tasks", json=payload)
        self.assertEqual(created.status_code, 201)
        task = created.get_json()["task"]
        self.assertEqual(task["domain"], "research")
        self.assertEqual(task["tags"], ["导师", "实验"])
        self.assertTrue(task["created_at"])

        updated = self.client.patch(
            f"/api/tasks/{task['id']}",
            json={"status": "completed", "actual_minutes": 190},
        )
        self.assertEqual(updated.status_code, 200)
        completed = updated.get_json()["task"]
        self.assertEqual(completed["progress"], 100)
        self.assertTrue(completed["completed_at"])

        listed = self.client.get("/api/tasks?domain=research&status=completed")
        self.assertEqual(len(listed.get_json()["tasks"]), 1)

        deleted = self.client.delete(f"/api/tasks/{task['id']}")
        self.assertEqual(deleted.status_code, 204)
        self.assertEqual(self.client.get(f"/api/tasks/{task['id']}").status_code, 404)

    def test_task_without_deadline_and_validation(self):
        response = self.client.post(
            "/api/tasks",
            json={"title": "探索新的研究方向", "domain": "research", "due_date": None},
        )
        self.assertEqual(response.status_code, 201)
        self.assertIsNone(response.get_json()["task"]["due_date"])
        invalid = self.client.post("/api/tasks", json={"title": "", "domain": "unknown"})
        self.assertEqual(invalid.status_code, 400)

        invalid_schedule = self.client.post(
            "/api/tasks",
            json={
                "title": "日期顺序错误",
                "domain": "course",
                "start_date": "2026-08-20",
                "due_date": "2026-08-19",
            },
        )
        self.assertEqual(invalid_schedule.status_code, 400)

    def test_legacy_waiting_status_remains_compatible(self):
        created = self.client.post(
            "/api/tasks",
            json={"title": "等待设备", "domain": "research", "status": "waiting"},
        )
        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.get_json()["task"]["status"], "waiting")
        listed = self.client.get("/api/tasks?status=waiting")
        self.assertEqual([task["title"] for task in listed.get_json()["tasks"]], ["等待设备"])

    def test_completion_invariants_and_timestamp_are_stable(self):
        created = self.client.post(
            "/api/tasks",
            json={"title": "完成状态测试", "domain": "personal", "status": "completed"},
        ).get_json()["task"]
        self.assertEqual(created["progress"], 100)
        first_completed_at = created["completed_at"]

        edited = self.client.patch(
            f"/api/tasks/{created['id']}",
            json={"title": "完成状态测试（已编辑）", "progress": 20},
        ).get_json()["task"]
        self.assertEqual(edited["progress"], 100)
        self.assertEqual(edited["completed_at"], first_completed_at)

        reopened = self.client.patch(
            f"/api/tasks/{created['id']}",
            json={"status": "in_progress", "progress": 40},
        ).get_json()["task"]
        self.assertEqual(reopened["progress"], 40)
        self.assertIsNone(reopened["completed_at"])

    def test_backup_export_and_import(self):
        self.client.post("/api/tasks", json={"title": "课程项目", "domain": "course"})
        backup = self.client.get("/api/export").get_json()
        self.assertEqual(backup["version"], 4)
        self.assertEqual(len(backup["tasks"]), 1)

        other_db = Path(self.temp_dir.name) / "restored.db"
        other_client = create_app(other_db).test_client()
        restored = other_client.post("/api/import", json=backup)
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.get_json()["imported"], 1)
        self.assertEqual(len(other_client.get("/api/tasks").get_json()["tasks"]), 1)

    def test_dynamic_port_falls_back_after_real_bind_failure(self):
        blocker = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        blocker.bind(("127.0.0.1", 0))
        blocker.listen(1)
        blocked_port = blocker.getsockname()[1]
        server = None
        try:
            server, actual_port, errors = bind_server(self.app, "127.0.0.1", blocked_port, attempts=2)
            self.assertNotEqual(actual_port, blocked_port)
            self.assertTrue(errors)
        finally:
            if server is not None:
                server.server_close()
            blocker.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
