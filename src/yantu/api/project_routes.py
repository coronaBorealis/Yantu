from __future__ import annotations

from dataclasses import asdict
from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services.project_service import ProjectService


def create_project_blueprint(db_path: Path | str) -> Blueprint:
    blueprint = Blueprint("projects", __name__, url_prefix="/api/projects")
    service = ProjectService(db_path)

    @blueprint.get("")
    def projects_list():
        projects = service.list()
        category = request.args.get("category")
        if category:
            projects = [item for item in projects if item.category.value == category]
        return jsonify({"projects": [asdict(item) for item in projects]})

    @blueprint.post("")
    def projects_create():
        return jsonify({"project": asdict(service.create(request.get_json(silent=True) or {}))}), 201

    @blueprint.get("/<project_id>")
    def projects_get(project_id: str):
        project = service.get(project_id)
        if not project:
            return jsonify({"error": "项目不存在"}), 404
        return jsonify({"project": asdict(project)})

    @blueprint.put("/<project_id>")
    def projects_update(project_id: str):
        project = service.update(project_id, request.get_json(silent=True) or {})
        if not project:
            return jsonify({"error": "项目不存在"}), 404
        return jsonify({"project": asdict(project)})

    @blueprint.delete("/<project_id>")
    def projects_delete(project_id: str):
        if not service.delete(project_id):
            return jsonify({"error": "项目不存在"}), 404
        return "", 204

    @blueprint.errorhandler(ValueError)
    def invalid_project(error: ValueError):
        return jsonify({"error": str(error)}), 400

    return blueprint
