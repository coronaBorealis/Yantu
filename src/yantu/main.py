from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import secrets
import socket
import sys
import threading
import time
import uuid
import webbrowser
from dataclasses import asdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import urlopen

PACKAGE_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = PACKAGE_ROOT / "web"

from flask import Flask, jsonify, request, send_from_directory
from werkzeug.serving import BaseWSGIServer, ThreadedWSGIServer

from .common import utc_now
from .api.ai_routes import ServiceFactory, create_ai_blueprint
from .api.appearance_routes import create_appearance_blueprint
from .api.schedule_routes import create_schedule_blueprint
from .api.time_routes import create_time_blueprint
from .api.planning_routes import create_planning_blueprint
from .api.focus_routes import create_focus_blueprint
from .api.settings_routes import create_settings_blueprint
from .api.research_routes import create_research_blueprint
from .api.project_routes import create_project_blueprint
from .database.config import APP_PATHS, DEFAULT_DB_PATH
from .database.constants import DOMAINS, PRIORITIES, STATUSES
from .services.task_service import TaskService
from .services.schedule_service import ScheduleService
from .services.appearance_service import AppearanceService
from .services.planning_service import PlanningService
from .services.focus_service import FocusService
from .services.focus_habit_service import FocusHabitMonitor, FocusHabitService
from .services.settings_service import SettingsService
from .services.research_service import ResearchService
from .services.project_service import ProjectService
from .services.archive_service import ArchiveService


RUNTIME_FILE = APP_PATHS.runtime_file
ASSET_FILES = {"styles.css", "theme.css", "app.js", "focus-analytics.css", "focus-analytics.js"}
BRAND_ASSETS = {
    "logo-master.png", "logo-512.png", "logo-192.png", "logo-64.png",
    "logo-32.png", "logo-16.png", "yantu.ico",
}
TASK_FIELDS = {
    "parent_id",
    "project_id",
    "title",
    "domain",
    "task_kind",
    "schedule_mode",
    "scheduled_date",
    "scheduled_start_time",
    "scheduled_end_time",
    "schedule_timezone",
    "recurrence_until",
    "subcategory",
    "tags",
    "description",
    "start_date",
    "due_date",
    "estimated_minutes",
    "actual_minutes",
    "priority",
    "status",
    "progress",
    "is_recurring",
    "recurrence_rule",
    "notes",
    "sort_order",
}


class ValidationError(ValueError):
    pass


class ExclusiveThreadedWSGIServer(ThreadedWSGIServer):
    """Prevent two local Yantu processes from sharing one Windows port."""

    allow_reuse_address = False

    def server_bind(self) -> None:
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def parse_date(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date().isoformat()
    except ValueError as error:
        raise ValidationError(f"{field} must use YYYY-MM-DD") from error


def parse_clock(value: Any, field: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        return datetime.strptime(str(value), "%H:%M").strftime("%H:%M")
    except ValueError as error:
        raise ValidationError(f"{field} must use HH:MM") from error


def normalize_task(payload: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")
    clean: dict[str, Any] = {}
    for key in TASK_FIELDS:
        if key in payload:
            clean[key] = payload[key]

    if not partial or "title" in clean:
        title = str(clean.get("title", "")).strip()
        if not title:
            raise ValidationError("Title is required")
        if len(title) > 160:
            raise ValidationError("Title cannot exceed 160 characters")
        clean["title"] = title

    if not partial or "domain" in clean:
        domain = str(clean.get("domain", "inbox"))
        if domain not in DOMAINS:
            raise ValidationError("Invalid domain")
        clean["domain"] = domain

    if not partial or "task_kind" in clean:
        task_kind = str(clean.get("task_kind") or "standard")
        if task_kind not in {"standard", "free_learning"}:
            raise ValidationError("Invalid task kind")
        clean["task_kind"] = task_kind

    if not partial or "schedule_mode" in clean:
        schedule_mode = str(clean.get("schedule_mode") or "flexible")
        if schedule_mode not in {"flexible", "time_block"}:
            raise ValidationError("Invalid schedule mode")
        clean["schedule_mode"] = schedule_mode

    if not partial or "priority" in clean:
        priority = str(clean.get("priority", "medium"))
        if priority not in PRIORITIES:
            raise ValidationError("Invalid priority")
        clean["priority"] = priority

    if not partial or "status" in clean:
        status = str(clean.get("status", "not_started"))
        if status not in STATUSES:
            raise ValidationError("Invalid status")
        clean["status"] = status

    for field in ("start_date", "due_date", "scheduled_date", "recurrence_until"):
        if field in clean:
            clean[field] = parse_date(clean[field], field)

    for field in ("scheduled_start_time", "scheduled_end_time"):
        if field in clean:
            clean[field] = parse_clock(clean[field], field)

    for field in ("estimated_minutes", "actual_minutes", "sort_order"):
        if field in clean:
            try:
                clean[field] = max(0, int(clean[field] or 0))
            except (TypeError, ValueError) as error:
                raise ValidationError(f"{field} must be a non-negative integer") from error

    if "progress" in clean or not partial:
        try:
            progress = int(clean.get("progress", 0) or 0)
        except (TypeError, ValueError) as error:
            raise ValidationError("Progress must be an integer") from error
        if not 0 <= progress <= 100:
            raise ValidationError("Progress must be between 0 and 100")
        clean["progress"] = progress

    if "tags" in clean:
        tags = clean["tags"]
        if isinstance(tags, str):
            tags = [part.strip() for part in tags.split(",") if part.strip()]
        if not isinstance(tags, list):
            raise ValidationError("Tags must be a list")
        clean["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()][:20]

    for field in ("subcategory", "description", "recurrence_rule", "notes"):
        if field in clean:
            clean[field] = str(clean[field] or "").strip()

    if "is_recurring" in clean:
        clean["is_recurring"] = int(bool(clean["is_recurring"]))

    clean["updated_at"] = utc_now()
    return clean


def validate_schedule(task: dict[str, Any]) -> None:
    start_date = task.get("start_date")
    due_date = task.get("due_date")
    if start_date and due_date and start_date > due_date:
        raise ValidationError("Start date cannot be later than the due date")
    if task.get("task_kind") == "free_learning" and due_date:
        raise ValidationError("自由学习任务不使用截止日期")
    if task.get("schedule_mode") == "time_block":
        scheduled_date = task.get("scheduled_date")
        start_time = task.get("scheduled_start_time")
        end_time = task.get("scheduled_end_time")
        if not scheduled_date or not start_time or not end_time:
            raise ValidationError("时间段任务必须填写日期、开始时间和结束时间")
        if end_time <= start_time:
            raise ValidationError("时间段任务的结束时间必须晚于开始时间")
        if task.get("is_recurring") and task.get("recurrence_rule") != "weekly":
            raise ValidationError("时间段任务当前仅支持每周重复")
        if task.get("is_recurring"):
            recurrence_until = task.get("recurrence_until")
            if not recurrence_until or recurrence_until < scheduled_date:
                raise ValidationError("每周重复任务必须设置不早于首次日期的结束日期")


def create_app(
    db_path: Path | str = DEFAULT_DB_PATH,
    llm_service_factory: ServiceFactory | None = None,
    schedule_ocr_engine=None,
    zotero_service=None,
    focus_habit_service: FocusHabitService | None = None,
    start_activity_monitor: bool = False,
) -> Flask:
    app = Flask(__name__)
    data_directory = Path(db_path).resolve().parent
    appearance_config = data_directory / "appearance.json"
    appearance_directory = data_directory / "appearance"
    task_service = TaskService(db_path)
    schedule_service = ScheduleService(db_path)
    appearance_service = AppearanceService(appearance_config, appearance_directory)
    planning_service = PlanningService(db_path)
    settings_service = SettingsService(db_path)
    habit_service = focus_habit_service or FocusHabitService(db_path)
    focus_service = FocusService(db_path, settings=settings_service, habits=habit_service)
    habit_monitor = FocusHabitMonitor(habit_service)
    if start_activity_monitor:
        habit_monitor.start()
    research_service = ResearchService(db_path)
    project_service = ProjectService(db_path)
    archive_service = ArchiveService(db_path)
    archive_service.prepare(date.today())
    app.config.update(
        DB_PATH=str(db_path),
        JSON_AS_ASCII=False,
        SHUTDOWN_TOKEN=None,
        SERVER_SHUTDOWN=None,
        INSTANCE_ID=None,
        REQUEST_TOKEN=None,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024 + 64 * 1024,
    )
    app.register_blueprint(create_ai_blueprint(db_path, llm_service_factory))
    app.register_blueprint(create_schedule_blueprint(db_path, schedule_ocr_engine))
    app.register_blueprint(create_time_blueprint(db_path))
    app.register_blueprint(create_planning_blueprint(db_path))
    app.extensions["yantu_focus_habit_monitor"] = habit_monitor
    app.extensions["yantu_focus_service"] = focus_service
    app.register_blueprint(create_focus_blueprint(db_path, focus_service, habit_service))
    app.register_blueprint(create_settings_blueprint(db_path, settings_service))
    app.register_blueprint(create_project_blueprint(db_path))
    app.register_blueprint(create_research_blueprint(db_path, zotero_service))
    app.register_blueprint(
        create_appearance_blueprint(appearance_config, appearance_directory)
    )

    @app.before_request
    def protect_local_mutations():
        expected = app.config.get("REQUEST_TOKEN")
        if (
            expected
            and request.path.startswith("/api/")
            and request.path != "/api/shutdown"
            and request.method in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            supplied = request.headers.get("X-Yantu-Token", "")
            if not supplied or not secrets.compare_digest(str(expected), supplied):
                return jsonify({"error": "请求令牌无效，请刷新 Yantu 后重试"}), 403

    @app.after_request
    def prevent_stale_local_assets(response):
        if request.path == "/" or request.path in {"/app.js", "/styles.css", "/theme.css"}:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        html = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
        html = html.replace("__YANTU_REQUEST_TOKEN__", str(app.config.get("REQUEST_TOKEN") or ""))
        return app.response_class(html, mimetype="text/html")

    @app.get("/favicon.ico")
    def favicon():
        return send_from_directory(WEB_ROOT / "assets", "yantu.ico")

    @app.get("/assets/<path:filename>")
    def brand_asset(filename: str):
        if filename not in BRAND_ASSETS:
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(WEB_ROOT / "assets", filename)

    @app.get("/<path:filename>")
    def asset(filename: str):
        if filename not in ASSET_FILES:
            return jsonify({"error": "Not found"}), 404
        return send_from_directory(WEB_ROOT, filename)

    @app.get("/api/health")
    def health():
        return jsonify(
            {
                "status": "ok",
                "app": "Yantu",
                "python": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                "database": str(Path(app.config["DB_PATH"]).resolve()),
                "task_count": task_service.count(),
                "instance_id": app.config.get("INSTANCE_ID"),
            }
        )

    @app.get("/api/archive/periods")
    def archive_periods():
        return jsonify({"format": "yantu.archive.period.v1", "periods": archive_service.list_periods()})

    @app.post("/api/archive/prepare")
    def archive_prepare():
        payload = request.get_json(silent=True) or {}
        try:
            periods = archive_service.prepare(payload.get("date") or date.today().isoformat())
        except ValueError as error:
            raise ValidationError("date must use YYYY-MM-DD") from error
        return jsonify({"periods": periods}), 201

    @app.post("/api/shutdown")
    def shutdown():
        expected = app.config.get("SHUTDOWN_TOKEN")
        supplied = request.headers.get("X-Yantu-Shutdown")
        shutdown_callback = app.config.get("SERVER_SHUTDOWN")
        if not expected or not supplied or not secrets.compare_digest(expected, supplied):
            return jsonify({"error": "Not found"}), 404
        if not callable(shutdown_callback):
            return jsonify({"error": "Shutdown is unavailable"}), 503
        threading.Thread(target=shutdown_callback, daemon=True).start()
        return jsonify({"status": "stopping"})

    @app.get("/api/tasks")
    def tasks_list():
        domain = request.args.get("domain") or None
        status = request.args.get("status") or None
        if domain and domain not in DOMAINS:
            raise ValidationError("Invalid domain filter")
        if status and status not in STATUSES:
            raise ValidationError("Invalid status filter")
        return jsonify({"tasks": task_service.list_records(domain=domain, status=status)})

    @app.get("/api/planning/daily")
    def daily_plan():
        requested_date = request.args.get("date") or datetime.now().date().isoformat()
        try:
            return jsonify(task_service.daily_plan(requested_date))
        except ValueError as error:
            raise ValidationError("date must use YYYY-MM-DD") from error

    @app.post("/api/tasks")
    def tasks_create():
        payload = request.get_json(silent=True) or {}
        research_item_id = str(payload.get("research_item_id") or "").strip()
        clean = normalize_task(payload)
        validate_schedule(clean)
        if clean.get("task_kind") == "free_learning" and not clean.get("estimated_minutes"):
            clean["estimated_minutes"] = 60
        now = utc_now()
        if clean.get("status") == "completed":
            clean["progress"] = 100
            clean["completed_at"] = now
        task = {
            "id": str(uuid.uuid4()),
            "parent_id": clean.get("parent_id"),
            "project_id": clean.get("project_id"),
            "title": clean["title"],
            "domain": clean.get("domain", "inbox"),
            "task_kind": clean.get("task_kind", "standard"),
            "schedule_mode": clean.get("schedule_mode", "flexible"),
            "scheduled_date": clean.get("scheduled_date"),
            "scheduled_start_time": clean.get("scheduled_start_time"),
            "scheduled_end_time": clean.get("scheduled_end_time"),
            "schedule_timezone": clean.get("schedule_timezone", "Asia/Shanghai"),
            "recurrence_until": clean.get("recurrence_until"),
            "subcategory": clean.get("subcategory", ""),
            "tags": clean.get("tags", []),
            "description": clean.get("description", ""),
            "created_at": now,
            "updated_at": now,
            "start_date": clean.get("start_date"),
            "due_date": clean.get("due_date"),
            "estimated_minutes": clean.get("estimated_minutes", 0),
            "actual_minutes": clean.get("actual_minutes", 0),
            "priority": clean.get("priority", "medium"),
            "status": clean.get("status", "not_started"),
            "progress": clean.get("progress", 0),
            "is_recurring": clean.get("is_recurring", 0),
            "recurrence_rule": clean.get("recurrence_rule", ""),
            "notes": clean.get("notes", ""),
            "completed_at": clean.get("completed_at"),
            "sort_order": clean.get("sort_order", 0),
        }
        if research_item_id:
            try:
                linked = research_service.create_linked_task(task, research_item_id)
            except ValueError as exc:
                raise ValidationError(str(exc)) from exc
            return jsonify({"task": linked}), 201
        return jsonify({"task": task_service.create_record(task)}), 201

    @app.get("/api/tasks/<task_id>")
    def tasks_get(task_id: str):
        task = task_service.get_record(task_id)
        if not task:
            return jsonify({"error": "Task not found"}), 404
        return jsonify({"task": task})

    @app.patch("/api/tasks/<task_id>")
    def tasks_update(task_id: str):
        existing = task_service.get_record(task_id)
        if not existing:
            return jsonify({"error": "Task not found"}), 404
        clean = normalize_task(request.get_json(silent=True) or {}, partial=True)
        validate_schedule({**existing, **clean})
        if clean.get("task_kind", existing.get("task_kind")) == "free_learning" and not clean.get("estimated_minutes", existing.get("estimated_minutes")):
            clean["estimated_minutes"] = 60
        resulting_status = clean.get("status", existing["status"])
        if resulting_status == "completed":
            clean["progress"] = 100
            clean["completed_at"] = existing.get("completed_at") or utc_now()
        elif "status" in clean:
            clean["completed_at"] = None
        task = task_service.update_record(task_id, clean)
        assert task is not None
        return jsonify({"task": task})

    @app.delete("/api/tasks/<task_id>")
    def tasks_delete(task_id: str):
        if not task_service.delete(task_id):
            return jsonify({"error": "Task not found"}), 404
        return "", 204

    @app.post("/api/tasks/<task_id>/restore")
    def tasks_restore(task_id: str):
        if not task_service.restore(task_id):
            return jsonify({"error": "Task not found in trash"}), 404
        return "", 204

    @app.delete("/api/tasks/<task_id>/permanent")
    def tasks_permanent_delete(task_id: str):
        if not task_service.delete_permanently(task_id):
            return jsonify({"error": "Task not found in trash"}), 404
        return "", 204

    @app.get("/api/trash")
    def trash_list():
        return jsonify({
            "tasks": task_service.list_deleted_records(),
            "courses": schedule_service.list_courses(deleted=True),
        })

    @app.get("/api/export")
    def export_data():
        return jsonify(
            {
                "version": 13,
                "exported_at": utc_now(),
                "projects": [asdict(project) for project in project_service.list()],
                "tasks": task_service.list_records(),
                "deleted_tasks": task_service.list_deleted_records(),
                "semesters": schedule_service.list_semesters(),
                "courses": [
                    schedule_service.get_course(course["id"], include_deleted=True)
                    for course in (
                        schedule_service.list_courses()
                        + schedule_service.list_courses(deleted=True)
                    )
                ],
                "appearance": appearance_service.export_backup(),
                "planning": planning_service.export_backup(),
                "focus_sessions": focus_service.export_backup(),
                "focus_habits": habit_service.export_backup(),
                "settings": settings_service.export_backup(),
                "research": research_service.export_backup(),
                "archive": archive_service.export_index(),
            }
        )

    @app.post("/api/import")
    def import_data():
        payload = request.get_json(silent=True) or {}
        tasks = payload.get("tasks")
        if not isinstance(tasks, list):
            raise ValidationError("Backup must contain a tasks list")
        projects_imported = 0
        for project in payload.get("projects") or []:
            if not isinstance(project, dict):
                continue
            project_service.import_record(project)
            projects_imported += 1
        imported = 0
        for source in tasks:
            clean = normalize_task(source)
            validate_schedule(clean)
            if clean.get("task_kind") == "free_learning" and not clean.get("estimated_minutes"):
                clean["estimated_minutes"] = 60
            now = utc_now()
            if clean.get("status") == "completed":
                clean["progress"] = 100
                clean["completed_at"] = str(source.get("completed_at") or now)
            task = {
                "id": str(source.get("id") or uuid.uuid4()),
                "parent_id": clean.get("parent_id"),
                "project_id": clean.get("project_id"),
                "title": clean["title"],
                "domain": clean.get("domain", "inbox"),
                "task_kind": clean.get("task_kind", "standard"),
                "schedule_mode": clean.get("schedule_mode", "flexible"),
                "scheduled_date": clean.get("scheduled_date"),
                "scheduled_start_time": clean.get("scheduled_start_time"),
                "scheduled_end_time": clean.get("scheduled_end_time"),
                "schedule_timezone": clean.get("schedule_timezone", "Asia/Shanghai"),
                "recurrence_until": clean.get("recurrence_until"),
                "subcategory": clean.get("subcategory", ""),
                "tags": clean.get("tags", []),
                "description": clean.get("description", ""),
                "created_at": str(source.get("created_at") or now),
                "updated_at": now,
                "start_date": clean.get("start_date"),
                "due_date": clean.get("due_date"),
                "estimated_minutes": clean.get("estimated_minutes", 0),
                "actual_minutes": clean.get("actual_minutes", 0),
                "priority": clean.get("priority", "medium"),
                "status": clean.get("status", "not_started"),
                "progress": clean.get("progress", 0),
                "is_recurring": clean.get("is_recurring", 0),
                "recurrence_rule": clean.get("recurrence_rule", ""),
                "notes": clean.get("notes", ""),
                "completed_at": clean.get("completed_at"),
                "sort_order": clean.get("sort_order", 0),
            }
            if task_service.get_record(task["id"]):
                task.pop("id")
                task.pop("created_at")
                task_service.update_record(str(source["id"]), task)
            else:
                task_service.create_record(task)
            imported += 1
        deleted_imported = 0
        for source in payload.get("deleted_tasks") or []:
            if not isinstance(source, dict):
                continue
            restore_id = str(source.get("id") or uuid.uuid4())
            existing = task_service.get_including_deleted_record(restore_id)
            if not existing:
                clean = normalize_task(source)
                now = utc_now()
                task_service.create_record({
                    "id": restore_id, "title": clean["title"],
                    "domain": clean.get("domain", "inbox"), "subcategory": clean.get("subcategory", ""),
                    "task_kind": clean.get("task_kind", "standard"),
                    "schedule_mode": clean.get("schedule_mode", "flexible"),
                    "scheduled_date": clean.get("scheduled_date"),
                    "scheduled_start_time": clean.get("scheduled_start_time"),
                    "scheduled_end_time": clean.get("scheduled_end_time"),
                    "schedule_timezone": clean.get("schedule_timezone", "Asia/Shanghai"),
                    "recurrence_until": clean.get("recurrence_until"),
                    "tags": clean.get("tags", []), "description": clean.get("description", ""),
                    "created_at": str(source.get("created_at") or now), "updated_at": now,
                    "start_date": clean.get("start_date"), "due_date": clean.get("due_date"),
                    "estimated_minutes": clean.get("estimated_minutes", 0),
                    "actual_minutes": clean.get("actual_minutes", 0), "priority": clean.get("priority", "medium"),
                    "status": clean.get("status", "not_started"), "progress": clean.get("progress", 0),
                    "is_recurring": clean.get("is_recurring", 0), "recurrence_rule": clean.get("recurrence_rule", ""),
                    "notes": clean.get("notes", ""), "completed_at": source.get("completed_at"),
                    "sort_order": clean.get("sort_order", 0),
                })
            task_service.delete(restore_id)
            deleted_imported += 1
        semester_imported = 0
        for semester in payload.get("semesters") or []:
            schedule_service.save_semester(semester, semester_id=str(semester.get("id") or uuid.uuid4()))
            semester_imported += 1
        course_imported = 0
        for course in payload.get("courses") or []:
            if not course or schedule_service.get_course(str(course.get("id") or ""), include_deleted=True):
                continue
            created = schedule_service.create_course(course)
            for meeting in course.get("meetings") or []:
                for exception in meeting.get("exceptions") or []:
                    if exception.get("kind") == "skip":
                        schedule_service.skip_occurrence(
                            meeting["id"],
                            exception.get("occurrence_date"),
                        )
            if course.get("deleted_at"):
                schedule_service.trash_course(created["id"])
            course_imported += 1
        appearance_imported = False
        if isinstance(payload.get("appearance"), dict):
            appearance_service.import_backup(payload["appearance"])
            appearance_imported = True
        planning_result = {"planning_runs_imported": 0}
        if isinstance(payload.get("planning"), dict):
            planning_result = planning_service.import_backup(payload["planning"])
        settings_service.import_backup(payload.get("settings"))
        focus_sessions_imported = focus_service.import_backup(payload.get("focus_sessions"))
        focus_habit_result = habit_service.import_backup(payload.get("focus_habits"))
        research_result = research_service.import_backup(payload.get("research"))
        return jsonify({
            "imported": imported,
            "projects_imported": projects_imported,
            "deleted_imported": deleted_imported,
            "semesters_imported": semester_imported,
            "courses_imported": course_imported,
            "appearance_imported": appearance_imported,
            **planning_result,
            "focus_sessions_imported": focus_sessions_imported,
            **focus_habit_result,
            **research_result,
        })

    @app.errorhandler(ValidationError)
    def validation_error(error: ValidationError):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Not found"}), 404

    @app.errorhandler(413)
    def file_too_large(_error):
        return jsonify({"error": "课表文件不能超过 10 MB"}), 413

    return app


def bind_server(
    app: Flask,
    host: str = "127.0.0.1",
    preferred_port: int = 8765,
    attempts: int = 20,
) -> tuple[BaseWSGIServer, int, list[str]]:
    errors: list[str] = []
    for port in range(preferred_port, preferred_port + attempts):
        bind_output = io.StringIO()
        try:
            with contextlib.redirect_stderr(bind_output):
                server = ExclusiveThreadedWSGIServer(host, port, app)
            return server, int(server.server_port), errors
        except (OSError, SystemExit) as error:
            detail = bind_output.getvalue().strip() or str(error)
            errors.append(f"{host}:{port} -> {detail}")
    bind_output = io.StringIO()
    try:
        with contextlib.redirect_stderr(bind_output):
            server = ExclusiveThreadedWSGIServer(host, 0, app)
        return server, int(server.server_port), errors
    except (OSError, SystemExit) as error:
        detail = bind_output.getvalue().strip() or str(error)
        errors.append(f"{host}:automatic -> {detail}")
        details = os.linesep.join(errors)
        raise RuntimeError(f"No local port could be bound.{os.linesep}{details}") from error


def write_runtime(url: str, port: int, db_path: Path, shutdown_token: str, instance_id: str, runtime_file: Path = RUNTIME_FILE) -> None:
    runtime_file.parent.mkdir(parents=True, exist_ok=True)
    runtime_file.write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "url": url,
                "port": port,
                "database": str(db_path.resolve()),
                "shutdown_token": shutdown_token,
                "instance_id": instance_id,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def wait_and_open(url: str, open_browser: bool, instance_id: str) -> None:
    health_url = f"{url}/api/health"
    for _ in range(80):
        try:
            with urlopen(health_url, timeout=0.5) as response:
                health = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and health.get("instance_id") == instance_id:
                    print(f"Yantu is ready: {url}", flush=True)
                    if open_browser:
                        webbrowser.open(url)
                    return
        except Exception:
            time.sleep(0.1)
    print(f"STARTUP ERROR: health check failed: {health_url}", file=sys.stderr, flush=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the local Yantu server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    if sys.version_info[:2] != (3, 11):
        print(f"STARTUP ERROR: Yantu requires Python 3.11, got {sys.version}", file=sys.stderr)
        return 2
    if args.host != "127.0.0.1":
        print("STARTUP ERROR: Yantu only binds to 127.0.0.1", file=sys.stderr)
        return 2

    db_path = args.db.resolve()
    runtime_file = db_path.parent / "runtime.json"
    app = create_app(db_path, start_activity_monitor=True)
    instance_id = str(uuid.uuid4())
    app.config["INSTANCE_ID"] = instance_id
    app.config["REQUEST_TOKEN"] = secrets.token_urlsafe(32)
    try:
        server, port, bind_errors = bind_server(app, args.host, args.port)
    except RuntimeError as error:
        print(f"STARTUP ERROR: {error}", file=sys.stderr, flush=True)
        return 1

    url = f"http://{args.host}:{port}"
    shutdown_token = secrets.token_urlsafe(32)
    app.config["SHUTDOWN_TOKEN"] = shutdown_token
    app.config["SERVER_SHUTDOWN"] = server.shutdown
    write_runtime(url, port, db_path, shutdown_token, instance_id, runtime_file)
    print(f"Python interpreter: {sys.executable}", flush=True)
    print(f"SQLite database: {db_path}", flush=True)
    if bind_errors:
        print(f"Preferred port was unavailable; using {port}.", flush=True)
        for error in bind_errors:
            print(f"  {error}", flush=True)
    print("Press Ctrl+C or close this window to stop Yantu.", flush=True)

    readiness = threading.Thread(
        target=wait_and_open,
        args=(url, not args.no_browser, instance_id),
        daemon=True,
    )
    readiness.start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping Yantu...", flush=True)
    finally:
        monitor = app.extensions.get("yantu_focus_habit_monitor")
        if monitor:
            monitor.stop()
        server.server_close()
        try:
            runtime = json.loads(runtime_file.read_text(encoding="utf-8"))
            if runtime.get("pid") == os.getpid():
                runtime_file.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
