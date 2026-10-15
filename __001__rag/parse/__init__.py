"""__001__rag.parse - document parsing abstractions."""

from __future__ import annotations

# 3. 本地应用
from __001__rag.parse.base import (
    BaseParser,
    ParsedDocument,
    ParsedElement,
    ParserContext,
)
from __001__rag.parse.factory import ParserFactory, parse_document_to_markdown
from __001__rag.parse.mineru import MinerUParser
from __001__rag.parse.mineru_service import MinerUService, mineru_service
from __001__rag.parse.ocrflux import OCRFluxParser
from __001__rag.parse.ocrflux_service import OCRFluxService, ocrflux_service

__all__ = [
    "BaseParser",
    "ParsedDocument",
    "ParsedElement",
    "ParserContext",
    "ParserFactory",
    "parse_document_to_markdown",
    "MinerUParser",
    "MinerUService",
    "mineru_service",
    "OCRFluxParser",
    "OCRFluxService",
    "ocrflux_service",
]
