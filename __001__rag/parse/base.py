"""文档解析基础抽象。"""

from __future__ import annotations

# 1. Python 标准库
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

ParsedElementType = Literal["text", "table", "image", "title", "markdown"]


@dataclass(slots=True)
class ParserContext:
    """解析任务上下文。"""

    doc_id: str
    kb_id: str
    filename: str
    parser_id: str = "naive"
    config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedElement:
    """解析后的结构化元素。"""

    content: str
    element_type: ParsedElementType = "text"
    page: int | None = None
    title: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ParsedDocument:
    """解析后的文档内容。"""

    doc_id: str
    filename: str
    elements: list[ParsedElement]
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseParser(ABC):
    """文档解析器端口。"""

    parser_id = "base"

    @abstractmethod
    def supports(self, filename: str, content_type: str | None = None) -> bool:
        """判断当前解析器是否支持该文件。"""
        raise NotImplementedError

    @abstractmethod
    def parse(self, file_bytes: bytes, context: ParserContext) -> ParsedDocument:
        """将文件字节解析为结构化文档。"""
        raise NotImplementedError
