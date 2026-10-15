"""单切片处理任务：提取关键词 / 问题 / 向量 → 写入 ES。"""

from __future__ import annotations

# 1. Python 标准库
from datetime import datetime
from typing import Any

# 2. 第三方库
from celery import shared_task
from django.conf import settings
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone
from loguru import logger

# 3. 本地应用
from __001__rag.assistant import AssistantConfigError
from __001__rag.chunk.utils.documents import build_chunk_embedding
from __001__rag.keyword_extraction import create_keyword_extractor
from __001__rag.llm.exceptions import LLMAuthError, LLMConfigError
from __001__rag.models import DocImagesCache, Document, Task
from __001__rag.nlp.utils.indexing_tokenizer import build_token_metadata, token_string
from __001__rag.parse.utils.markdown import (
    build_document_image_url,
    extract_markdown_image_names,
    replace_markdown_image_paths,
)
from __001__rag.question_generate import create_question_generator
from __001__rag.search import es_service
from __001__rag.task import dict_to_chunk
from __001__rag.utils.db import append_progress_msg_expr


@shared_task(bind=True, max_retries=2, default_retry_delay=5, queue="default")
def process_chunk_and_index(
    self,
    chunk_dict: dict[str, Any],
    *,
    auto_keywords: int = 0,
    auto_questions: int = 0,
    doc_id: str = "",
    kb_id: str = "",
    doc_name: str = "",
    task_id: str = "",
    total_chunks: int = 0,
    started_at: str = "",
) -> dict[str, Any]:
    """处理单个切片：关键词提取、问题生成、向量生成，然后写入 ES。

    写入成功后同步更新 Task.progress_msg、Document.progress 和 process_duration。

    Returns:
        {"chunk_id": str, "chunk_idx": int, "token_num": int}
    """
    chunk_id = chunk_dict.get("chunk_id") or ""
    chunk_idx = chunk_dict.get("chunk_idx", -1)
    title = chunk_dict.get("title") or ""
    content = chunk_dict.get("content", "")
    metadata = chunk_dict.get("metadata")
    if not isinstance(metadata, dict):
        metadata = {}
        chunk_dict["metadata"] = metadata
    content = _replace_chunk_image_paths(content, metadata)
    chunk_dict["content"] = content
    metadata.update(build_token_metadata(content, title))

    # 1. 关键词提取
    if auto_keywords > 0:
        try:
            keywords = create_keyword_extractor().extract(content, topn=auto_keywords)
        except AssistantConfigError:
            logger.exception("关键词提取失败：助理配置不可用 chunk_id={}", chunk_id)
            raise self.retry(exc=AssistantConfigError("助理配置不可用: keyword_extraction"))
        except (LLMConfigError, LLMAuthError):
            logger.exception("关键词提取失败（配置/认证错误，不重试） chunk_id={}", chunk_id)
            raise  # 不 retry — 配置问题不会自行恢复
        except Exception:
            logger.exception("关键词提取失败 chunk_id={}", chunk_id)
            raise self.retry()
    else:
        keywords = []

    # 2. 问题生成
    if auto_questions > 0:
        try:
            questions = create_question_generator().generate(content, max_questions=auto_questions)
        except AssistantConfigError:
            logger.exception("问题生成失败：助理配置不可用 chunk_id={}", chunk_id)
            raise self.retry(exc=AssistantConfigError("助理配置不可用: question_generate"))
        except (LLMConfigError, LLMAuthError):
            logger.exception("问题生成失败（配置/认证错误，不重试） chunk_id={}", chunk_id)
            raise  # 不 retry — 配置问题不会自行恢复
        except Exception:
            logger.exception("问题生成失败 chunk_id={}", chunk_id)
            raise self.retry()
    else:
        questions = []

    # 3. 向量生成
    try:
        vec = build_chunk_embedding(title, content, questions)
    except (LLMConfigError, LLMAuthError):
        logger.exception("向量生成失败（配置/认证错误，不重试） chunk_id={}", chunk_id)
        raise  # 不 retry — 配置问题不会自行恢复
    except Exception:
        logger.exception("向量生成失败 chunk_id={}", chunk_id)
        raise self.retry()

    # 4. 合并结果到 chunk metadata
    metadata["important_kwd"] = keywords
    metadata["question_kwd"] = questions
    if keywords:
        metadata["important_tks"] = token_string(" ".join(keywords))
    if questions:
        metadata["question_tks"] = token_string("\n".join(questions))
    if vec:
        metadata[f"q_{len(vec)}_vec"] = vec

    # 5. 写入 ES（与检索同一套索引命名，尊重 CHUNK_LEGACY_COMPAT）
    index_name = es_service.chunk_index_name(kb_id)
    row = _chunk_dict_to_index_row(chunk_dict, doc_id, doc_name, kb_id, datetime.now())
    errors = es_service.create_chunks_to_index(index_name, kb_id, [row])
    if errors:
        logger.info("切片写入 ES 存在错误 chunk_id={} errors={}", chunk_id, errors)
        raise self.retry()

    # 6. 同步进度消息
    if task_id:
        _append_progress_msg(task_id, doc_id, chunk_idx, total_chunks, started_at)

    token_num = chunk_dict.get("token_num", 0)
    return {"chunk_id": chunk_id, "chunk_idx": chunk_idx, "token_num": token_num}


def _chunk_dict_to_index_row(
    cd: dict[str, Any], doc_id: str, doc_name: str, kb_id: str, created_at: datetime,
) -> dict[str, Any]:
    """将 chunk dict 转为 ES 索引行。"""
    chunk = dict_to_chunk(cd)
    row = chunk.to_index_document()
    row.setdefault("id", chunk.chunk_id)
    row.setdefault("doc_id", doc_id)
    row.setdefault("docnm_kwd", doc_name or "")
    row.setdefault("kb_id", [kb_id])
    row.setdefault("available_int", 1)
    row.setdefault("create_time", created_at.strftime("%Y-%m-%d %H:%M:%S"))
    row.setdefault("create_timestamp_flt", created_at.timestamp())
    return row


def _replace_chunk_image_paths(content: str, metadata: dict[str, Any]) -> str:
    """将切片内容中残留的 `images/<key>` 替换为文档图片接口路径。"""
    image_keys = extract_markdown_image_names(content)
    if not image_keys:
        return content

    image_url_map = _get_metadata_image_url_map(metadata, image_keys)
    missing_keys = image_keys - set(image_url_map)
    if missing_keys:
        image_url_map.update(_load_cached_image_url_map(missing_keys))
    return replace_markdown_image_paths(content, image_url_map)


def _get_metadata_image_url_map(
    metadata: dict[str, Any],
    image_keys: set[str],
) -> dict[str, str]:
    """从切片 metadata 携带的解析图片映射中提取当前内容需要的 URL。"""
    raw_map = metadata.get("image_url_map")
    if not isinstance(raw_map, dict):
        return {}

    result: dict[str, str] = {}
    for key in image_keys:
        url = raw_map.get(key) or raw_map.get(f"images/{key}")
        if isinstance(url, str) and url:
            result[key] = url
    return result


def _load_cached_image_url_map(image_keys: set[str]) -> dict[str, str]:
    """按图片 key 从缓存表恢复文档图片接口路径。"""
    if not image_keys:
        return {}

    try:
        rows = (
            DocImagesCache.objects.filter(image_key__in=image_keys, status=1)
            .exclude(bucket__isnull=True)
            .exclude(bucket="")
            .only("image_key", "bucket")
            .order_by("-update_date")
        )
        image_url_map: dict[str, str] = {}
        for row in rows:
            if row.image_key not in image_url_map:
                image_url_map[row.image_key] = build_document_image_url(row.bucket, row.image_key)
        return image_url_map
    except Exception:
        logger.exception("文档图片缓存查询失败 image_keys={}", sorted(image_keys))
        return {}


def _append_progress_msg(
    task_id: str,
    doc_id: str,
    chunk_idx: int,
    total_chunks: int = 0,
    started_at: str = "",
) -> None:
    """向 Task / Document 的 progress_msg 追加完成消息，同时更新进度和时间。"""
    now = timezone.now()
    _ts = datetime.now().strftime("%H:%M:%S")
    msg = f"\n{_ts} 切片 [{chunk_idx}] 处理完成"
    msg_expr = append_progress_msg_expr(msg)

    Task.objects.filter(id=task_id).update(
        progress_msg=msg_expr,
        update_date=now,
    )

    if doc_id:
        doc_updates: dict[str, Any] = {
            "progress_msg": msg_expr,
            "update_date": now,
        }
        if total_chunks > 0:
            chunk_progress = 0.3 + 0.7 * (chunk_idx + 1) / total_chunks
            doc_updates["progress"] = Greatest(
                F("progress"), Value(round(chunk_progress, 6))
            )
        if started_at:
            try:
                duration = (now - datetime.fromisoformat(started_at)).total_seconds()
                doc_updates["process_duration"] = duration
            except (ValueError, TypeError):
                logger.info("[DEGRADE] started_at 时间戳解析失败 value={}", started_at)
        Document.objects.filter(id=doc_id).update(**doc_updates)
