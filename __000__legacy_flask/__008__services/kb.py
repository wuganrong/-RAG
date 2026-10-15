from __future__ import annotations

import os
import shutil

from __000__common.__001__path import PAGE_IMAGE_DIR
from __000__common.__003__orm.db import session_scope
from __000__common.__003__orm.ids import new_id
from __000__common.__003__orm.models import RAG_VISION, Chunk, Conversation, Document, Knowledgebase, Task
from __003__colpali.index.vision_index import drop_vision_index
from __004__store.search import es_store
from __004__store.storage.factory import storage
from __004__store.vectorstore.numpy_store import vector_store


def list_kbs() -> list[dict]:
    with session_scope() as session:
        rows = session.query(Knowledgebase).filter(Knowledgebase.status == "1").order_by(Knowledgebase.create_date.desc()).all()
        return [_kb_dict(row) for row in rows]


def get_kb(kb_id: str) -> dict | None:
    with session_scope() as session:
        row = session.get(Knowledgebase, kb_id)
        return _kb_dict(row) if row else None


def create_kb(name: str, rag_mode: str = RAG_VISION, description: str = "") -> dict:
    with session_scope() as session:
        exists = session.query(Knowledgebase).filter(Knowledgebase.name == name).first()
        if exists:
            raise ValueError(f"知识库已存在: {name}")
        row = Knowledgebase(
            id=new_id(),
            name=name.strip() or f"kb-{new_id()[:8]}",
            description=description,
            rag_mode=rag_mode or RAG_VISION,
        )
        session.add(row)
        session.flush()
        return _kb_dict(row)


def update_kb(kb_id: str, **fields) -> dict:
    allowed = {
        "name",
        "description",
        "rag_mode",
        "top_n",
        "page_top_n",
        "similarity_threshold",
        "embd_id",
        "chat_id",
        "parser_id",
        "chunker_id",
        "vlm_id",
    }
    with session_scope() as session:
        row = session.get(Knowledgebase, kb_id)
        if row is None:
            raise ValueError("知识库不存在")
        for key, value in fields.items():
            if key not in allowed or value is None or value == "":
                continue
            if key in {"top_n", "page_top_n"}:
                value = int(value)
            if key == "similarity_threshold":
                value = float(value)
            if key in {"parser_id", "chunker_id"} and value not in {"naive"}:
                raise ValueError("当前只支持 naive 解析器和切块器")
            setattr(row, key, value)
        session.flush()
        return _kb_dict(row)


def update_kb_and_reindex(
    kb_id: str,
    index_root: str,
    upload_root: str,
    indexer_model: str | None = None,
    **fields,
) -> dict:
    from __008__services import document as doc_service

    previous = get_kb(kb_id)
    data = update_kb(kb_id, **fields)
    old_mode = (previous or {}).get("rag_mode")
    new_mode = data.get("rag_mode")
    if old_mode and new_mode and old_mode != new_mode:
        data["reindex_count"] = doc_service.reindex_kb(
            kb_id,
            index_root,
            upload_root,
            indexer_model,
            old_mode=old_mode,
            new_mode=new_mode,
        )
    else:
        data["reindex_count"] = 0
    return data


def ensure_default_kb() -> dict:
    items = list_kbs()
    if items:
        return items[0]
    return create_kb("默认知识库", rag_mode=RAG_VISION, description="自动创建")


def delete_kb(kb_id: str, index_root: str, static_root: str | None = None) -> None:
    with session_scope() as session:
        session.query(Chunk).filter(Chunk.kb_id == kb_id).delete()
        session.query(Conversation).filter(Conversation.kb_id == kb_id).delete()
        docs = session.query(Document).filter(Document.kb_id == kb_id).all()
        for doc in docs:
            session.query(Task).filter(Task.doc_id == doc.id).delete()
            session.delete(doc)
        row = session.get(Knowledgebase, kb_id)
        if row is not None:
            session.delete(row)
    storage.delete_prefix(kb_id)
    vector_store.drop_kb(kb_id)
    es_store.drop_kb(kb_id)
    drop_vision_index(kb_id, index_root)
    image_root = static_root or PAGE_IMAGE_DIR
    images = os.path.join(image_root, kb_id)
    if os.path.isdir(images):
        shutil.rmtree(images, ignore_errors=True)
    legacy = os.path.join(image_root, "images", kb_id)
    if os.path.isdir(legacy):
        shutil.rmtree(legacy, ignore_errors=True)


def _kb_dict(row: Knowledgebase) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description,
        "rag_mode": row.rag_mode,
        "embd_id": row.embd_id,
        "chat_id": row.chat_id,
        "vlm_id": row.vlm_id,
        "parser_id": row.parser_id,
        "chunker_id": row.chunker_id,
        "top_n": row.top_n,
        "page_top_n": row.page_top_n,
        "similarity_threshold": row.similarity_threshold,
        "doc_num": row.doc_num,
        "chunk_num": row.chunk_num,
        "page_num": row.page_num,
        "status": row.status,
    }
