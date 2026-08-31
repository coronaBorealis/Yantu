from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services.focus_service import FocusService
from ..services.focus_habit_service import FocusHabitService


def create_focus_blueprint(
    db_path: Path | str,
    service: FocusService | None = None,
    habit_service: FocusHabitService | None = None,
) -> Blueprint:
    blueprint = Blueprint("focus", __name__, url_prefix="/api/focus")
    habits = habit_service or (service.habits if service else None) or FocusHabitService(db_path)
    focus = service or FocusService(db_path, habits=habits)

    @blueprint.get("/active")
    def active():
        return jsonify({"session": focus.active()})

    @blueprint.post("/sessions")
    def start():
        return jsonify({"session": focus.start(request.get_json(silent=True) or {})}), 201

    @blueprint.post("/sessions/<session_id>/pause")
    def pause(session_id: str):
        return jsonify({"session": focus.pause(session_id)})

    @blueprint.post("/sessions/<session_id>/resume")
    def resume(session_id: str):
        return jsonify({"session": focus.resume(session_id)})

    @blueprint.post("/sessions/<session_id>/complete")
    def complete(session_id: str):
        return jsonify(focus.complete(session_id))

    @blueprint.post("/sessions/<session_id>/cancel")
    def cancel(session_id: str):
        payload = request.get_json(silent=True) or {}
        return jsonify(focus.cancel(session_id, record_partial=bool(payload.get("record_partial"))))

    @blueprint.get("/habits/capability")
    def habit_capability():
        return jsonify({"capability": habits.capability()})

    @blueprint.get("/habits/current-app")
    def current_app():
        return jsonify({"activity": habits.current_app()})

    @blueprint.get("/habits")
    def habit_profiles():
        return jsonify({"profiles": habits.list_profiles()})

    @blueprint.get("/habits/stats")
    def habit_stats():
        return jsonify({"stats": habits.stats(
            start=request.args.get("start"), end=request.args.get("end")
        )})

    @blueprint.post("/habits")
    def create_habit_profile():
        return jsonify({"profile": habits.save_profile(request.get_json(silent=True) or {})}), 201

    @blueprint.put("/habits/<profile_id>")
    def update_habit_profile(profile_id: str):
        return jsonify({"profile": habits.save_profile(request.get_json(silent=True) or {}, profile_id)})

    @blueprint.delete("/habits/<profile_id>")
    def disable_habit_profile(profile_id: str):
        if not habits.disable_profile(profile_id):
            return jsonify({"error": "专注习惯方案不存在或已停用"}), 404
        return "", 204

    @blueprint.get("/sessions/<session_id>/habit")
    def habit_session(session_id: str):
        # UI polling doubles as a safe sampling fallback. The desktop/background
        # monitor still covers collapsed panels, while source/test deployments no
        # longer appear to have a selected habit that never records activity.
        return jsonify({"habit": habits.sample_session(session_id)})

    @blueprint.get("/history")
    def history():
        return jsonify({"sessions": focus.history(
            start=request.args.get("start"), end=request.args.get("end"),
            task_id=request.args.get("task_id") or None,
        )})

    @blueprint.get("/stats")
    def stats():
        return jsonify({"stats": focus.stats(start=request.args.get("start"), end=request.args.get("end"))})

    @blueprint.errorhandler(ValueError)
    def invalid(error: ValueError):
        return jsonify({"error": str(error)}), 400

    return blueprint
