from __future__ import annotations

import os

from celery import shared_task
from django.utils import timezone
from loguru import logger

from __001__rag.models import RUN_DONE, RUN_ERROR, RUN_RUNNING, Document, Knowledgebase
from __010__colpali.index.converters import convert_file_to_pdf, count_pages
from __010__colpali.index.vision_index import add_vision_document, rebuild_from_files
from __010__colpali.local_paths import get_default_indexer_model
from __010__colpali.paths import BYALDI_DIR, UPLOAD_DIR


@shared_task(bind=True, max_retries=0, queue="vision")
def index_vision_document(self, doc_id: str, file_path: str | None = None) -> None:
    """ColPali / Byaldi 页图建索。必须用 --pool=solo 的 vision 队列。"""
    try:
        doc = Document.objects.get(id=doc_id)
    except Document.DoesNotExist:
        logger.warning("视觉建索终止：文档不存在 doc_id={}", doc_id)
        return

    kb = Knowledgebase.objects.filter(id=doc.kb_id).first()
    mode = (getattr(kb, "rag_mode", None) or "text") if kb else "text"
    if mode not in {"vision", "hybrid"}:
        return

    path = file_path or _local_doc_path(doc)
    if not path or not os.path.isfile(path):
        _fail(doc, "找不到源文件，无法视觉建索")
        return

    ext = os.path.splitext(path)[1].lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}:
        logger.info("混合模式下跳过非页图文件的视觉建索 doc_id={} ext={}", doc_id, ext)
        return

    try:
        index_path = convert_file_to_pdf(path)
        page_count = count_pages(index_path) or 1
        add_vision_document(doc.kb_id, index_path, BYALDI_DIR, get_default_indexer_model())
        modes = [part for part in (doc.index_modes or "").split(",") if part]
        if "vision" not in modes:
            modes.append("vision")
        extra: dict = {}
        if mode == "vision" or ext in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}:
            extra = {"run": RUN_DONE, "progress": 1.0}
        else:
            current_run = str(
                Document.objects.filter(id=doc_id).values_list("run", flat=True).first() or ""
            )
            if current_run != RUN_RUNNING:
                extra = {"run": RUN_DONE, "progress": 1.0}
        Document.objects.filter(id=doc_id).update(
            page_num=page_count,
            index_modes=",".join(modes),
            progress_msg=(doc.progress_msg or "") + "\n视觉索引写入完成",
            update_date=timezone.now(),
            **extra,
        )
        if kb is not None:
            Knowledgebase.objects.filter(id=kb.id).update(
                page_num=_sum_kb_pages(kb.id),
            )
        logger.info("视觉建索完成 doc_id={} kb_id={}", doc_id, doc.kb_id)
    except Exception as exc:
        logger.exception("视觉建索失败 doc_id={}", doc_id)
        _fail(doc, str(exc))


def rebuild_kb_vision_index(kb_id: str) -> int:
    kb = Knowledgebase.objects.filter(id=kb_id).first()
    if kb is None or (kb.rag_mode or "text") not in {"vision", "hybrid"}:
        from __010__colpali.index.vision_index import drop_vision_index

        drop_vision_index(kb_id, BYALDI_DIR)
        return 0
    paths = []
    page_total = 0
    for doc in Document.objects.filter(kb_id=kb_id, status="1"):
        path = _local_doc_path(doc)
        if path:
            index_path = convert_file_to_pdf(path)
            paths.append(index_path)
            page_count = count_pages(index_path) or 1
            page_total += page_count
            Document.objects.filter(id=doc.id).update(page_num=page_count)
    added = rebuild_from_files(kb_id, paths, BYALDI_DIR, get_default_indexer_model())
    Knowledgebase.objects.filter(id=kb_id).update(page_num=page_total or added)
    return page_total or added


def _local_doc_path(doc: Document) -> str | None:
    if doc.location and os.path.isabs(doc.location) and os.path.isfile(doc.location):
        return doc.location
    candidate = os.path.join(UPLOAD_DIR, doc.kb_id, doc.name or "")
    if doc.name and os.path.isfile(candidate):
        return candidate
    return None


def _sum_kb_pages(kb_id: str) -> int:
    return sum(
        int(value or 0)
        for value in Document.objects.filter(kb_id=kb_id).values_list("page_num", flat=True)
    )


def _fail(doc: Document, msg: str) -> None:
    Document.objects.filter(id=doc.id).update(
        run=RUN_ERROR,
        progress_msg=f"视觉建索失败: {msg}",
        update_date=timezone.now(),
    )
