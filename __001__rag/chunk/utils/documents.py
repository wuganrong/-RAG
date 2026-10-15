"""Chunk 接口复用的轻量工具函数。"""

from __future__ import annotations

# 1. Python 标准库
import datetime
import re
from typing import Any

# 2. 第三方库
import xxhash
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.llm.service import LLMService
from __001__rag.nlp.utils.indexing_tokenizer import build_token_metadata, estimate_token_count, token_string

_INTERNAL_FIELD_RE = re.compile(r"(_vec$|_sm_|_tks|_ltks)")
_LABEL_FIELDS = ("subject_kwd", "std_kwd", "topic_kwd", "section_kwd")


def make_ragflow_chunk_id(doc_id: str, content: str) -> str:
    """按 ragflow 的手工创建规则生成稳定 chunk id。"""
    return xxhash.xxh64(f"{content}{doc_id}".encode("utf-8")).hexdigest()


def build_chunk_embedding(title: str, content: str, questions: list[str]) -> list[float] | None:
    """生成 chunk 向量，权重与 ragflow 手工创建/更新逻辑保持一致。"""
    try:
        texts = [title, content if not questions else "\n".join(questions)]
        embeddings = LLMService.embed(texts, model_name=getattr(settings, "EMBEDDING_MODEL_ID", None))
    except Exception as exc:
        logger.exception("[DEGRADE] 切片向量生成失败")
        return None

    if len(embeddings) >= 2:
        return [
            0.1 * title_value + 0.9 * body_value
            for title_value, body_value in zip(embeddings[0], embeddings[1], strict=False)
        ]
    return embeddings[0] if embeddings else None


def build_query_embedding(question: str, model_name: str | None = None) -> list[float] | None:
    """生成查询向量；失败时返回 None，保留关键词检索降级能力。

    Args:
        question: 查询文本。
        model_name: 指定 embedding 模型名；为 None 时回退到 settings.EMBEDDING_MODEL_ID。
    """
    try:
        resolved_model = model_name or getattr(settings, "EMBEDDING_MODEL_ID", None)
        embeddings = LLMService.embed([question], model_name=resolved_model)
    except Exception:
        logger.exception("[DEGRADE] 查询向量生成失败")
        return None
    return embeddings[0] if embeddings else None


def build_chunk_create_doc(
    *,
    doc_id: str,
    doc_name: str,
    kb_id: str,
    content: str,
    important_kwd: list[str],
    question_kwd: list[str],
    tag_kwd: list[str],
    available_int: int,
) -> tuple[dict[str, Any], int]:
    """构造写入 ES 的新 chunk 文档，并返回 token 估算数。"""
    chunk_id = make_ragflow_chunk_id(doc_id, content)
    now = datetime.datetime.now()
    es_doc: dict[str, Any] = {
        "id": chunk_id,
        "content_with_weight": content,
        "important_kwd": important_kwd,
        "important_tks": token_string(" ".join(important_kwd)),
        "question_kwd": question_kwd,
        "question_tks": token_string("\n".join(question_kwd)),
        "create_time": now.strftime("%Y-%m-%d %H:%M:%S"),
        "create_timestamp_flt": now.timestamp(),
        "kb_id": [kb_id],
        "doc_id": doc_id,
        "docnm_kwd": doc_name,
        "title_tks": token_string(doc_name),
        "available_int": available_int,
        **build_token_metadata(content, doc_name),
    }
    if tag_kwd:
        es_doc["tag_kwd"] = tag_kwd

    embedding = build_chunk_embedding(doc_name, content, question_kwd)
    if embedding:
        es_doc[f"q_{len(embedding)}_vec"] = embedding

    return es_doc, estimate_token_count(content)


def build_chunk_update_doc(
    *,
    doc_name: str,
    content: str,
    important_kwd: list[str] | None = None,
    question_kwd: list[str] | None = None,
    tag_kwd: list[str] | None = None,
    available_int: int | None = None,
) -> dict[str, Any]:
    """构造更新 ES chunk 的字段集合。"""
    es_doc: dict[str, Any] = {
        "content_with_weight": content,
        **build_token_metadata(content, doc_name),
    }
    questions = question_kwd or []
    if important_kwd is not None:
        es_doc["important_kwd"] = important_kwd
        es_doc["important_tks"] = token_string(" ".join(important_kwd))
    if question_kwd is not None:
        es_doc["question_kwd"] = question_kwd
        es_doc["question_tks"] = token_string("\n".join(question_kwd))
    if tag_kwd is not None:
        es_doc["tag_kwd"] = tag_kwd
    if available_int is not None:
        es_doc["available_int"] = available_int

    embedding = build_chunk_embedding(doc_name, content, questions)
    if embedding:
        es_doc[f"q_{len(embedding)}_vec"] = embedding
    return es_doc


def strip_chunk_internal_fields(chunk: dict[str, Any]) -> dict[str, Any]:
    """移除向量、分词等内部索引字段。"""
    return {key: value for key, value in chunk.items() if not _INTERNAL_FIELD_RE.search(key)}


def format_chunk_for_response(
    chunk: dict[str, Any],
    *,
    highlight: str | None = None,
    include_prefix: bool = False,
) -> dict[str, Any]:
    """转换 ES chunk 为前端兼容字段。"""
    content = highlight or chunk.get("content_with_weight", "")
    doc_name = chunk.get("docnm_kwd", "")
    if include_prefix and doc_name:
        content = f"《{doc_name}》\n{content}"

    score = float(chunk.get("similarity") or chunk.get("_score") or 0.0)
    data = {
        "chunk_id": chunk.get("id", ""),
        "content_with_weight": content,
        "doc_id": chunk.get("doc_id", ""),
        "docnm_kwd": doc_name,
        "chunk_title_kwd": chunk.get("chunk_title_kwd", ""),
        "important_kwd": chunk.get("important_kwd", []),
        "question_kwd": chunk.get("question_kwd", []),
        "image_id": chunk.get("img_id", ""),
        "available_int": int(chunk.get("available_int", 1)),
        "positions": chunk.get("position_int", []),
        "parent_group_id": chunk.get("parent_group_id", ""),
        "chunk_order": chunk.get("chunk_order", ""),
        "similarity": score,
        "vector_similarity": float(chunk.get("vector_similarity") or score),
        "term_similarity": float(chunk.get("term_similarity") or score),
    }
    labels = [chunk[field] for field in _LABEL_FIELDS if chunk.get(field)]
    if labels:
        data["chunk_labels"] = labels
    return data


def format_doc_aggs(aggregations: dict[str, Any]) -> list[dict[str, Any]]:
    """将 ES 聚合结果转成 doc_aggs 兼容结构。"""
    buckets = aggregations.get("docnm_kwd", [])
    return [{"doc_name": name, "count": count} for name, count in buckets]
