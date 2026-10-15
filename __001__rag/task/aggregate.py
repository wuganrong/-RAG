"""Chord 回调：汇总切片处理结果，更新 DB 记录。"""

from __future__ import annotations

# 1. Python 标准库
import json
import time
from datetime import datetime
from typing import Any

# 2. 第三方库
from celery import shared_task
from django.db.models import F, Value
from django.db.models.functions import Coalesce, Concat, Greatest
from django.utils import timezone
from loguru import logger

# 3. 本地应用
from __001__rag.models import (
    RUN_CANCEL,
    RUN_DONE,
    STATUS_ENABLED,
    Document,
    Knowledgebase,
    Task,
)
from __001__rag.search import es_service


@shared_task(bind=True, max_retries=1, queue="default")
def finalize_document(
    self,
    results: list[dict[str, Any]],
    *,
    doc_id: str,
    task_id: str,
    kb_id: str,
    chunks_data: list[dict],
    parser_id: str,
    chunker_id: str,
    markdown_chars: int,
    element_count: int,
    old_chunk_num: int,
    auto_keywords: int,
    auto_questions: int,
    doc_name: str,
    started_at: str,
    start_wall: float,
) -> None:
    """Chord 回调：所有切片处理完成后，更新 Document / Knowledgebase / Task 记录。

    ES 写入已在每个切片的 process_chunk_and_index 中独立完成。
    """
    # 检查文档是否已被取消
    if Document.objects.filter(id=doc_id, run=RUN_CANCEL).exists():
        logger.info("文档已被取消，跳过汇总 doc_id={} task_id={}", doc_id, task_id)
        Task.objects.filter(id=task_id).update(
            progress=-1.0,
            progress_msg=Concat(
                Coalesce(F("progress_msg"), Value("")),
                Value("\n任务已取消"),
            ),
            update_date=timezone.now(),
        )
        Document.objects.filter(id=doc_id).update(
            progress_msg=Concat(
                Coalesce(F("progress_msg"), Value("")),
                Value("\n任务已取消"),
            ),
            update_date=timezone.now(),
        )
        return

    # ------------------------------------------------------------------
    # 1. 汇总切片结果
    # ------------------------------------------------------------------
    chunk_num = len(chunks_data)
    token_num = sum(r.get("token_num", 0) for r in results if isinstance(r, dict))
    if not token_num:
        token_num = max(markdown_chars // 4, 1)

    # ------------------------------------------------------------------
    # 2. 更新 Document / Knowledgebase / Task
    # ------------------------------------------------------------------
    duration = (timezone.now() - datetime.fromisoformat(started_at)).total_seconds()
    chunk_delta = chunk_num - old_chunk_num
    creation_enabled = auto_keywords > 0 or auto_questions > 0

    from_page = 0
    to_page = 100000000
    try:
        task_obj = Task.objects.only("from_page", "to_page").get(id=task_id)
        from_page = task_obj.from_page
        to_page = task_obj.to_page
    except Task.DoesNotExist:
        logger.info("[DEGRADE] 任务记录不存在 task_id={}，使用默认分页参数", task_id)

    page_label = _format_page_label(from_page, to_page)
    _now_str = datetime.now().strftime("%H:%M:%S")
    current = Document.objects.filter(id=doc_id).only("index_modes").first()
    modes = [part for part in ((current.index_modes if current else "") or "").split(",") if part]
    if chunk_num > 0 and "text" not in modes:
        modes.append("text")

    Document.objects.filter(id=doc_id).update(
        run=RUN_DONE,
        status=STATUS_ENABLED,
        progress=1.0,
        progress_msg=Concat(
            Coalesce(F("progress_msg"), Value("")),
            Value(f"\n{_now_str} {page_label}: 解析完成"),
        ),
        chunk_num=chunk_num,
        token_num=token_num,
        process_duration=duration,
        index_modes=",".join(modes),
        update_date=timezone.now(),
    )

    try:
        es_service.update_doc_available(kb_id, doc_id, 1)
    except Exception:
        logger.exception("解析完成后同步文档启用状态到 ES 失败 kb_id={} doc_id={}", kb_id, doc_id)

    if chunk_delta:
        Knowledgebase.objects.filter(id=kb_id).update(
            chunk_num=Greatest(F("chunk_num") + Value(chunk_delta), Value(0)),
            update_date=timezone.now(),
        )
        logger.info(
            "知识库切片数已同步 kb_id={} doc_id={} old_chunk_num={} new_chunk_num={} delta={}",
            kb_id, doc_id, old_chunk_num, chunk_num, chunk_delta,
        )

    chunk_ids = [cd.get("chunk_id", "") for cd in chunks_data if cd.get("chunk_id")]
    Task.objects.filter(id=task_id).update(
        progress=1.0,
        progress_msg=Concat(
            Coalesce(F("progress_msg"), Value("")),
            Value("\n完成"),
        ),
        process_duration=duration,
        update_date=timezone.now(),
        digest=json.dumps(
            {
                "parse_method": parser_id,
                "chunker_id": chunker_id,
                "element_count": element_count,
                "markdown_chars": markdown_chars,
                "chunk_count": chunk_num,
                "extraction_enabled": creation_enabled,
                "auto_keywords": auto_keywords,
                "auto_questions": auto_questions,
            },
            ensure_ascii=False,
        ),
        chunk_ids=json.dumps(chunk_ids, ensure_ascii=False),
    )

    logger.info(
        "文档解析汇总完成 doc_id={} task_id={} chunk_num={} token_num={} duration={:.3f}s total_wall={:.3f}s",
        doc_id, task_id, chunk_num, token_num, duration, time.time() - start_wall,
    )


def _format_page_label(from_page: int, to_page: int) -> str:
    display_from = from_page + 1
    display_to = to_page + 1 if to_page >= 100000000 else to_page
    return f"Page({display_from}~{display_to})"
