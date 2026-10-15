"""Celery 异步任务定义。

文档解析任务流程：
  1. 更新 Document.run = '2'（运行中），progress = 0
  2. 创建 Task 记录
  3. 从 MinIO 拉取文件
  4. 调用解析器解析 → 切分
  5. 按切片分发 process_chunk_and_index 任务（每个切片独立完成 关键词/问题/Embedding 并写入 ES）
  6. Chord 回调 finalize_document 更新 DB 记录
  7. 失败时更新 Document.run = '-1'（报错），记录 progress_msg，不再自动重试
"""

from __future__ import annotations

# 1. Python 标准库
import json
import os
import time
from datetime import datetime
from typing import Any

# 2. 第三方库
from celery import chord, shared_task
from django.db.models import F, Value
from django.db.models.functions import Coalesce, Concat
from django.utils import timezone
from loguru import logger

# 3. 本地应用
from __001__rag.chunk import ChunkContext, chunk_document
from __001__rag.models import (
    RUN_CANCEL,
    RUN_ERROR,
    RUN_IDLE,
    RUN_RUNNING,
    Document,
    Knowledgebase,
    Task,
)
from __001__rag.parse import ParserContext, parse_document_to_markdown
from __001__rag.storage import minio_service
from __001__rag.task import chunk_to_dict
from __001__rag.task.aggregate import finalize_document
from __001__rag.task.process_chunk import process_chunk_and_index
from __001__rag.utils import get_uuid
from __001__rag.utils.db import append_progress_msg_expr


@shared_task(bind=True, max_retries=0)
def parse_document(self, doc_id: str) -> None:
    """文档解析 Celery 任务。

    负责：拉取文件 → 解析切分 → 分发切片处理任务。
    ES 写入由各切片独立完成，DB 汇总由 Chord 回调 finalize_document 完成。

    Args:
        doc_id: 要解析的文档 ID。
    """
    logger.info("文档解析任务开始 doc_id={} celery_task_id={}", doc_id, self.request.id)

    try:
        doc = Document.objects.get(id=doc_id)
    except Document.DoesNotExist:
        logger.info("文档解析任务终止：文档不存在 doc_id={}", doc_id)
        return

    if doc.run == RUN_CANCEL:
        logger.info("文档已被取消，跳过解析 doc_id={}", doc_id)
        return

    if doc.run == RUN_ERROR:
        logger.info("文档已处于失败状态，跳过解析 doc_id={}", doc_id)
        return

    task_id = get_uuid()
    celery_task_id: str = self.request.id or ""
    now = datetime.now()

    # --- 创建 Task 记录（digest 暂存 celery_task_id，分发 Chord 后追加 sub_task_ids） ---
    Task.objects.create(
        id=task_id,
        doc_id=doc_id,
        from_page=0,
        to_page=100000000,
        begin_at=now,
        progress=0.0,
        progress_msg="任务已入队，等待处理…",
        retry_count=self.request.retries,
        digest=json.dumps({"celery_task_id": celery_task_id}, ensure_ascii=False),
    )
    logger.info(
        "已创建文档解析任务记录 doc_id={} task_id={} retry_count={} parser_id={}",
        doc_id, task_id, self.request.retries, doc.parser_id,
    )

    # --- 更新文档状态为运行中 ---
    Document.objects.filter(id=doc_id).update(
        run=RUN_RUNNING,
        progress=0.0,
        progress_msg="开始解析…",
        process_begin_at=now,
        update_date=timezone.now(),
    )
    logger.info("文档状态已更新为解析中 doc_id={} task_id={}", doc_id, task_id)

    try:
        _run_parse_and_dispatch(doc, task_id, celery_task_id)
    except Exception as exc:
        logger.exception("文档解析任务失败 doc_id={} task_id={}", doc_id, task_id)
        _mark_doc_error(doc_id, task_id, str(exc))


# ---------------------------------------------------------------------------
# 内部辅助函数
# ---------------------------------------------------------------------------


def _run_parse_and_dispatch(doc: Any, task_id: str, celery_task_id: str) -> None:
    """拉取文件、解析切分并分发 Chord 子任务。"""
    doc_id: str = doc.id
    old_chunk_num = max(int(getattr(doc, "chunk_num", 0) or 0), 0)
    started_at = timezone.now()
    start_wall = time.time()

    task_obj = Task.objects.only("from_page", "to_page").get(id=task_id)
    display_from = task_obj.from_page + 1
    display_to = task_obj.to_page + 1 if task_obj.to_page >= 100000000 else task_obj.to_page
    page_label = f"Page({display_from}~{display_to})"

    # 1. 从 MinIO 拉取文件
    _ts = datetime.now().strftime("%H:%M:%S")
    _update_task_progress(task_id, 0.05, f"{_ts} {page_label}: 从存储拉取文件…", doc_id=doc_id, started_at=started_at)
    try:
        bucket, name = minio_service.get_storage_address(doc_id)
        file_bytes = minio_service.get(bucket, name)
    except Exception as exc:
        raise RuntimeError(f"MinIO 拉取失败: {exc}") from exc

    # 检查是否已被取消
    if _is_doc_cancelled(doc_id):
        logger.info("文档解析任务已被取消，中止执行 doc_id={} task_id={}", doc_id, task_id)
        _mark_doc_cancelled(doc_id, task_id)
        return

    kb = Knowledgebase.objects.filter(id=doc.kb_id).first()
    rag_mode = (getattr(kb, "rag_mode", None) or "text") if kb else "text"
    local_path = _materialize_upload(doc, file_bytes)
    if rag_mode in {"vision", "hybrid"}:
        from __010__colpali.tasks import index_vision_document

        index_vision_document.apply_async(args=[doc_id, local_path], queue="vision")
        logger.info("已投递视觉建索 doc_id={} mode={}", doc_id, rag_mode)
    if rag_mode == "vision":
        _update_task_progress(task_id, 0.4, "仅视觉模式：已交给 ColPali 队列", doc_id=doc_id, started_at=started_at)
        return

    image_exts = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}
    filename = (doc.name or local_path or "").lower()
    if rag_mode == "hybrid" and any(filename.endswith(ext) for ext in image_exts):
        _update_task_progress(
            task_id, 0.4, "混合模式图片：跳过文本解析，等待视觉建索",
            doc_id=doc_id, started_at=started_at,
        )
        return

    # 2. 调用解析器 → 切分
    _ts = datetime.now().strftime("%H:%M:%S")
    _update_task_progress(task_id, 0.1, f"{_ts} {page_label}: 文件加载成功，开始解析…", doc_id=doc_id, started_at=started_at)
    parser_id: str = doc.parser_id or "mineru"
    chunker_id: str = getattr(doc, "chunker_id", None) or "pdf_llm"
    chunker_config: dict[str, Any] = getattr(doc, "chunker_config", None) or {}

    def progress_callback(progress: float, message: str) -> None:
        mapped_progress = 0.1 + max(min(progress, 1.0), 0.0) * 0.2
        _update_task_progress(task_id, mapped_progress, message, doc_id=doc_id, started_at=started_at)

    _update_task_progress(task_id, 0.15, f"使用解析器 [{parser_id}] 处理中…", doc_id=doc_id, started_at=started_at)
    parsed_document = parse_document_to_markdown(
        file_bytes=file_bytes,
        context=ParserContext(
            doc_id=doc.id,
            kb_id=doc.kb_id,
            filename=doc.name or doc.location or doc.id,
            parser_id=parser_id,
            config={"callback": progress_callback},
        ),
    )
    markdown_content = "\n\n".join(
        element.content for element in parsed_document.elements if element.content
    )
    _update_task_progress(task_id, 0.30, "文档已解析为 Markdown，开始切分…", doc_id=doc_id, started_at=started_at)
    chunks = chunk_document(
        document=parsed_document,
        context=ChunkContext(
            doc_id=doc.id,
            kb_id=doc.kb_id,
            parser_id=parser_id,
            chunker_id=chunker_id,
            config={**chunker_config, "callback": progress_callback},
        ),
    )
    _update_task_progress(task_id, 0.30, "文档切分完成，分发子任务…", doc_id=doc_id, started_at=started_at)

    # 3. 构建 Chord 子任务列表
    auto_keywords = int(chunker_config.get("auto_keywords", 20))
    auto_questions = int(chunker_config.get("auto_questions", 5))

    chunks_data = [chunk_to_dict(c, idx=i) for i, c in enumerate(chunks)]
    doc_name = doc.name or doc.location or doc.id
    total_chunks = len(chunks_data)

    chunk_sigs = []
    sub_task_ids: list[str] = []
    for i, cd in enumerate(chunks_data):
        chunk_task_id = f"chunk_{task_id}_{i}"
        chunk_sigs.append(
            process_chunk_and_index.s(
                cd,
                auto_keywords=auto_keywords,
                auto_questions=auto_questions,
                doc_id=doc_id,
                kb_id=doc.kb_id,
                doc_name=doc_name,
                task_id=task_id,
                total_chunks=total_chunks,
                started_at=started_at.isoformat(),
            ).set(task_id=chunk_task_id),
        )
        sub_task_ids.append(chunk_task_id)

    # 保存子任务 ID 列表到 Task.digest，供取消时批量 revoke
    Task.objects.filter(id=task_id).update(
        digest=json.dumps(
            {"celery_task_id": celery_task_id, "sub_task_ids": sub_task_ids},
            ensure_ascii=False,
        ),
    )

    _ts = datetime.now().strftime("%H:%M:%S")
    _update_task_progress(
        task_id, 0.3,
        f"{_ts} {page_label}: 分发 {len(chunks)} 个切片处理任务 "
        f"(关键词={auto_keywords > 0} 问题={auto_questions > 0} 向量={len(chunks)})",
        doc_id=doc_id,
        started_at=started_at,
    )

    finalize_kwargs = dict(
        doc_id=doc_id,
        task_id=task_id,
        kb_id=doc.kb_id,
        chunks_data=chunks_data,
        parser_id=parser_id,
        chunker_id=chunker_id,
        markdown_chars=len(markdown_content),
        element_count=len(parsed_document.elements),
        old_chunk_num=old_chunk_num,
        auto_keywords=auto_keywords,
        auto_questions=auto_questions,
        doc_name=doc_name,
        started_at=started_at.isoformat(),
        start_wall=start_wall,
    )

    # solo 单进程下 Redis chord 回调容易丢失；INLINE_CHUNK_TASKS=1 时本进程串行跑完切片。
    inline = os.environ.get("INLINE_CHUNK_TASKS", "").lower() in ("1", "true", "yes")
    if inline:
        results = []
        chunk_kwargs = {
            "auto_keywords": auto_keywords,
            "auto_questions": auto_questions,
            "doc_id": doc_id,
            "kb_id": doc.kb_id,
            "doc_name": doc_name,
            "task_id": task_id,
            "total_chunks": total_chunks,
            "started_at": started_at.isoformat(),
        }
        for cd in chunks_data:
            results.append(
                process_chunk_and_index.apply(
                    args=(cd,),
                    kwargs=chunk_kwargs,
                    throw=True,
                ).result
            )
        finalize_document.apply(args=(results,), kwargs=finalize_kwargs, throw=True)
        logger.info(
            "切片已本进程串行完成 doc_id={} task_id={} chunk_task_count={}",
            doc_id, task_id, len(chunks_data),
        )
        return

    # 4. 分发 Chord：每个切片独立处理，所有完成后汇总 DB
    chord(chunk_sigs, finalize_document.s(**finalize_kwargs)).delay()

    logger.info(
        "Chord 已分发 doc_id={} task_id={} chunk_task_count={}",
        doc_id, task_id, len(chunk_sigs),
    )


def _materialize_upload(doc: Any, file_bytes: bytes) -> str:
    """把 MinIO 字节落到本地工作副本，供 ColPali 读盘。"""
    from __010__colpali.paths import UPLOAD_DIR

    folder = os.path.join(UPLOAD_DIR, doc.kb_id)
    os.makedirs(folder, exist_ok=True)
    filename = doc.name or f"{doc.id}.bin"
    path = os.path.join(folder, filename)
    with open(path, "wb") as f:
        f.write(file_bytes)
    return path


def _update_task_progress(
    task_id: str, progress: float, msg: str, *, doc_id: str = "", started_at: datetime | None = None,
) -> None:
    """更新 Task 和 Document 的进度字段。"""
    now = timezone.now()
    common = {
        "progress_msg": append_progress_msg_expr("\n" + msg),
        "update_date": now,
    }
    Task.objects.filter(id=task_id).update(progress=progress, **common)
    if doc_id:
        doc_updates: dict[str, Any] = {"progress": progress, **common}
        if started_at is not None:
            doc_updates["process_duration"] = (now - started_at).total_seconds()
        Document.objects.filter(id=doc_id).update(**doc_updates)


def _mark_doc_error(doc_id: str, task_id: str, error_msg: str) -> None:
    """将文档和任务标记为错误状态。"""
    now = timezone.now()
    logger.exception("标记文档解析失败 doc_id={} task_id={}", doc_id, task_id)
    Document.objects.filter(id=doc_id).update(
        run=RUN_ERROR,
        progress_msg=f"解析失败: {error_msg}",
        update_date=now,
    )
    Task.objects.filter(id=task_id).update(
        progress=-1.0,
        progress_msg=f"失败: {error_msg}",
        update_date=now,
    )


def _is_doc_cancelled(doc_id: str) -> bool:
    """检查文档是否已被标记为取消。"""
    return Document.objects.filter(id=doc_id, run=RUN_CANCEL).exists()


def _mark_doc_cancelled(doc_id: str, task_id: str) -> None:
    """将文档和任务标记为已取消状态。"""
    now = timezone.now()
    logger.info("标记文档解析已取消 doc_id={} task_id={}", doc_id, task_id)
    Document.objects.filter(id=doc_id).update(
        run=RUN_CANCEL,
        progress_msg=Concat(
            Coalesce(F("progress_msg"), Value("")),
            Value("\n任务已取消"),
        ),
        update_date=now,
    )
    Task.objects.filter(id=task_id).update(
        progress=-1.0,
        progress_msg=Concat(
            Coalesce(F("progress_msg"), Value("")),
            Value("\n任务已取消"),
        ),
        update_date=now,
    )
