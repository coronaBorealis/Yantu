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
from datetime import datetime, timezone
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
from .database.config import DEFAULT_DB_PATH
from .database.constants import DOMAINS, PRIORITIES, STATUSES
from .services.task_service import TaskService


RUNTIME_FILE = REPOSITORY_ROOT / "data" / "runtime.json"
ASSET_FILES = {"styles.css", "app.js"}
TASK_FIELDS = {
    "parent_id",
    "project_id",
    "title",
    "domain",
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

    for field in ("start_date", "due_date"):
        if field in clean:
            clean[field] = parse_date(clean[field], field)

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


def create_app(
    db_path: Path | str = DEFAULT_DB_PATH,
    llm_service_factory: ServiceFactory | None = None,
) -> Flask:
    app = Flask(__name__)
    task_service = TaskService(db_path)
    app.config.update(
        DB_PATH=str(db_path),
        JSON_AS_ASCII=False,
        SHUTDOWN_TOKEN=None,
        SERVER_SHUTDOWN=None,
        INSTANCE_ID=None,
    )
    app.register_blueprint(create_ai_blueprint(db_path, llm_service_factory))

    @app.after_request
    def prevent_stale_local_assets(response):
        if request.path == "/" or request.path in {"/app.js", "/styles.css"}:
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif request.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/")
    def index():
        return send_from_directory(WEB_ROOT, "index.html")

    @app.get("/favicon.ico")
    def favicon():
        return "", 204

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

    @app.post("/api/tasks")
    def tasks_create():
        clean = normalize_task(request.get_json(silent=True) or {})
        validate_schedule(clean)
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

    @app.get("/api/export")
    def export_data():
        return jsonify(
            {
                "version": 2,
                "exported_at": utc_now(),
                "tasks": task_service.list_records(),
            }
        )

    @app.post("/api/import")
    def import_data():
        payload = request.get_json(silent=True) or {}
        tasks = payload.get("tasks")
        if not isinstance(tasks, list):
            raise ValidationError("Backup must contain a tasks list")
        imported = 0
        for source in tasks:
            clean = normalize_task(source)
            validate_schedule(clean)
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
        return jsonify({"imported": imported})

    @app.errorhandler(ValidationError)
    def validation_error(error: ValidationError):
        return jsonify({"error": str(error)}), 400

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify({"error": "Not found"}), 404

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


def write_runtime(url: str, port: int, db_path: Path, shutdown_token: str, instance_id: str) -> None:
    RUNTIME_FILE.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_FILE.write_text(
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
    app = create_app(db_path)
    instance_id = str(uuid.uuid4())
    app.config["INSTANCE_ID"] = instance_id
    try:
        server, port, bind_errors = bind_server(app, args.host, args.port)
    except RuntimeError as error:
        print(f"STARTUP ERROR: {error}", file=sys.stderr, flush=True)
        return 1

    url = f"http://{args.host}:{port}"
    shutdown_token = secrets.token_urlsafe(32)
    app.config["SHUTDOWN_TOKEN"] = shutdown_token
    app.config["SERVER_SHUTDOWN"] = server.shutdown
    write_runtime(url, port, db_path, shutdown_token, instance_id)
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
        server.server_close()
        try:
            runtime = json.loads(RUNTIME_FILE.read_text(encoding="utf-8"))
            if runtime.get("pid") == os.getpid():
                RUNTIME_FILE.unlink(missing_ok=True)
        except (OSError, json.JSONDecodeError):
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
