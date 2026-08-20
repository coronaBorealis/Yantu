from __future__ import annotations

import json
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services.schedule_import_service import OCRUnavailableError, ScheduleImportService
from ..services.schedule_service import ScheduleService


def create_schedule_blueprint(db_path: Path | str, ocr_engine=None) -> Blueprint:
    blueprint = Blueprint("schedule", __name__, url_prefix="/api")
    schedules = ScheduleService(db_path)
    importer = ScheduleImportService(db_path, ocr_engine=ocr_engine)

    @blueprint.get("/semesters")
    def semesters_list():
        return jsonify({"semesters": schedules.list_semesters()})

    @blueprint.post("/semesters")
    def semesters_create():
        semester = schedules.save_semester(request.get_json(silent=True) or {})
        return jsonify({"semester": semester}), 201

    @blueprint.put("/semesters/<semester_id>")
    def semesters_update(semester_id: str):
        if not schedules.get_semester(semester_id):
            return jsonify({"error": "Semester not found"}), 404
        semester = schedules.save_semester(
            request.get_json(silent=True) or {}, semester_id=semester_id
        )
        return jsonify({"semester": semester})

    @blueprint.get("/courses")
    def courses_list():
        return jsonify({
            "courses": schedules.list_courses(request.args.get("semester_id") or None)
        })

    @blueprint.get("/courses/<course_id>")
    def courses_get(course_id: str):
        course = schedules.get_course(course_id)
        if not course:
            return jsonify({"error": "Course not found"}), 404
        return jsonify({"course": course})

    @blueprint.post("/courses")
    def courses_create():
        return jsonify({"course": schedules.create_course(request.get_json(silent=True) or {})}), 201

    @blueprint.put("/courses/<course_id>")
    def courses_update(course_id: str):
        course = schedules.update_course(course_id, request.get_json(silent=True) or {})
        if not course:
            return jsonify({"error": "Course not found"}), 404
        return jsonify({"course": course})

    @blueprint.post("/courses/<course_id>/duplicate")
    def courses_duplicate(course_id: str):
        course = schedules.duplicate_course(course_id)
        if not course:
            return jsonify({"error": "Course not found"}), 404
        return jsonify({"course": course}), 201

    @blueprint.delete("/courses/<course_id>")
    def courses_delete(course_id: str):
        if not schedules.trash_course(course_id):
            return jsonify({"error": "Course not found"}), 404
        return "", 204

    @blueprint.post("/courses/<course_id>/restore")
    def courses_restore(course_id: str):
        if not schedules.restore_course(course_id):
            return jsonify({"error": "Course not found"}), 404
        return "", 204

    @blueprint.delete("/courses/<course_id>/permanent")
    def courses_permanent_delete(course_id: str):
        if not schedules.delete_course_permanently(course_id):
            return jsonify({"error": "Course not found in trash"}), 404
        return "", 204

    @blueprint.post("/course-meetings/<meeting_id>/exceptions")
    def meeting_exception(meeting_id: str):
        payload = request.get_json(silent=True) or {}
        if payload.get("kind", "skip") != "skip":
            raise ValueError("当前仅支持 skip 例外")
        if not schedules.skip_occurrence(meeting_id, payload.get("date")):
            return jsonify({"error": "Meeting not found"}), 404
        return "", 204

    @blueprint.get("/calendar/events")
    def calendar_events():
        start, end = request.args.get("start"), request.args.get("end")
        if not start or not end:
            raise ValueError("start 和 end 查询参数不能为空")
        return jsonify({"events": schedules.calendar_events(start, end)})

    @blueprint.post("/schedule-import/preview")
    def schedule_preview():
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            raise ValueError("请选择课表文件")
        try:
            config = json.loads(request.form.get("config") or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("课表配置不是有效 JSON") from exc
        return jsonify({"preview": importer.preview(uploaded.filename, uploaded.read(), config)})

    @blueprint.post("/schedule-import/confirm")
    def schedule_confirm():
        created = importer.confirm(request.get_json(silent=True) or {})
        return jsonify({"created_course_ids": created}), 201

    @blueprint.errorhandler(OCRUnavailableError)
    def ocr_unavailable(error: OCRUnavailableError):
        return jsonify({"error": str(error), "code": "ocr_unavailable"}), 503

    @blueprint.errorhandler(ValueError)
    def invalid_schedule(error: ValueError):
        return jsonify({"error": str(error)}), 400

    return blueprint
