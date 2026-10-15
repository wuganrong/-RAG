from __future__ import annotations

import hashlib
import os

from werkzeug.utils import secure_filename

from __000__common.__003__orm.db import session_scope
from __000__common.__003__orm.ids import new_id
from __000__common.__003__orm.models import (
    RAG_HYBRID,
    RAG_TEXT,
    RAG_VISION,
    RUN_CANCEL,
    RUN_DONE,
    RUN_RUNNING,
    Document,
    Knowledgebase,
)
from __003__colpali.index.vision_index import drop_vision_index, rebuild_from_files
from __004__store.storage.factory import storage
from __007__task.worker import enqueue_index, resolve_modes


def save_and_enqueue(
    kb_id: str,
    files,
    upload_root: str,
    index_root: str,
    indexer_model: str | None = None,
) -> list[dict]:
    saved = []
    kb_folder = os.path.join(upload_root, kb_id)
    os.makedirs(kb_folder, exist_ok=True)
    with session_scope() as session:
        kb = session.get(Knowledgebase, kb_id)
        if kb is None or kb.status != "1":
            raise ValueError("知识库不存在或已禁用")
        for file in files:
            if not file or not file.filename:
                continue
            filename = secure_filename(file.filename)
            path = os.path.join(kb_folder, filename)
            file.save(path)
            digest = _sha256(path)
            object_key = f"{kb_id}/{filename}"
            storage.put_file(object_key, path)
            existed = (
                session.query(Document)
                .filter(Document.kb_id == kb_id, Document.content_hash == digest, Document.run == RUN_DONE)
                .first()
            )
            if existed:
                saved.append(_doc_dict(existed) | {"dedup": True, "task_id": None})
                continue
            doc = Document(
                id=new_id(),
                kb_id=kb_id,
                name=filename,
                type=os.path.splitext(filename)[1].lstrip(".").lower(),
                location=object_key,
                size=os.path.getsize(path),
                content_hash=digest,
                index_modes="",
            )
            session.add(doc)
            session.flush()
            saved.append(_doc_dict(doc) | {"dedup": False})
        kb.doc_num = session.query(Document).filter(Document.kb_id == kb_id, Document.status == "1").count()

    for item in saved:
        if item.get("dedup"):
            continue
        item["task_id"] = enqueue_index(item["id"], index_root, upload_root, indexer_model)
    return saved


def list_documents(kb_id: str) -> list[dict]:
    with session_scope() as session:
        rows = (
            session.query(Document)
            .filter(Document.kb_id == kb_id, Document.status == "1")
            .order_by(Document.create_date.desc())
            .all()
        )
        return [_doc_dict(row) for row in rows]


def get_document(doc_id: str) -> dict | None:
    with session_scope() as session:
        row = session.get(Document, doc_id)
        return _doc_dict(row) if row else None


def delete_document(doc_id: str, index_root: str, static_root: str | None = None) -> None:
    from __000__common.__003__orm.models import Chunk, Task
    from __004__store.search import es_store
    from __004__store.vectorstore.numpy_store import vector_store

    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            return
        kb_id = doc.kb_id
        location = doc.location
        session.query(Chunk).filter(Chunk.doc_id == doc_id).delete()
        session.query(Task).filter(Task.doc_id == doc_id).delete()
        session.delete(doc)
        kb = session.get(Knowledgebase, kb_id)
        if kb is not None:
            kb.doc_num = session.query(Document).filter(Document.kb_id == kb_id, Document.status == "1").count()
            kb.chunk_num = session.query(Chunk).filter(Chunk.kb_id == kb_id, Chunk.available == 1).count()
    vector_store.delete_doc(kb_id, doc_id)
    es_store.delete_doc(kb_id, doc_id)
    if location:
        if os.path.isabs(location):
            if os.path.isfile(location):
                os.remove(location)
        else:
            storage.delete(location)
    rebuild_vision_index(kb_id, index_root)


def cancel_index(doc_id: str) -> dict:
    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            raise ValueError("文档不存在")
        if doc.run != RUN_RUNNING:
            raise ValueError("当前没有进行中的建索")
        doc.run = RUN_CANCEL
        doc.progress_msg = "已请求取消（当前步骤结束后生效，ColPali 无法中途打断）"
        return _doc_dict(doc)


def retry_index(doc_id: str, index_root: str, upload_root: str, indexer_model: str | None = None) -> dict:
    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            raise ValueError("文档不存在")
        if doc.run == RUN_RUNNING:
            raise ValueError("文档正在建索，请稍后再试")
        doc.page_num = 0
        doc.index_modes = ""
        payload = _doc_dict(doc)
    payload["task_id"] = enqueue_index(doc_id, index_root, upload_root, indexer_model)
    return payload


def source_path(doc: Document) -> str | None:
    if doc.location and os.path.isabs(doc.location) and os.path.isfile(doc.location):
        return doc.location
    path = storage.full_path(doc.location or "")
    return path if os.path.isfile(path) else None


def rebuild_vision_index(kb_id: str, index_root: str, indexer_model: str | None = None) -> int:
    paths: list[str] = []
    with session_scope() as session:
        kb = session.get(Knowledgebase, kb_id)
        if kb is None:
            drop_vision_index(kb_id, index_root)
            return 0
        docs = session.query(Document).filter(Document.kb_id == kb_id, Document.status == "1").all()
        for doc in docs:
            if RAG_VISION not in resolve_modes(kb, doc):
                doc.page_num = 0
                continue
            path = source_path(doc)
            if path:
                paths.append(path)
        if not paths:
            drop_vision_index(kb_id, index_root)
            kb.page_num = 0
            return 0
    added = rebuild_from_files(kb_id, paths, index_root, indexer_model)
    with session_scope() as session:
        kb = session.get(Knowledgebase, kb_id)
        if kb is not None:
            kb.page_num = added
    return added


def reindex_kb(
    kb_id: str,
    index_root: str,
    upload_root: str,
    indexer_model: str | None = None,
    old_mode: str | None = None,
    new_mode: str | None = None,
) -> int:
    from __000__common.__003__orm.models import Chunk, RUN_IDLE
    from __004__store.search import es_store
    from __004__store.vectorstore.numpy_store import vector_store

    need_text = (new_mode or "") in {RAG_TEXT, RAG_HYBRID}
    need_vision = (new_mode or "") in {RAG_VISION, RAG_HYBRID}
    if not need_vision:
        drop_vision_index(kb_id, index_root)
    if not need_text:
        with session_scope() as session:
            session.query(Chunk).filter(Chunk.kb_id == kb_id).delete()
            for doc in session.query(Document).filter(Document.kb_id == kb_id).all():
                doc.chunk_num = 0
        vector_store.drop_kb(kb_id)
        es_store.drop_kb(kb_id)

    ids: list[str] = []
    with session_scope() as session:
        docs = session.query(Document).filter(Document.kb_id == kb_id, Document.status == "1").all()
        for doc in docs:
            doc.index_modes = ""
            doc.page_num = 0 if need_vision else 0
            doc.run = RUN_IDLE
            doc.progress = 0.0
            doc.progress_msg = f"模式已改为 {new_mode or ''}，等待重建索引"
            ids.append(doc.id)
    for doc_id in ids:
        enqueue_index(doc_id, index_root, upload_root, indexer_model)
    return len(ids)


def indexed_names(kb_id: str) -> list[str]:
    return [row["name"] for row in list_documents(kb_id) if row.get("run") == RUN_DONE]


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def _doc_dict(row: Document) -> dict:
    return {
        "id": row.id,
        "kb_id": row.kb_id,
        "name": row.name,
        "type": row.type,
        "run": row.run,
        "progress": row.progress,
        "progress_msg": row.progress_msg,
        "chunk_num": row.chunk_num,
        "page_num": row.page_num,
        "size": row.size,
        "index_modes": row.index_modes,
        "create_date": row.create_date.isoformat(sep=" ", timespec="seconds") if row.create_date else "",
    }
