"""OCRFlux 解析服务门面。"""

from __future__ import annotations

# 3. 本地应用
from __001__rag.parse.base import ParsedDocument, ParserContext
from __001__rag.parse.ocrflux import OCRFluxParser


class OCRFluxService:
    """对业务层暴露 OCRFlux 文档解析入口。"""

    def __init__(self, parser: OCRFluxParser | None = None) -> None:
        self.parser = parser or OCRFluxParser()

    def parse(self, file_bytes: bytes, context: ParserContext) -> ParsedDocument:
        """解析文档为 Markdown。"""
        return self.parser.parse(file_bytes=file_bytes, context=context)

    def parse_to_markdown(self, file_bytes: bytes, context: ParserContext) -> str:
        """解析文档并直接返回 Markdown 内容。"""
        document = self.parse(file_bytes=file_bytes, context=context)
        return "\n\n".join(element.content for element in document.elements if element.content)


ocrflux_service = OCRFluxService()
