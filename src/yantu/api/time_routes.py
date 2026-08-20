from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services.time_entry_service import TimeEntryService


def create_time_blueprint(db_path: Path | str) -> Blueprint:
    blueprint = Blueprint("time_entries", __name__, url_prefix="/api/time-entries")
    entries = TimeEntryService(db_path)

    @blueprint.get("")
    def entries_list():
        return jsonify({
            "time_entries": [
                asdict(entry)
                for entry in entries.list(task_id=request.args.get("task_id") or None)
            ]
        })

    @blueprint.post("")
    def entries_create():
        return jsonify({"time_entry": asdict(entries.create(request.get_json(silent=True) or {}))}), 201

    @blueprint.patch("/<entry_id>")
    def entries_update(entry_id: str):
        entry = entries.update(entry_id, request.get_json(silent=True) or {})
        if not entry:
            return jsonify({"error": "Time entry not found"}), 404
        return jsonify({"time_entry": asdict(entry)})

    @blueprint.delete("/<entry_id>")
    def entries_delete(entry_id: str):
        if not entries.delete(entry_id):
            return jsonify({"error": "Time entry not found"}), 404
        return "", 204

    @blueprint.errorhandler(ValueError)
    def invalid_time_entry(error: ValueError):
        return jsonify({"error": str(error)}), 400

    return blueprint
