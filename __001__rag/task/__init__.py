"""__001__rag.task — 后台异步任务定义与切片处理工具。

Celery 任务（由 CELERY_IMPORTS 注册）：
  - process_chunk.py: 单切片处理（关键词/问题/向量 → ES 写入）
  - aggregate.py    : Chord 回调，文档处理完成后更新 DB 记录

可复用工具：
  - chunk_to_dict   : ChunkItem → 可 JSON 序列化 dict
  - dict_to_chunk   : dict → ChunkItem
"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 3. 本地应用
from __001__rag.chunk.base import ChunkItem


def chunk_to_dict(chunk: ChunkItem, idx: int = 0) -> dict[str, Any]:
    """将 ChunkItem 转为可 JSON 序列化的字典。"""
    return {
        "chunk_id": chunk.chunk_id or "",
        "chunk_idx": idx,
        "title": chunk.title or "",
        "content": chunk.content,
        "page": chunk.page,
        "doc_id": chunk.doc_id,
        "kb_id": chunk.kb_id,
        "token_num": chunk.token_num,
        "metadata": chunk.metadata,
    }


def dict_to_chunk(data: dict[str, Any]) -> ChunkItem:
    """从字典还原 ChunkItem。"""
    return ChunkItem(
        chunk_id=data.get("chunk_id") or None,
        title=data.get("title") or None,
        content=data.get("content", ""),
        page=data.get("page"),
        doc_id=data.get("doc_id", ""),
        kb_id=data.get("kb_id", ""),
        token_num=int(data.get("token_num", 0)),
        metadata=data.get("metadata", {}),
    )


__all__ = [
    "chunk_to_dict",
    "dict_to_chunk",
]
