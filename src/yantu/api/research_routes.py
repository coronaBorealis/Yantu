from __future__ import annotations

from pathlib import Path

from flask import Blueprint, jsonify, request

from ..services.research_service import ResearchService
from ..services.zotero_service import ZoteroService


def create_research_blueprint(
    db_path: Path | str, zotero_service: ZoteroService | None = None
) -> Blueprint:
    blueprint = Blueprint("research", __name__, url_prefix="/api/research")
    service = ResearchService(db_path)
    zotero = zotero_service or ZoteroService(db_path)

    @blueprint.get("/sources")
    def sources_list():
        return jsonify({"sources": zotero.list_connections()})

    @blueprint.post("/sources")
    def sources_save():
        return jsonify({"source": zotero.save_connection(request.get_json(silent=True) or {})}), 201

    @blueprint.post("/sources/<source_id>/test")
    def source_test(source_id: str):
        return jsonify(zotero.test_connection(source_id))

    @blueprint.post("/sources/<source_id>/sync")
    def source_sync(source_id: str):
        return jsonify(zotero.sync(source_id))

    @blueprint.get("/sources/<source_id>/collections")
    def source_collections(source_id: str):
        return jsonify({"collections": zotero.list_collections(source_id)})

    @blueprint.post("/sources/<source_id>/project-import-preview")
    def project_import_preview(source_id: str):
        return jsonify({
            "preview": zotero.preview_project_import(
                source_id, request.get_json(silent=True) or {}
            )
        })

    @blueprint.delete("/sources/<source_id>/key")
    def source_key_delete(source_id: str):
        return jsonify({"source": zotero.delete_key(source_id)})

    @blueprint.get("/items")
    def items_list():
        return jsonify({"items": service.list_items(request.args.get("source_id") or None)})

    @blueprint.post("/items")
    def items_save():
        return jsonify({"item": service.save_item(request.get_json(silent=True) or {})}), 201

    @blueprint.get("/inbox")
    def inbox_list():
        return jsonify({"items": service.list_inbox(request.args.get("status") or "pending")})

    @blueprint.delete("/inbox/<item_id>")
    def inbox_dismiss(item_id: str):
        if not service.dismiss_inbox_item(item_id):
            return jsonify({"error": "科研收件箱条目不存在"}), 404
        return "", 204

    @blueprint.post("/inbox/<item_id>/task-preview")
    def inbox_task_preview(item_id: str):
        return jsonify({
            "preview": service.preview_task(item_id, request.get_json(silent=True) or {})
        })

    @blueprint.post("/inbox/<item_id>/task-confirm")
    def inbox_task_confirm(item_id: str):
        return jsonify(service.confirm_task(item_id, request.get_json(silent=True) or {})), 201

    @blueprint.get("/tasks/<task_id>/items")
    def task_items(task_id: str):
        return jsonify({"items": service.list_task_items(task_id)})

    @blueprint.get("/projects/<project_id>/items")
    def project_items(project_id: str):
        return jsonify({"items": service.list_project_items(project_id)})

    @blueprint.post("/projects/<project_id>/imports")
    def project_import_confirm(project_id: str):
        values = request.get_json(silent=True) or {}
        source_id = str(values.get("source_id") or "")
        if not source_id:
            raise ValueError("请选择 Zotero 来源")
        return jsonify(zotero.confirm_project_import(project_id, source_id, values)), 201

    @blueprint.post("/tasks/<task_id>/items/<item_id>")
    def task_item_link(task_id: str, item_id: str):
        service.link_task(task_id, item_id, request.get_json(silent=True) or {})
        return jsonify({"items": service.list_task_items(task_id)}), 201

    @blueprint.errorhandler(ValueError)
    def invalid_research(error: ValueError):
        return jsonify({"error": str(error)}), 400

    return blueprint
