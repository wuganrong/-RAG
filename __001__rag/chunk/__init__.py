"""__001__rag.chunk - document chunking abstractions and factory."""

from __future__ import annotations

# 3. 本地应用
from __001__rag.chunk.base import BaseChunker, ChunkContext, ChunkItem
from __001__rag.chunk.factory import ChunkFactory, chunk_document

__all__ = [
    "BaseChunker",
    "ChunkContext",
    "ChunkItem",
    "ChunkFactory",
    "chunk_document",
]
