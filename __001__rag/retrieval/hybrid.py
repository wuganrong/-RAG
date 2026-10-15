"""混合检索器（关键词 + 向量融合检索）。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.conf import settings

# 3. 本地应用
from __001__rag.nlp.utils.indexing_tokenizer import token_string
from __001__rag.retrieval.base import BaseRetriever
from __001__rag.search import es_service
from __001__rag.search.base import FusionExpr, MatchDenseExpr, MatchTextExpr, SearchResult
from __001__rag.search.constants import CHUNK_SELECT_FIELDS_WITH_KB, TEXT_SEARCH_FIELDS


class HybridRetriever(BaseRetriever):
    """混合检索：融合关键词匹配（MatchTextExpr）与向量相似度（MatchDenseExpr），
    通过 weighted_sum 融合，weight 由 vector_similarity_weight 控制。
    """

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

        filters: dict[str, Any] = {"available_int": 1}
        if doc_ids:
            filters["doc_id"] = doc_ids

        if text_match_expr is not None:
            match_exprs: list[Any] = [text_match_expr]
        else:
            match_exprs = [
                MatchTextExpr(
                    fields=TEXT_SEARCH_FIELDS,
                    matching_text=token_string(question),
                    topn=top_k,
                    extra_options={"minimum_should_match": float(getattr(settings, "RETRIEVAL_MINIMUM_SHOULD_MATCH", 0.3))},
                )
            ]
        if embedding:
            match_exprs.append(
                MatchDenseExpr(
                    vector_field=f"q_{len(embedding)}_vec",
                    embedding=embedding,
                    topn=top_k,
                    extra_options={"similarity": similarity_threshold},
                )
            )
            match_exprs.append(
                FusionExpr(
                    method="weighted_sum",
                    topn=top_k,
                    params={"weights": [1.0 - vector_similarity_weight, vector_similarity_weight]},
                )
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