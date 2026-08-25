from __future__ import annotations

from pathlib import Path
from typing import Callable

from flask import Blueprint, jsonify, request

from ..ai.llm_service import LLMAPIError, LLMConfigurationError, LLMResponseError, LLMService
from ..ai.schemas import SchemaValidationError
from ..services.task_breakdown_service import TaskBreakdownService


ServiceFactory = Callable[[], LLMService]


def create_ai_blueprint(db_path: Path | str, service_factory: ServiceFactory | None = None) -> Blueprint:
    blueprint = Blueprint("ai", __name__, url_prefix="/api/ai")

    def service() -> TaskBreakdownService:
        llm = service_factory() if service_factory else LLMService.from_settings(db_path)
        return TaskBreakdownService(db_path, llm)

    @blueprint.get("/status")
    def status():
        try:
            return jsonify(service().llm_service.status())
        except LLMConfigurationError as exc:
            return jsonify({"configured": False, "error": str(exc)}), 503

    @blueprint.post("/breakdown/preview")
    def preview():
        payload = request.get_json(silent=True) or {}
        task = payload.get("task")
        if not isinstance(task, str) or not task.strip():
            return jsonify({"error": "请输入需要拆解的任务"}), 400
        try:
            breakdown = service().preview(task.strip())
            return jsonify({"breakdown": breakdown.to_dict()})
        except LLMConfigurationError as exc:
            return jsonify({"error": str(exc)}), 503
        except (LLMAPIError, LLMResponseError) as exc:
            return jsonify({"error": str(exc)}), 502

    @blueprint.post("/breakdown/confirm")
    def confirm():
        payload = request.get_json(silent=True) or {}
        try:
            tasks = service().confirm(payload.get("breakdown", {}), payload.get("domain", "research"))
            return jsonify({"tasks": tasks}), 201
        except (SchemaValidationError, ValueError) as exc:
            return jsonify({"error": str(exc)}), 400

    return blueprint
