from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services.focus_service import FocusService


def create_focus_blueprint(db_path: Path | str, service: FocusService | None = None) -> Blueprint:
    blueprint = Blueprint("focus", __name__, url_prefix="/api/focus")
    focus = service or FocusService(db_path)

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
        return jsonify({"session": focus.cancel(session_id, record_partial=bool(payload.get("record_partial")))})

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
