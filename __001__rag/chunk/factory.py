"""文档切分器工厂。"""

from __future__ import annotations

# 2. 第三方库
from django.utils.module_loading import import_string

# 3. 本地应用
from __001__rag.chunk.base import BaseChunker, ChunkContext, ChunkItem
from __001__rag.models import ChunkMethod
from __001__rag.parse.base import ParsedDocument

_UNSUPPORTED_CHUNKER_IDS = {"presentation", "ppt", "pptx"}


class ChunkFactory:
    """按 chunker_id 构建切分器实例。"""

    @staticmethod
    def create(chunker_id: str | None) -> BaseChunker:
        normalized = (chunker_id or "naive").strip().lower()
        if normalized in _UNSUPPORTED_CHUNKER_IDS:
            raise ValueError(f"暂不支持的切分器: {chunker_id}")
        method_class = ChunkFactory._get_method_class_path(normalized)
        if not method_class:
            raise ValueError(f"不支持的切分器: {chunker_id or 'empty'}")
        chunker_cls = ChunkFactory._load_chunker_class(method_class)
        return chunker_cls()

    @staticmethod
    def supported_chunker_ids() -> set[str]:
        """返回已配置的切分器 ID。"""
        return set(ChunkMethod.objects.filter(method_type="chunker", status="1").values_list("method", flat=True))

    @staticmethod
    def _get_method_class_path(method: str) -> str | None:
        """返回切分方法对应的切分器类路径。"""
        try:
            chunk_method = ChunkMethod.objects.only("method_class").get(
                method_type="chunker",
                method=method,
                status="1",
            )
        except ChunkMethod.DoesNotExist:
            return None
        return chunk_method.method_class

    @staticmethod
    def _load_chunker_class(method_class: str) -> type[BaseChunker]:
        """加载并校验切分器类。"""
        try:
            chunker_cls = import_string(method_class)
        except ImportError as exc:
            raise ValueError(f"切分器类导入失败: {method_class}") from exc

        if not isinstance(chunker_cls, type) or not issubclass(chunker_cls, BaseChunker):
            raise ValueError(f"切分器类配置无效: {method_class}")
        return chunker_cls


def chunk_document(document: ParsedDocument, context: ChunkContext) -> list[ChunkItem]:
    """按上下文中的 chunker_id 切分解析后的文档。"""
    chunker = ChunkFactory.create(context.chunker_id)
    return chunker.chunk(document=document, context=context)
