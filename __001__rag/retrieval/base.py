"""检索方法抽象基类。"""

from __future__ import annotations

# 1. Python 标准库
from abc import ABC, abstractmethod

# 3. 本地应用
from __001__rag.search.base import MatchTextExpr, SearchResult


class BaseRetriever(ABC):
    """检索方法基类，所有具体检索策略均需实现 retrieve 方法。"""

    @abstractmethod
    def retrieve(
        self,
        *,
        kb_ids: list[str],
        question: str,
        embedding: list[float] | None,
        page: int,
        size: int,
        top_k: int,
        similarity_threshold: float,
        vector_similarity_weight: float,
        doc_ids: list[str] | None = None,
        text_match_expr: MatchTextExpr | None = None,
        select_fields: list[str] | None = None,
    ) -> SearchResult:
        """执行检索并返回标准化结果。"""
        raise NotImplementedError
