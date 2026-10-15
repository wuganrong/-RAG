"""模型与检索结果的轻量序列化工具。"""

from __future__ import annotations

# 1. Python 标准库
from typing import TYPE_CHECKING, Any

# 2. 第三方库

# 3. 本地应用
from __001__rag.utils.time import format_datetime

if TYPE_CHECKING:
    from __001__rag.models import Document


def doc_to_dict(doc: "Document") -> dict[str, Any]:
    """将 Document 模型实例转换为与 ragflow 原接口兼容的响应字典。"""
    fields = [
        "chunk_num",
        "chunker_config",
        "chunker_id",
        "create_date",
        "created_by",
        "id",
        "kb_id",
        "tenant_id",
        "location",
        "meta_fields",
        "name",
        "parser_id",
        "process_begin_at",
        "process_duation",
        "progress",
        "progress_msg",
        "remote_id",
        "run",
        "size",
        "source_type",
        "status",
        "thumbnail",
        "token_num",
        "type",
        "update_date",
        "index_modes",
        "page_num",
    ]
    values = {
        "chunk_num": _getattr_if_exists(doc, "chunk_num"),
        "chunker_config": _getattr_if_exists(doc, "chunker_config"),
        "chunker_id": _getattr_if_exists(doc, "chunker_id"),
        "create_date": _format_dt(_getattr_if_exists(doc, "create_date")),
        "created_by": _getattr_if_exists(doc, "created_by"),
        "id": _getattr_if_exists(doc, "id"),
        "kb_id": _getattr_if_exists(doc, "kb_id"),
        "tenant_id": _getattr_if_exists(doc, "tenant_id"),
        "location": _getattr_if_exists(doc, "location"),
        "meta_fields": _getattr_if_exists(doc, "meta_fields"),
        "name": _getattr_if_exists(doc, "name"),
        "parser_id": _getattr_if_exists(doc, "parser_id"),
        "process_begin_at": _format_dt(_getattr_if_exists(doc, "process_begin_at")),
        "process_duation": _getattr_if_exists(doc, "process_duration"),
        "progress": _getattr_if_exists(doc, "progress"),
        "progress_msg": _getattr_if_exists(doc, "progress_msg"),
        "remote_id": _getattr_if_exists(doc, "remote_id"),
        "run": _getattr_if_exists(doc, "run"),
        "size": _getattr_if_exists(doc, "size"),
        "source_type": _getattr_if_exists(doc, "source_type"),
        "status": _getattr_if_exists(doc, "status"),
        "thumbnail": _getattr_if_exists(doc, "thumbnail"),
        "token_num": _getattr_if_exists(doc, "token_num"),
        "type": _getattr_if_exists(doc, "type"),
        "update_date": _format_dt(_getattr_if_exists(doc, "update_date")),
        "index_modes": _getattr_if_exists(doc, "index_modes"),
        "page_num": _getattr_if_exists(doc, "page_num"),
    }
    return {field: values[field] for field in fields if values[field] is not _MISSING}


_MISSING = object()


def _getattr_if_exists(obj: object, name: str) -> Any:
    return getattr(obj, name, _MISSING)


def _format_dt(value: Any) -> str | None | object:
    if value is _MISSING or value is None:
        return value
    return format_datetime(value)


def chunk_to_dict(chunk: dict[str, Any]) -> dict[str, Any]:
    """将 ES 返回的 chunk 转换为与原项目兼容的响应字典。"""
    return {
        "chunk_id": chunk.get("id", ""),
        "content_with_weight": chunk.get("content_with_weight", ""),
        "doc_id": chunk.get("doc_id", ""),
        "docnm_kwd": chunk.get("docnm_kwd", ""),
        "chunk_title_kwd": chunk.get("chunk_title_kwd", ""),
        "important_kwd": chunk.get("important_kwd", []),
        "question_kwd": chunk.get("question_kwd", []),
        "image_id": chunk.get("img_id", ""),
        "available_int": int(chunk.get("available_int", 1)),
        "create_user_name": chunk.get("create_user_name", ""),
        "create_time": chunk.get("create_time", ""),
    }
