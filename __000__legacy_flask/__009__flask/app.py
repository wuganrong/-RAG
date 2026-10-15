import os

from flask import Flask, flash, jsonify, redirect, render_template, request, send_from_directory, session, url_for
from dotenv import load_dotenv

from __000__common.__001__path import BYALDI_DIR, PAGE_IMAGE_DIR, UPLOAD_DIR, page_relpath, root_dir
from __000__common.__002__log import get_logger
from __000__common.__003__orm.db import init_db
from __003__colpali.local_paths import (
    ensure_local_colpali_ready,
    get_default_indexer_model,
    resolve_indexer_model,
)
from __007__task.worker import start_worker
from __008__services import audit as audit_service
from __008__services import auth as auth_service
from __008__services import conversation as conv_service
from __008__services import document as doc_service
from __008__services import kb as kb_service
from __008__services import quota as quota_service
from __009__flask.api.v1 import v1_bp

load_dotenv()
os.environ["TOKENIZERS_PARALLELISM"] = "false"

BASE_DIR = root_dir
os.chdir(BASE_DIR)

_FLASK_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(_FLASK_DIR, "templates"),
    static_folder=os.path.join(_FLASK_DIR, "static"),
)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-secret")
app.register_blueprint(v1_bp)

logger = get_logger(__name__)

app.config["UPLOAD_FOLDER"] = UPLOAD_DIR
app.config["PAGE_IMAGE_FOLDER"] = PAGE_IMAGE_DIR
app.config["INDEX_FOLDER"] = BYALDI_DIR
os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)
os.makedirs(app.config["PAGE_IMAGE_FOLDER"], exist_ok=True)
os.makedirs(app.config["INDEX_FOLDER"], exist_ok=True)

DEFAULT_INDEXER_MODEL = get_default_indexer_model()
_local_ready = ensure_local_colpali_ready()
if _local_ready:
    logger.info("Using local ColPali indexer: %s", _local_ready)
else:
    logger.warning("Local ColPali not ready; default indexer: %s", DEFAULT_INDEXER_MODEL)

init_db()
auth_service.seed_defaults()
start_worker()
logger.info("Application started with dual-engine RAG.")


def _bootstrap_context(create_conv: bool = True) -> tuple[dict, dict]:
    kbs = kb_service.list_kbs()
    if not kbs:
        current_kb = kb_service.ensure_default_kb()
    else:
        kb_id = session.get("kb_id")
        current_kb = next((item for item in kbs if item["id"] == kb_id), None) or kbs[0]
    session["kb_id"] = current_kb["id"]

    convs = conv_service.list_conversations(current_kb["id"])
    conv_id = session.get("session_id")
    current_conv = next((item for item in convs if item["id"] == conv_id), None)
    if current_conv is None and create_conv:
        current_conv = conv_service.create_conversation(
            current_kb["id"],
            "新会话",
            user_id=session.get("user_id") or "local",
        )
    if current_conv is None:
        session.pop("session_id", None)
        return current_kb, {"id": "", "name": "新会话", "kb_id": current_kb["id"]}
    session["session_id"] = current_conv["id"]
    return current_kb, current_conv


def _shell(nav: str, extra: dict | None = None) -> dict:
    current_kb, current_conv = _bootstrap_context(create_conv=(nav == "chat"))
    payload = {
        "nav": nav,
        "current_kb": current_kb,
        "knowledge_bases": kb_service.list_kbs(),
        "chat_sessions": conv_service.list_conversations(current_kb["id"]),
        "current_session": current_conv["id"],
        "quota": quota_service.snapshot(session.get("user_id") or ""),
    }
    if extra:
        payload.update(extra)
    return payload


_OPEN_ENDPOINTS = {"login", "logout", "health", "static", "page_image"}


@app.before_request
def make_session_permanent():
    session.permanent = True
    if request.endpoint in _OPEN_ENDPOINTS or (request.endpoint or "").startswith("static"):
        return None
    if not session.get("user_id"):
        if request.path.startswith("/v1/") or request.is_json:
            return jsonify({"code": 401, "message": "请先登录"}), 401
        return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        user = auth_service.authenticate(request.form.get("username") or "", request.form.get("password") or "")
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            audit_service.write(user["id"], "login", user["username"])
            return redirect(url_for("chat"))
        error = "用户名或密码错误"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/health")
def health():
    from __000__common.__004__infra import ES_HOSTS, REDIS_HOST, REDIS_PORT, minio_endpoint

    payload = {
        "ok": True,
        "colpali": bool(_local_ready),
        "dashscope": bool(os.getenv("DASHSCOPE_API_KEY")),
        "redis": {"host": f"{REDIS_HOST}:{REDIS_PORT}"},
        "elasticsearch": {"hosts": ES_HOSTS},
        "minio": {"endpoint": minio_endpoint()},
    }
    if request.args.get("probe") == "1":
        from __004__store.cache.redis_cache import health as redis_health
        from __004__store.search.es_store import health as es_health
        from __004__store.storage.factory import storage as object_storage

        payload["redis"] = redis_health(retry=True)
        payload["elasticsearch"] = es_health(retry=True)
        payload["minio"] = object_storage.health(retry=True)
    return jsonify(payload)


@app.route("/media/pages/<path:filename>")
def page_image(filename):
    return send_from_directory(app.config["PAGE_IMAGE_FOLDER"], page_relpath(filename))


@app.route("/", methods=["GET"])
def home():
    return redirect(url_for("chat"))


@app.route("/chat", methods=["GET", "POST"])
def chat():
    current_kb, current_conv = _bootstrap_context()
    session_id = current_conv["id"]
    conv = conv_service.get_conversation(session_id) or {"messages": [], "name": current_conv["name"]}
    chat_history = conv.get("messages") or []
    session_name = conv.get("name") or "新会话"
    indexed_files = doc_service.indexed_names(current_kb["id"])

    if request.method == "POST":
        if "upload" in request.form:
            files = request.files.getlist("file")
            if not files:
                return jsonify({"success": False, "message": "没有选择文件"})
            try:
                auth_service.require_role(session.get("role") or "viewer", "editor")
                quota_service.consume(session["user_id"], "uploads", len(files))
                docs = doc_service.save_and_enqueue(
                    current_kb["id"],
                    files,
                    app.config["UPLOAD_FOLDER"],
                    app.config["INDEX_FOLDER"],
                    resolve_indexer_model(session.get("indexer_model", DEFAULT_INDEXER_MODEL)),
                )
                audit_service.write(session.get("user_id") or "", "upload", current_kb["id"], f"{len(docs)} files")
                return jsonify(
                    {
                        "success": True,
                        "async": True,
                        "message": "已提交建索任务，请等待进度完成后再提问。",
                        "documents": docs,
                        "indexed_files": [item["name"] for item in docs],
                    }
                )
            except PermissionError as exc:
                return jsonify({"success": False, "message": str(exc)})
            except Exception as exc:
                logger.error("Upload/index enqueue failed: %s", exc, exc_info=True)
                return jsonify({"success": False, "message": str(exc)})

        if "send_query" in request.form:
            query = (request.form.get("query") or "").strip()
            try:
                result = conv_service.ask(
                    session_id,
                    query,
                    app.config["INDEX_FOLDER"],
                    app.config["PAGE_IMAGE_FOLDER"],
                    int(session.get("resized_height", 280)),
                    int(session.get("resized_width", 280)),
                    session.get("generation_model", "qwen"),
                )
                new_messages_html = render_template(
                    "chat_messages.html",
                    messages=[
                        {"role": "user", "content": query},
                        {
                            "role": "assistant",
                            "content": result["answer_html"],
                            "images": result["images"],
                            "citations": result["citations"],
                        },
                    ],
                )
                quota_service.consume(session["user_id"], "queries")
                return jsonify({"success": True, "html": new_messages_html, "session_name": result["session_name"]})
            except Exception as exc:
                logger.error("Ask failed: %s", exc, exc_info=True)
                return jsonify({"success": False, "message": str(exc)})

    return render_template(
        "chat.html",
        **_shell(
            "chat",
            {
                "chat_history": chat_history,
                "session_name": session_name,
                "indexed_files": indexed_files,
                "model_choice": session.get("generation_model", "qwen"),
                "resized_height": session.get("resized_height", 280),
                "resized_width": session.get("resized_width", 280),
            },
        ),
    )


@app.route("/switch_session/<session_id>")
def switch_session(session_id):
    session["session_id"] = session_id
    conv = conv_service.get_conversation(session_id)
    if conv:
        session["kb_id"] = conv["kb_id"]
    flash("已切换会话。", "info")
    return redirect(url_for("chat"))


@app.route("/switch_kb/<kb_id>")
def switch_kb(kb_id):
    session["kb_id"] = kb_id
    session.pop("session_id", None)
    flash("已切换知识库。", "info")
    return redirect(url_for("chat"))


@app.route("/rename_session", methods=["POST"])
def rename_session():
    session_id = request.form.get("session_id")
    new_name = request.form.get("new_session_name", "未命名会话")
    try:
        conv_service.rename_conversation(session_id, new_name)
        return jsonify({"success": True, "message": "Session name updated."})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)})


@app.route("/delete_session/<session_id>", methods=["POST"])
def delete_session(session_id):
    try:
        conv_service.delete_conversation(session_id)
        if session.get("session_id") == session_id:
            session.pop("session_id", None)
        return jsonify({"success": True, "message": "Session deleted successfully."})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)})


@app.route("/new_session")
def new_session():
    current_kb, _ = _bootstrap_context(create_conv=False)
    created = conv_service.create_conversation(
        current_kb["id"],
        "新会话",
        user_id=session.get("user_id") or "local",
    )
    session["session_id"] = created["id"]
    flash("已新建会话。", "success")
    return redirect(url_for("chat"))


@app.route("/create_kb", methods=["POST"])
def create_kb():
    name = (request.form.get("name") or "").strip()
    rag_mode = request.form.get("rag_mode") or "vision"
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        data = kb_service.create_kb(name, rag_mode=rag_mode)
        session["kb_id"] = data["id"]
        session.pop("session_id", None)
        return jsonify({"success": True, "data": data})
    except PermissionError as exc:
        return jsonify({"success": False, "message": str(exc)})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)})


@app.route("/settings", methods=["GET", "POST"])
def settings():
    current_kb, _ = _bootstrap_context(create_conv=False)
    if request.method == "POST":
        session["indexer_model"] = request.form.get("indexer_model", DEFAULT_INDEXER_MODEL)
        session["generation_model"] = request.form.get("generation_model", "qwen")
        session["resized_height"] = request.form.get("resized_height", 280)
        session["resized_width"] = request.form.get("resized_width", 280)
        kb_service.update_kb_and_reindex(
            current_kb["id"],
            app.config["INDEX_FOLDER"],
            app.config["UPLOAD_FOLDER"],
            resolve_indexer_model(session.get("indexer_model", DEFAULT_INDEXER_MODEL)),
            rag_mode=request.form.get("rag_mode"),
            top_n=request.form.get("top_n"),
            page_top_n=request.form.get("page_top_n"),
            similarity_threshold=request.form.get("similarity_threshold"),
            embd_id=request.form.get("embd_id"),
            chat_id=request.form.get("chat_id"),
            vlm_id=request.form.get("vlm_id"),
            parser_id=request.form.get("parser_id"),
            chunker_id=request.form.get("chunker_id"),
        )
        session.modified = True
        audit_service.write(session.get("user_id") or "", "update_params", current_kb["id"])
        flash("参数已保存。若检索模式有变，已按新模式重建索引。", "success")
        return redirect(url_for("settings"))
    return render_template(
        "settings.html",
        **_shell(
            "params",
            {
                "indexer_model": session.get("indexer_model", DEFAULT_INDEXER_MODEL),
                "generation_model": session.get("generation_model", "qwen"),
                "resized_height": session.get("resized_height", 280),
                "resized_width": session.get("resized_width", 280),
                "local_indexer_model": DEFAULT_INDEXER_MODEL,
                "rag_mode": current_kb.get("rag_mode", "vision"),
            },
        ),
    )


@app.route("/documents", methods=["GET", "POST"])
def documents():
    current_kb, _ = _bootstrap_context(create_conv=False)
    if request.method == "POST":
        files = request.files.getlist("file")
        if not files:
            return jsonify({"success": False, "message": "没有选择文件"})
        try:
            auth_service.require_role(session.get("role") or "viewer", "editor")
            quota_service.consume(session["user_id"], "uploads", len(files))
            docs = doc_service.save_and_enqueue(
                current_kb["id"],
                files,
                app.config["UPLOAD_FOLDER"],
                app.config["INDEX_FOLDER"],
                resolve_indexer_model(session.get("indexer_model", DEFAULT_INDEXER_MODEL)),
            )
            audit_service.write(session.get("user_id") or "", "upload", current_kb["id"], f"{len(docs)} files")
            return jsonify({"success": True, "documents": docs, "message": "已提交建索任务"})
        except Exception as exc:
            return jsonify({"success": False, "message": str(exc)})
    files = doc_service.list_documents(current_kb["id"])
    return render_template(
        "documents.html",
        **_shell(
            "documents",
            {
                "documents": files,
                "run_labels": {"0": "待建索", "1": "已完成", "2": "建索中", "3": "已取消", "-1": "失败"},
            },
        ),
    )


@app.route("/cancel_document/<doc_id>", methods=["POST"])
def cancel_document(doc_id):
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        data = doc_service.cancel_index(doc_id)
        audit_service.write(session.get("user_id") or "", "cancel_index", doc_id)
        return jsonify({"success": True, "document": data})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)})


@app.route("/retry_document/<doc_id>", methods=["POST"])
def retry_document(doc_id):
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        data = doc_service.retry_index(
            doc_id,
            app.config["INDEX_FOLDER"],
            app.config["UPLOAD_FOLDER"],
            resolve_indexer_model(session.get("indexer_model", DEFAULT_INDEXER_MODEL)),
        )
        audit_service.write(session.get("user_id") or "", "retry_index", doc_id)
        return jsonify({"success": True, "document": data})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)})


@app.route("/ops")
def ops():
    from __000__common.__004__infra import ES_HOSTS, REDIS_HOST, REDIS_PORT, minio_endpoint

    health_payload = {
        "colpali": bool(_local_ready),
        "dashscope": bool(os.getenv("DASHSCOPE_API_KEY")),
        "redis": f"{REDIS_HOST}:{REDIS_PORT}",
        "elasticsearch": ES_HOSTS,
        "minio": minio_endpoint(),
    }
    return render_template(
        "ops.html",
        **_shell(
            "ops",
            {
                "health": health_payload,
                "audits": audit_service.list_recent(20),
            },
        ),
    )


@app.route("/get_indexed_files/<session_id>")
def get_indexed_files(session_id):
    conv = conv_service.get_conversation(session_id)
    kb_id = conv["kb_id"] if conv else session.get("kb_id")
    files = doc_service.list_documents(kb_id) if kb_id else []
    return jsonify(
        {
            "success": True,
            "indexed_files": [
                f"{item['name']}  [{item['run']}]  {item.get('progress_msg') or ''}"
                for item in files
            ],
            "documents": files,
        }
    )


@app.route("/delete_kb/<kb_id>", methods=["POST"])
def delete_kb(kb_id):
    try:
        auth_service.require_role(session.get("role") or "viewer", "owner")
        kb_service.delete_kb(kb_id, app.config["INDEX_FOLDER"], app.config["PAGE_IMAGE_FOLDER"])
        if session.get("kb_id") == kb_id:
            session.pop("kb_id", None)
            session.pop("session_id", None)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)})


@app.route("/delete_document/<doc_id>", methods=["POST"])
def delete_document(doc_id):
    try:
        auth_service.require_role(session.get("role") or "viewer", "editor")
        doc_service.delete_document(doc_id, app.config["INDEX_FOLDER"], app.config["PAGE_IMAGE_FOLDER"])
        audit_service.write(session.get("user_id") or "", "delete_document", doc_id)
        return jsonify({"success": True})
    except Exception as exc:
        return jsonify({"success": False, "message": str(exc)})


@app.route("/document_status/<doc_id>")
def document_status(doc_id):
    data = doc_service.get_document(doc_id)
    if not data:
        return jsonify({"success": False, "message": "文档不存在"}), 404
    return jsonify({"success": True, "document": data})


if __name__ == "__main__":
    app.run(port=5050, debug=True, use_reloader=False)
