import json

from flask import Blueprint, Response, current_app, jsonify, request, session

from __008__services import conversation as conv_service
from __008__services import quota as quota_service

conversation_bp = Blueprint("conversation", __name__, url_prefix="/conversation")


@conversation_bp.get("/")
def list_conv():
    kb_id = request.args.get("kb_id") or session.get("kb_id")
    return jsonify({"code": 0, "data": conv_service.list_conversations(kb_id)})


@conversation_bp.post("/")
def create_conv():
    payload = request.get_json(silent=True) or {}
    kb_id = payload.get("kb_id") or session.get("kb_id")
    try:
        data = conv_service.create_conversation(
            kb_id,
            payload.get("name") or "新会话",
            user_id=session.get("user_id") or "local",
        )
        return jsonify({"code": 0, "data": data})
    except ValueError as exc:
        return jsonify({"code": 400, "message": str(exc)}), 400


@conversation_bp.post("/<conv_id>/completion")
def complete(conv_id: str):
    payload = request.get_json(silent=True) or request.form.to_dict() or {}
    query = (payload.get("query") or "").strip()
    if not query:
        return jsonify({"code": 400, "message": "问题不能为空"}), 400
    user_id = session.get("user_id") or ""
    generation_model = session.get("generation_model", "qwen")
    resized_height = int(session.get("resized_height", 280))
    resized_width = int(session.get("resized_width", 280))

    if payload.get("stream") in {True, "true", "1"}:
        def generate():
            consumed = False
            try:
                for event in conv_service.ask_stream(
                    conv_id,
                    query,
                    current_app.config["INDEX_FOLDER"],
                    current_app.config["PAGE_IMAGE_FOLDER"],
                    generation_model,
                    resized_height,
                    resized_width,
                ):
                    if event.get("event") == "citations" and not consumed:
                        quota_service.consume(user_id, "queries")
                        consumed = True
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
            except Exception as exc:
                yield f"data: {json.dumps({'event': 'error', 'message': str(exc)}, ensure_ascii=False)}\n\n"

        return Response(generate(), mimetype="text/event-stream")
    try:
        data = conv_service.ask(
            conv_id,
            query,
            current_app.config["INDEX_FOLDER"],
            current_app.config["PAGE_IMAGE_FOLDER"],
            resized_height,
            resized_width,
            generation_model,
        )
        quota_service.consume(user_id, "queries")
        return jsonify({"code": 0, "data": data})
    except ValueError as exc:
        return jsonify({"code": 400, "message": str(exc)}), 400
