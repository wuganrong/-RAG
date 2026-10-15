"""文档切分基础抽象。"""

from __future__ import annotations

# 1. Python 标准库
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

# 3. 本地应用
from __001__rag.parse.base import ParsedDocument


@dataclass(slots=True)
class ChunkContext:
    """切分任务上下文。"""

    doc_id: str
    kb_id: str
    parser_id: str
    chunker_id: str
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChunkItem:
    """待写入检索索引的切片。"""

    content: str
    doc_id: str
    kb_id: str
    chunk_id: str | None = None
    title: str | None = None
    page: int | None = None
    token_num: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_index_document(self) -> dict[str, Any]:
        """转换为 ES 等检索后端可写入的基础字段。"""
        data: dict[str, Any] = {
            "content_with_weight": self.content,
            "doc_id": self.doc_id,
            "kb_id": self.kb_id,
            "chunk_title_kwd": self.title or "",
            "page": self.page,
            "token_num": self.token_num,
        }
        if self.chunk_id:
            data["id"] = self.chunk_id
        data.update(self.metadata)
        return data


class BaseChunker(ABC):
    """文档切分端口。"""

    chunker_id = "base"

    @abstractmethod
    def chunk(self, document: ParsedDocument, context: ChunkContext) -> list[ChunkItem]:
        """将解析后的文档切分为可索引的 chunk。"""
        raise NotImplementedError
