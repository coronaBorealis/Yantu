from __future__ import annotations

from datetime import date
from pathlib import Path

from yantu.main import create_app
from yantu.services.archive_service import ArchiveService
from yantu.services.schedule_import_service import ScheduleImportService


def semester() -> dict:
    return {
        "name": "2026 秋季学期",
        "stage_label": "研一上",
        "start_date": "2026-09-21",
        "end_date": "2027-01-17",
    }


def test_time_block_task_expands_into_calendar_and_repeats_weekly(tmp_path: Path) -> None:
    client = create_app(tmp_path / "time-block.db").test_client()
    response = client.post(
        "/api/tasks",
        json={
            "title": "固定组会",
            "domain": "research",
            "schedule_mode": "time_block",
            "scheduled_date": "2026-09-22",
            "scheduled_start_time": "15:00",
            "scheduled_end_time": "16:30",
            "is_recurring": True,
            "recurrence_rule": "weekly",
            "recurrence_until": "2026-10-06",
        },
    )
    assert response.status_code == 201
    task = response.get_json()["task"]
    assert task["schedule_mode"] == "time_block"

    events = client.get(
        "/api/calendar/events?start=2026-09-21&end=2026-10-11"
    ).get_json()["events"]
    task_events = [event for event in events if event.get("task_id") == task["id"]]
    assert [event["date"] for event in task_events] == [
        "2026-09-22",
        "2026-09-29",
        "2026-10-06",
    ]
    assert all(event["source_type"] == "task" for event in task_events)


def test_changing_first_week_date_only_moves_course_occurrences(tmp_path: Path) -> None:
    client = create_app(tmp_path / "semester.db").test_client()
    saved = client.post("/api/semesters", json=semester()).get_json()["semester"]
    assert saved["stage_label"] == "研一上"
    client.post(
        "/api/courses",
        json={
            "semester_id": saved["id"],
            "name": "数值分析",
            "meetings": [{
                "weekday": 1,
                "start_period": 1,
                "end_period": 2,
                "start_time": "08:00",
                "end_time": "09:35",
                "start_week": 1,
                "end_week": 2,
            }],
        },
    )
    before = client.get(
        "/api/calendar/events?start=2026-09-21&end=2026-10-11"
    ).get_json()["events"]
    assert [event["date"] for event in before] == ["2026-09-21", "2026-09-28"]

    changed = {**saved, "start_date": "2026-09-28"}
    response = client.put(f"/api/semesters/{saved['id']}", json=changed)
    assert response.status_code == 200
    after = client.get(
        "/api/calendar/events?start=2026-09-21&end=2026-10-11"
    ).get_json()["events"]
    assert [event["date"] for event in after] == ["2026-09-28", "2026-10-05"]


class PdfOCR:
    def recognize(self, path: Path):
        assert path.suffix == ".pdf"
        return [
            {
                "text": "周四|学位英语|1-2节|1-16周|刘晓妍|纪忠楼-Y407",
                "confidence": 0.98,
                "bbox": [],
            },
            {
                "text": "人工智能通识导论06班（9月-10月MOOC）",
                "confidence": 0.96,
                "bbox": [],
            },
        ]


def test_pdf_timetable_is_accepted_and_disjoint_week_ranges_expand(tmp_path: Path) -> None:
    importer = ScheduleImportService(tmp_path / "pdf.db", PdfOCR())
    preview = importer.preview("课表.pdf", b"%PDF-1.7\nmock", {"semester": semester()})
    assert preview["source_type"] == "pdf"
    assert preview["courses"][0]["meetings"][0]["start_time"] == "08:00"
    assert preview["learning_items"][0]["title"] == "人工智能通识导论"
    importer.confirm(preview)
    assert any(
        task["title"] == "人工智能通识导论" and task["task_kind"] == "free_learning"
        for task in importer.schedule.tasks.list()
    )

    csv_content = (
        "课程名称,教师,地点,星期,节次,周次\n"
        '理论与实践,许川,纪忠楼-Y312,周四,6-8节,"6-12,14-16周"\n'
    ).encode("utf-8")
    csv_preview = importer.preview("课表.csv", csv_content, {"semester": semester()})
    meeting = csv_preview["courses"][0]["meetings"][0]
    assert meeting["week_pattern"] == "custom"
    assert meeting["custom_weeks"] == [6, 7, 8, 9, 10, 11, 12, 14, 15, 16]


def test_archive_layout_prepares_week_and_month_manifests(tmp_path: Path) -> None:
    service = ArchiveService(tmp_path / "archive.db")
    periods = service.prepare(date(2026, 9, 21))
    assert {item["period_key"] for item in periods} == {"2026-W39", "2026-09"}
    assert (tmp_path / "archive" / "schema-v1.json").is_file()
    assert (tmp_path / "archive" / "weekly" / "2026" / "2026-W39" / "manifest.json").is_file()
    assert (tmp_path / "archive" / "monthly" / "2026" / "2026-09" / "entries.ndjson").is_file()
