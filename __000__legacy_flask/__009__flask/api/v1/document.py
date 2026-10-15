from flask import Blueprint, current_app, jsonify, request, session

from __003__colpali.local_paths import get_default_indexer_model, resolve_indexer_model
from __008__services import auth as auth_service
from __008__services import document as doc_service
from __008__services import quota as quota_service

document_bp = Blueprint("document", __name__, url_prefix="/document")


@document_bp.get("/")
def list_docs():
    kb_id = request.args.get("kb_id") or session.get("kb_id")
    if not kb_id:
        return jsonify({"code": 400, "message": "缺少 kb_id"}), 400
    return jsonify({"code": 0, "data": doc_service.list_documents(kb_id)})


@document_bp.get("/<doc_id>")
def get_doc(doc_id: str):
    data = doc_service.get_document(doc_id)
    if not data:
        return jsonify({"code": 404, "message": "文档不存在"}), 404
    return jsonify({"code": 0, "data": data})


@document_bp.delete("/<doc_id>")
def remove_doc(doc_id: str):
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        doc_service.delete_document(
            doc_id,
            current_app.config["INDEX_FOLDER"],
            current_app.config["PAGE_IMAGE_FOLDER"],
        )
        return jsonify({"code": 0, "data": True})
    except PermissionError as exc:
        return jsonify({"code": 403, "message": str(exc)}), 403
    except Exception as exc:
        return jsonify({"code": 400, "message": str(exc)}), 400


@document_bp.post("/<doc_id>/cancel")
def cancel_doc(doc_id: str):
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        data = doc_service.cancel_index(doc_id)
        return jsonify({"code": 0, "data": data})
    except PermissionError as exc:
        return jsonify({"code": 403, "message": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"code": 400, "message": str(exc)}), 400


@document_bp.post("/<doc_id>/retry")
def retry_doc(doc_id: str):
    indexer_model = resolve_indexer_model(session.get("indexer_model", get_default_indexer_model()))
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        data = doc_service.retry_index(
            doc_id,
            current_app.config["INDEX_FOLDER"],
            current_app.config["UPLOAD_FOLDER"],
            indexer_model,
        )
        return jsonify({"code": 0, "data": data})
    except PermissionError as exc:
        return jsonify({"code": 403, "message": str(exc)}), 403
    except ValueError as exc:
        return jsonify({"code": 400, "message": str(exc)}), 400


@document_bp.post("/upload")
def upload_docs():
    kb_id = request.form.get("kb_id") or session.get("kb_id")
    if not kb_id:
        return jsonify({"code": 400, "message": "缺少 kb_id"}), 400
    files = request.files.getlist("file")
    indexer_model = resolve_indexer_model(session.get("indexer_model", get_default_indexer_model()))
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        data = doc_service.save_and_enqueue(
            kb_id,
            files,
            current_app.config["UPLOAD_FOLDER"],
            current_app.config["INDEX_FOLDER"],
            indexer_model,
        )
        quota_service.consume(session.get("user_id") or "", "uploads", len(data) or 1)
        return jsonify({"code": 0, "data": data})
    except (ValueError, PermissionError) as exc:
        return jsonify({"code": 400, "message": str(exc)}), 400
