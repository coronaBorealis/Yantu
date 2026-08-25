from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services.settings_service import SettingsService


def create_settings_blueprint(db_path: Path | str, service: SettingsService | None = None) -> Blueprint:
    blueprint = Blueprint("settings", __name__, url_prefix="/api/settings")
    settings = service or SettingsService(db_path)

    @blueprint.get("/ai")
    def ai_get():
        return jsonify({"ai": settings.get_ai()})

    @blueprint.put("/ai")
    def ai_put():
        return jsonify({"ai": settings.update_ai(request.get_json(silent=True) or {})})

    @blueprint.post("/ai/test")
    def ai_test():
        return jsonify(settings.test_ai())

    @blueprint.delete("/ai/key")
    def ai_delete():
        return jsonify({"ai": settings.delete_ai_key()})

    @blueprint.get("/preferences")
    def preferences_get():
        return jsonify({"preferences": settings.get_preferences()})

    @blueprint.put("/preferences")
    def preferences_put():
        return jsonify({"preferences": settings.update_preferences(request.get_json(silent=True) or {})})

    @blueprint.errorhandler(ValueError)
    def invalid(error: ValueError):
        return jsonify({"error": str(error)}), 400

    return blueprint
