"""向量检索器（纯向量检索，不使用关键词）。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from loguru import logger

# 3. 本地应用
from __001__rag.retrieval.base import BaseRetriever
from __001__rag.search import es_service
from __001__rag.search.base import MatchDenseExpr, MatchTextExpr, SearchResult
from __001__rag.search.constants import CHUNK_SELECT_FIELDS_WITH_KB


class VectorRetriever(BaseRetriever):
    """向量检索：仅通过向量相似度（MatchDenseExpr）检索，不使用关键词。"""

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
        if not kb_ids:
            return SearchResult(total=0, chunks=[], aggregations={})

        if not embedding:
            return SearchResult(total=0, chunks=[], aggregations={})

        filters: dict[str, Any] = {"available_int": 1}
        if doc_ids:
            filters["doc_id"] = doc_ids

        match_exprs: list[Any] = [
            MatchDenseExpr(
                vector_field=f"q_{len(embedding)}_vec",
                embedding=embedding,
                topn=top_k,
                extra_options={"similarity": similarity_threshold},
            )
        ]

        logger.info(
            "ES检索[vector] kb_ids={} question_len={} top_n={} top_k={} embedding_dim={} "
            "similarity_threshold={} vector_field={}",
            kb_ids, len(question), size, top_k,
            len(embedding) if embedding else 0, similarity_threshold,
            f"q_{len(embedding)}_vec" if embedding else "N/A",
        )

        fields = select_fields if select_fields is not None else CHUNK_SELECT_FIELDS_WITH_KB
        return es_service.search(
            kb_ids=kb_ids,
            match_exprs=match_exprs,
            select_fields=fields,
            filters=filters,
            offset=max(page - 1, 0) * size,
            limit=size,
            agg_fields=["docnm_kwd"],
        )