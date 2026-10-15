"""检索方法模块。

提供可插拔的检索策略：
- HybridRetriever：混合检索（关键词 + 向量融合）
- KeywordRetriever：纯关键词检索
- VectorRetriever：纯向量检索
"""

from __future__ import annotations

from __001__rag.retrieval.base import BaseRetriever
from __001__rag.retrieval.hybrid import HybridRetriever
from __001__rag.retrieval.keyword import KeywordRetriever
from __001__rag.retrieval.vector import VectorRetriever

__all__ = [
    "BaseRetriever",
    "HybridRetriever",
    "KeywordRetriever",
    "VectorRetriever",
]
