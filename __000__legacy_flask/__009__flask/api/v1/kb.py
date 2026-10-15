from flask import Blueprint, jsonify, request, session

from __008__services import auth as auth_service
from __008__services import kb as kb_service

kb_bp = Blueprint("kb", __name__, url_prefix="/kb")


@kb_bp.get("/")
def list_kb():
    return jsonify({"code": 0, "data": kb_service.list_kbs()})


@kb_bp.post("/")
def create_kb():
    payload = request.get_json(silent=True) or {}
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        data = kb_service.create_kb(
            name=payload.get("name") or "",
            rag_mode=payload.get("rag_mode") or "vision",
            description=payload.get("description") or "",
        )
        return jsonify({"code": 0, "data": data})
    except PermissionError as exc:
        return jsonify({"code": 403, "message": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"code": 400, "message": str(exc)}), 400


@kb_bp.delete("/<kb_id>")
def remove_kb(kb_id: str):
    from flask import current_app

    try:
        auth_service.require_role(session.get("role") or "viewer", "owner")
        kb_service.delete_kb(kb_id, current_app.config["INDEX_FOLDER"], current_app.config["PAGE_IMAGE_FOLDER"])
        return jsonify({"code": 0, "data": True})
    except PermissionError as exc:
        return jsonify({"code": 403, "message": str(exc)}), 403


@kb_bp.patch("/<kb_id>")
def patch_kb(kb_id: str):
    from flask import current_app

    payload = request.get_json(silent=True) or {}
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        data = kb_service.update_kb_and_reindex(
            kb_id,
            current_app.config["INDEX_FOLDER"],
            current_app.config["UPLOAD_FOLDER"],
            **payload,
        )
        return jsonify({"code": 0, "data": data})
    except PermissionError as exc:
        return jsonify({"code": 403, "message": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"code": 400, "message": str(exc)}), 400
