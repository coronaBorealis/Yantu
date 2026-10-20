from __future__ import annotations

import io
import sqlite3
from pathlib import Path

import pytest

from yantu.database.repository import init_db
from yantu.main import create_app
from yantu.services.schedule_import_service import ScheduleImportService, _week_rule
from yantu.services.schedule_service import ScheduleService


def semester_payload() -> dict:
    return {
        "name": "2026 秋季学期",
        "start_date": "2026-08-31",
        "end_date": "2027-01-17",
        "periods": [
            {"period": 1, "start_time": "08:00", "end_time": "08:45"},
            {"period": 2, "start_time": "08:55", "end_time": "09:40"},
            {"period": 3, "start_time": "10:00", "end_time": "10:45"},
            {"period": 4, "start_time": "10:55", "end_time": "11:40"},
        ],
    }


def test_v3_migration_is_idempotent_and_preserves_tasks(tmp_path: Path):
    db_path = tmp_path / "v3.db"
    init_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        connection.execute(
            """INSERT INTO tasks
            (id,title,domain,created_at,updated_at) VALUES ('old','旧任务','inbox','now','now')"""
        )
        connection.commit()
    finally:
        connection.close()
    init_db(db_path)
    init_db(db_path)
    connection = sqlite3.connect(db_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 15
        assert connection.execute("SELECT title FROM tasks WHERE id='old'").fetchone()[0] == "旧任务"
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_schema WHERE type='table'")}
        assert {"semesters", "courses", "course_meetings", "course_exceptions", "schedule_imports"} <= tables
    finally:
        connection.close()


def test_course_events_support_odd_even_custom_and_skip(tmp_path: Path):
    service = ScheduleService(tmp_path / "schedule.db")
    semester = service.save_semester(semester_payload())
    odd = service.create_course({
        "semester_id": semester["id"], "name": "机器视觉", "location": "A101",
        "meetings": [{"weekday": 1, "start_period": 1, "end_period": 2,
            "start_time": "08:00", "end_time": "09:40", "start_week": 1,
            "end_week": 4, "week_pattern": "odd"}],
    })
    service.create_course({
        "semester_id": semester["id"], "name": "科研写作",
        "meetings": [{"weekday": 2, "start_period": 3, "end_period": 4,
            "start_time": "10:00", "end_time": "11:40", "start_week": 1,
            "end_week": 4, "week_pattern": "custom", "custom_weeks": [2, 4]}],
    })
    events = service.calendar_events("2026-08-31", "2026-09-27")
    assert [item["date"] for item in events if item["title"] == "机器视觉"] == ["2026-08-31", "2026-09-14"]
    assert [item["date"] for item in events if item["title"] == "科研写作"] == ["2026-09-08", "2026-09-22"]
    meeting_id = odd["meetings"][0]["id"]
    assert service.skip_occurrence(meeting_id, "2026-09-14")
    assert [item["date"] for item in service.calendar_events("2026-08-31", "2026-09-27") if item["title"] == "机器视觉"] == ["2026-08-31"]


def test_csv_preview_is_read_only_then_confirm_is_atomic(tmp_path: Path):
    db_path = tmp_path / "import.db"
    importer = ScheduleImportService(db_path)
    content = "课程名称,教师,地点,星期,节次,周次\n激光雷达,王老师,A101,周一,1-2节,1-8周单周\n".encode("utf-8")
    preview = importer.preview("课表.csv", content, {"semester": semester_payload()})
    assert preview["courses"][0]["name"] == "激光雷达"
    assert preview["courses"][0]["meetings"][0]["week_pattern"] == "odd"
    assert importer.repository.list_courses() == []
    created = importer.confirm(preview)
    assert len(created) == 1
    assert importer.repository.list_courses()[0]["name"] == "激光雷达"
    with pytest.raises(ValueError, match="已经导入"):
        importer.confirm(preview)


@pytest.mark.parametrize("text,expected", [
    ("1-16周", (1, 16, "all", [])),
    ("第1—16周（第2-4节）", (1, 16, "all", [])),
    ("1-16周单周", (1, 16, "odd", [])),
    ("6-12,14-16周", (6, 16, "custom", [6, 7, 8, 9, 10, 11, 12, 14, 15, 16])),
    ("1-8周,10-16周", (1, 16, "custom", [*range(1, 9), *range(10, 17)])),
    ("1-8,10-16周单周", (1, 15, "custom", [1, 3, 5, 7, 11, 13, 15])),
])
def test_week_rule_ignores_unrelated_period_numbers(text: str, expected: tuple):
    assert _week_rule(text) == expected


@pytest.mark.parametrize("text", ["0-16周", "16-1周", "未识别周次"])
def test_week_rule_rejects_invalid_or_unreadable_range(text: str):
    with pytest.raises(ValueError, match="周次"):
        _week_rule(text)


def test_invalid_week_preview_can_be_corrected_before_atomic_confirm(tmp_path: Path):
    importer = ScheduleImportService(tmp_path / "recover.db")
    content = (
        "课程名称,教师,地点,星期,节次,周次\n"
        "光学原理,李老师,A101,周一,1-2节,1-16周\n"
        "信号处理,王老师,B202,周三,3-4节,0-16周\n"
    ).encode("utf-8")
    preview = importer.preview("课表.csv", content, {"semester": semester_payload()})
    invalid = preview["courses"][1]
    assert invalid["selected"] is False
    assert invalid["meetings"][0]["start_week"] == 0
    assert invalid["meetings"][0]["end_week"] == 16
    assert importer.repository.list_courses() == []
    invalid["selected"] = True
    with pytest.raises(ValueError, match="课程周次范围无效"):
        importer.confirm(preview)
    assert importer.repository.list_courses() == []
    assert importer.repository.list_semesters() == []
    invalid["meetings"][0]["start_week"] = 1
    created = importer.confirm(preview)
    assert len(created) == 2
    assert {course["name"] for course in importer.repository.list_courses()} == {"光学原理", "信号处理"}


def test_same_course_with_one_invalid_week_remains_one_editable_draft(tmp_path: Path):
    importer = ScheduleImportService(tmp_path / "merged.db")
    content = (
        "课程名称,教师,地点,星期,节次,周次\n"
        "光学原理,李老师,A101,周一,1-2节,1-8周\n"
        "光学原理,李老师,A101,周三,3-4节,0-8周\n"
    ).encode("utf-8")
    preview = importer.preview("课表.csv", content, {"semester": semester_payload()})
    assert len(preview["courses"]) == 1
    course = preview["courses"][0]
    assert course["selected"] is False
    assert len(course["meetings"]) == 2
    next(meeting for meeting in course["meetings"] if meeting["weekday"] == 3)["start_week"] = 1
    course["selected"] = True
    importer.confirm(preview)
    saved = importer.repository.list_courses()
    assert len(saved) == 1
    assert len(importer.repository.get_course(saved[0]["id"])["meetings"]) == 2


def test_import_rejects_weeks_outside_semester_without_writing(tmp_path: Path):
    importer = ScheduleImportService(tmp_path / "short-semester.db")
    short = {**semester_payload(), "end_date": "2026-09-13"}
    content = "课程名称,星期,节次,周次\n机器视觉,周一,1-2节,1-8周\n".encode("utf-8")
    preview = importer.preview("课表.csv", content, {"semester": short})
    assert "仅覆盖 2 周" in preview["courses"][0]["warnings"][0]
    with pytest.raises(ValueError, match="超出学期日期"):
        importer.confirm(preview)
    assert importer.repository.list_courses() == []
    assert importer.repository.list_semesters() == []


class FakeOCR:
    def recognize(self, _path: Path):
        return [{"text": "周三|信号处理|3-4节|1-16周|李老师|B202", "confidence": 0.95, "bbox": []}]


def test_image_preview_uses_injected_local_ocr(tmp_path: Path):
    importer = ScheduleImportService(tmp_path / "image.db", FakeOCR())
    png = b"\x89PNG\r\n\x1a\n" + b"image"
    preview = importer.preview("schedule.png", png, {"semester": semester_payload()})
    assert preview["courses"][0]["name"] == "信号处理"
    assert preview["courses"][0]["meetings"][0]["weekday"] == 3


class SplitBoxOCR:
    def recognize(self, _path: Path):
        return [
            {"text": "周一", "confidence": 0.99, "bbox": [100, 0, 180, 30]},
            {"text": "周二", "confidence": 0.99, "bbox": [200, 0, 280, 30]},
            {"text": "1-2节", "confidence": 0.99, "bbox": [0, 60, 70, 100]},
            {"text": "光学原理", "confidence": 0.96, "bbox": [100, 60, 180, 78]},
            {"text": "1-8周单周", "confidence": 0.94, "bbox": [100, 80, 180, 98]},
        ]


def test_image_layout_boxes_are_grouped_by_weekday_and_period(tmp_path: Path):
    importer = ScheduleImportService(tmp_path / "boxes.db", SplitBoxOCR())
    png = b"\x89PNG\r\n\x1a\n" + b"image"
    preview = importer.preview("schedule.png", png, {"semester": semester_payload()})
    course = preview["courses"][0]
    assert course["name"] == "光学原理"
    assert course["meetings"][0]["weekday"] == 1
    assert course["meetings"][0]["week_pattern"] == "odd"


def test_schedule_api_and_recoverable_deletion(tmp_path: Path):
    app = create_app(tmp_path / "api.db", schedule_ocr_engine=FakeOCR())
    app.config["TESTING"] = True
    client = app.test_client()
    semester = client.post("/api/semesters", json=semester_payload()).get_json()["semester"]
    created = client.post("/api/courses", json={
        "semester_id": semester["id"], "name": "光电检测",
        "meetings": [{"weekday": 3, "start_period": 1, "end_period": 2,
            "start_time": "08:00", "end_time": "09:40", "start_week": 1,
            "end_week": 2, "week_pattern": "all"}],
    })
    assert created.status_code == 201
    course = created.get_json()["course"]
    events = client.get("/api/calendar/events?start=2026-08-31&end=2026-09-13").get_json()["events"]
    assert len(events) == 2
    assert client.delete(f"/api/courses/{course['id']}").status_code == 204
    assert len(client.get("/api/trash").get_json()["courses"]) == 1
    assert client.post(f"/api/courses/{course['id']}/restore").status_code == 204

    task = client.post("/api/tasks", json={"title": "可恢复任务"}).get_json()["task"]
    assert client.delete(f"/api/tasks/{task['id']}").status_code == 204
    assert client.get(f"/api/tasks/{task['id']}").status_code == 404
    assert client.post(f"/api/tasks/{task['id']}/restore").status_code == 204
    assert client.get(f"/api/tasks/{task['id']}").status_code == 200


def test_schedule_upload_validation(tmp_path: Path):
    client = create_app(tmp_path / "upload.db", schedule_ocr_engine=FakeOCR()).test_client()
    config = '{"semester":{"name":"秋季","start_date":"2026-08-31","end_date":"2027-01-17"}}'
    bad = client.post("/api/schedule-import/preview", data={"config": config, "file": (io.BytesIO(b"not png"), "bad.png")})
    assert bad.status_code == 400
    assert "扩展名" in bad.get_json()["error"]


def test_v3_backup_restores_courses_and_trash(tmp_path: Path):
    source = create_app(tmp_path / "source.db").test_client()
    semester = source.post("/api/semesters", json=semester_payload()).get_json()["semester"]
    course = source.post("/api/courses", json={
        "semester_id": semester["id"], "name": "备份课程",
        "meetings": [{"weekday": 5, "start_period": 1, "end_period": 2,
            "start_time": "08:00", "end_time": "09:40", "start_week": 1,
            "end_week": 2, "week_pattern": "all"}],
    }).get_json()["course"]
    task = source.post("/api/tasks", json={"title": "回收站任务"}).get_json()["task"]
    source.delete(f"/api/tasks/{task['id']}")
    source.post(
        f"/api/course-meetings/{course['meetings'][0]['id']}/exceptions",
        json={"kind": "skip", "date": "2026-09-04"},
    )
    backup = source.get("/api/export").get_json()

    target = create_app(tmp_path / "target.db").test_client()
    restored = target.post("/api/import", json=backup)
    assert restored.status_code == 200
    assert restored.get_json()["courses_imported"] == 1
    assert len(target.get("/api/trash").get_json()["tasks"]) == 1
    assert target.get("/api/courses").get_json()["courses"][0]["name"] == "备份课程"
    events = target.get(
        "/api/calendar/events?start=2026-08-31&end=2026-09-13"
    ).get_json()["events"]
    assert [event["date"] for event in events] == ["2026-09-11"]
