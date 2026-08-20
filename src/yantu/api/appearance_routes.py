from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request, send_file

from ..services.appearance_service import AppearanceService


def create_appearance_blueprint(config_path: Path, background_dir: Path) -> Blueprint:
    blueprint = Blueprint("appearance", __name__, url_prefix="/api/appearance")
    appearance = AppearanceService(config_path, background_dir)

    @blueprint.get("")
    def appearance_get():
        return jsonify({"appearance": appearance.get()})

    @blueprint.put("")
    def appearance_put():
        return jsonify({"appearance": appearance.save(request.get_json(silent=True) or {})})

    @blueprint.post("/background")
    def background_post():
        uploaded = request.files.get("file")
        if not uploaded or not uploaded.filename:
            raise ValueError("请选择背景图片")
        if request.content_length and request.content_length > 8 * 1024 * 1024 + 64 * 1024:
            raise ValueError("背景图片不能超过 8 MB")
        saved = appearance.save_background(
            uploaded.filename, uploaded.mimetype or "", uploaded.read(8 * 1024 * 1024 + 1)
        )
        return jsonify({"appearance": saved}), 201

    @blueprint.get("/background")
    def background_get():
        path = appearance.background_path()
        if not path:
            return jsonify({"error": "Background not found"}), 404
        response = send_file(path, conditional=True)
        response.headers["Cache-Control"] = "private, max-age=3600"
        return response

    @blueprint.delete("/background")
    def background_delete():
        return jsonify({"appearance": appearance.delete_background()})

    @blueprint.errorhandler(ValueError)
    def invalid_appearance(error: ValueError):
        return jsonify({"error": str(error)}), 400

    return blueprint
