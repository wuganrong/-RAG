"""文档解析器工厂。"""

from __future__ import annotations

# 2. 第三方库
from django.utils.module_loading import import_string

# 3. 本地应用
from __001__rag.models import ChunkMethod
from __001__rag.parse.base import BaseParser, ParsedDocument, ParserContext


class ParserFactory:
    """按 parser_id 构建解析器实例。"""

    @staticmethod
    def create(parser_id: str | None) -> BaseParser:
        normalized = (parser_id or "").strip().lower()
        method_class = ParserFactory._get_method_class_path(normalized)
        if not method_class:
            raise ValueError(f"不支持的解析器: {parser_id or 'empty'}")
        parser_cls = ParserFactory._load_parser_class(method_class)
        return parser_cls()

    @staticmethod
    def supported_parser_ids() -> set[str]:
        """返回已配置的文档提取方法 ID。"""
        return set(ChunkMethod.objects.filter(method_type="parser", status="1").values_list("method", flat=True))

    @staticmethod
    def _get_method_class_path(method: str) -> str | None:
        """返回文档提取方法对应的解析器类路径。"""
        try:
            parser_method = ChunkMethod.objects.only("method_class").get(
                method_type="parser",
                method=method,
                status="1",
            )
        except ChunkMethod.DoesNotExist:
            return None
        return parser_method.method_class

    @staticmethod
    def _load_parser_class(method_class: str) -> type[BaseParser]:
        """加载并校验文档解析器类。"""
        try:
            parser_cls = import_string(method_class)
        except ImportError as exc:
            raise ValueError(f"解析器类导入失败: {method_class}") from exc

        if not isinstance(parser_cls, type) or not issubclass(parser_cls, BaseParser):
            raise ValueError(f"解析器类配置无效: {method_class}")
        return parser_cls


def parse_document_to_markdown(file_bytes: bytes, context: ParserContext) -> ParsedDocument:
    """根据上下文 parser_id 分发解析，并返回 ParsedDocument。"""
    parser = ParserFactory.create(context.parser_id)
    if not parser.supports(context.filename):
        raise ValueError(f"解析器 {parser.parser_id} 不支持文件: {context.filename}")
    return parser.parse(file_bytes=file_bytes, context=context)
