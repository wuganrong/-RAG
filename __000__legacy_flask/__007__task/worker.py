from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

from __000__common.__002__log import get_logger
from __000__common.__003__orm.db import session_scope
from __000__common.__003__orm.ids import new_id
from __000__common.__003__orm.models import (
    RAG_HYBRID,
    RAG_TEXT,
    RAG_VISION,
    RUN_CANCEL,
    RUN_DONE,
    RUN_ERROR,
    RUN_IDLE,
    RUN_RUNNING,
    Chunk,
    Document,
    Knowledgebase,
    Task,
)
from __001__parse.factory import parse_document
from __002__chunk.factory import chunk_document
from __003__colpali.index.vision_index import add_vision_document
from __004__store.search import es_store
from __004__store.storage.factory import storage
from __004__store.vectorstore.numpy_store import vector_store
from __006__llm.factory import embed_texts

logger = get_logger(__name__)

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="rag-index")


class IndexCancelled(Exception):
    pass


def start_worker() -> None:
    from __000__common.__001__path import BYALDI_DIR, UPLOAD_DIR
    from __003__colpali.local_paths import get_default_indexer_model

    stuck: list[str] = []
    with session_scope() as session:
        rows = (
            session.query(Document)
            .filter(Document.status == "1", Document.run.in_([RUN_RUNNING, RUN_IDLE]))
            .all()
        )
        for row in rows:
            row.run = RUN_IDLE
            row.progress_msg = "进程重启，任务将重新入队"
            stuck.append(row.id)
    model = get_default_indexer_model()
    for doc_id in stuck:
        try:
            enqueue_index(doc_id, BYALDI_DIR, UPLOAD_DIR, model)
            logger.info("Re-queued interrupted index doc=%s", doc_id)
        except Exception as exc:
            logger.warning("Re-queue failed doc=%s: %s", doc_id, exc)


def _is_cancelled(doc_id: str) -> bool:
    from __000__common.__003__orm.db import SessionLocal

    db = SessionLocal()
    try:
        row = db.get(Document, doc_id)
        return row is not None and row.run == RUN_CANCEL
    finally:
        db.close()


def _guard(session, doc: Document, task: Task | None) -> None:
    session.commit()
    if _is_cancelled(doc.id):
        raise IndexCancelled(doc.id)


def resolve_modes(kb: Knowledgebase, doc: Document) -> list[str]:
    raw = (doc.index_modes or "").strip()
    if raw:
        return [part for part in raw.split(",") if part]
    mode = kb.rag_mode or RAG_VISION
    if mode == RAG_HYBRID:
        return [RAG_TEXT, RAG_VISION]
    return [mode]


def _advance(session, doc: Document, task: Task | None, progress: float, msg: str) -> None:
    progress = max(float(doc.progress or 0), progress)
    doc.progress = progress
    doc.progress_msg = msg
    if task is not None:
        task.progress = max(float(task.progress or 0), progress)
        task.progress_msg = msg
    session.flush()
    session.commit()


def enqueue_index(doc_id: str, index_root: str, upload_root: str, indexer_model: str | None = None) -> str:
    with session_scope() as session:
        doc = session.get(Document, doc_id)
        if doc is None:
            raise ValueError(f"文档不存在: {doc_id}")
        task = Task(id=new_id(), doc_id=doc_id, progress=0.0, progress_msg="任务已入队")
        doc.run = RUN_RUNNING
        doc.progress = 0.0
        doc.progress_msg = "任务已入队，等待处理…"
        session.add(task)
        task_id = task.id
    _executor.submit(_run_index, doc_id, task_id, index_root, upload_root, indexer_model)
    return task_id


def _run_index(
    doc_id: str,
    task_id: str,
    index_root: str,
    upload_root: str,
    indexer_model: str | None,
) -> None:
    if _is_cancelled(doc_id):
        with session_scope() as session:
            doc = session.get(Document, doc_id)
            if doc is not None:
                doc.run = RUN_CANCEL
                doc.progress_msg = "已取消"
        return
    try:
        with session_scope() as session:
            doc = session.get(Document, doc_id)
            task = session.get(Task, task_id)
            if doc is None:
                return
            kb = session.get(Knowledgebase, doc.kb_id)
            if kb is None:
                return
            if doc.run == RUN_CANCEL:
                return
            doc.run = RUN_RUNNING
            _advance(session, doc, task, 0.05, "开始处理文档")
            _guard(session, doc, task)
            modes = resolve_modes(kb, doc)
            doc.index_modes = ",".join(modes)
            if RAG_VISION not in modes:
                doc.page_num = 0
            if doc.location and os.path.isabs(doc.location):
                source_path = doc.location
            else:
                source_path = storage.full_path(doc.location or "")
            if not os.path.isfile(source_path):
                raise FileNotFoundError(f"找不到源文件，无法建索：{source_path}")

            if RAG_TEXT in modes:
                _advance(session, doc, task, 0.15, "解析文本")
                _guard(session, doc, task)
                text = parse_document(source_path, kb.parser_id or "naive")
                _guard(session, doc, task)
                pieces = chunk_document(text, kb.chunker_id or "naive")
                if not pieces and RAG_VISION not in modes:
                    raise ValueError("文本模式未能解析出正文。图片或扫描件请改用视觉 / 混合模式。")
                session.query(Chunk).filter(Chunk.doc_id == doc.id).delete()
                vectors = embed_texts(pieces, model=kb.embd_id) if pieces else []
                store_rows = []
                for idx, piece in enumerate(pieces):
                    chunk_id = new_id()
                    embedding = vectors[idx] if idx < len(vectors) else None
                    session.add(
                        Chunk(
                            id=chunk_id,
                            kb_id=kb.id,
                            doc_id=doc.id,
                            doc_name=doc.name or "",
                            position=idx,
                            content=piece,
                            embedding=json.dumps(embedding) if embedding else None,
                            available=1,
                        )
                    )
                    if embedding:
                        store_rows.append(
                            {
                                "id": chunk_id,
                                "doc_id": doc.id,
                                "doc_name": doc.name or "",
                                "content": piece,
                                "embedding": embedding,
                            }
                        )
                vector_store.replace_doc(kb.id, doc.id, store_rows)
                es_store.upsert_chunks(kb.id, store_rows)
                doc.chunk_num = len(pieces)
                _advance(session, doc, task, 0.55 if RAG_VISION in modes else 0.9, f"文本切块完成 {len(pieces)} 段")
                _guard(session, doc, task)

            if RAG_VISION in modes:
                _advance(session, doc, task, 0.6, "视觉增量建索（ColPali）")
                _guard(session, doc, task)
                vision_dir = os.path.join(index_root, kb.id)
                if int(doc.page_num or 0) > 0 and os.path.isdir(vision_dir):
                    _advance(session, doc, task, 0.9, "视觉索引已存在，跳过重复写入")
                else:
                    add_vision_document(kb.id, source_path, index_root, indexer_model)
                    _guard(session, doc, task)
                    doc.page_num = max(int(doc.page_num or 0), 1)
                    _advance(session, doc, task, 0.95, "视觉索引写入完成")
                _guard(session, doc, task)

            kb.chunk_num = session.query(Chunk).filter(Chunk.kb_id == kb.id, Chunk.available == 1).count()
            kb.doc_num = session.query(Document).filter(Document.kb_id == kb.id, Document.status == "1").count()
            kb.page_num = sum(
                int(row.page_num or 0)
                for row in session.query(Document).filter(Document.kb_id == kb.id, Document.status == "1").all()
            )
            session.refresh(doc)
            if doc.run == RUN_CANCEL:
                raise IndexCancelled(doc_id)
            doc.run = RUN_DONE
            _advance(session, doc, task, 1.0, "完成")
            logger.info("Index finished doc=%s modes=%s", doc_id, modes)
    except IndexCancelled:
        logger.info("Index cancelled doc=%s", doc_id)
        with session_scope() as session:
            doc = session.get(Document, doc_id)
            task = session.get(Task, task_id)
            if doc is not None:
                doc.run = RUN_CANCEL
                doc.progress_msg = "已取消"
            if task is not None:
                task.progress_msg = "已取消"
    except Exception as exc:
        logger.error("Index failed doc=%s: %s", doc_id, exc, exc_info=True)
        with session_scope() as session:
            doc = session.get(Document, doc_id)
            task = session.get(Task, task_id)
            if doc is not None:
                doc.run = RUN_ERROR
                doc.progress_msg = str(exc)
            if task is not None:
                task.progress_msg = str(exc)
