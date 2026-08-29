from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services.planning_service import PlanningService


def create_planning_blueprint(db_path: Path | str) -> Blueprint:
    blueprint = Blueprint("planning", __name__, url_prefix="/api/planning")
    planning = PlanningService(db_path)

    @blueprint.get("/profile")
    def profile_get():
        return jsonify({"profile": planning.get_profile()})

    @blueprint.put("/profile")
    def profile_put():
        return jsonify({"profile": planning.update_profile(request.get_json(silent=True) or {})})

    @blueprint.post("/preview")
    def plan_preview():
        return jsonify({"preview": planning.preview(request.get_json(silent=True) or {})})

    @blueprint.post("/confirm")
    def plan_confirm():
        return jsonify({"plan": planning.confirm(request.get_json(silent=True) or {})}), 201

    @blueprint.get("/plans")
    def plans_list():
        value = request.args.get("date")
        if not value:
            raise ValueError("date 不能为空")
        return jsonify(planning.plan_state_for_date(value))

    @blueprint.get("/tasks/<task_id>/preference")
    def task_preference_get(task_id: str):
        return jsonify({"preference": planning.get_task_preference(task_id)})

    @blueprint.put("/tasks/<task_id>/preference")
    def task_preference_put(task_id: str):
        return jsonify({
            "preference": planning.update_task_preference(
                task_id, request.get_json(silent=True) or {}
            )
        })

    @blueprint.errorhandler(ValueError)
    def invalid_planning(error: ValueError):
        return jsonify({"error": str(error)}), 400

    return blueprint
