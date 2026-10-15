"""关键词检索器（纯文本检索，不使用向量）。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.nlp.utils.indexing_tokenizer import token_string
from __001__rag.retrieval.base import BaseRetriever
from __001__rag.search import es_service
from __001__rag.search.base import MatchTextExpr, SearchResult
from __001__rag.search.constants import CHUNK_SELECT_FIELDS_WITH_KB, TEXT_SEARCH_FIELDS


class KeywordRetriever(BaseRetriever):
    """关键词检索：仅通过文本匹配（MatchTextExpr）检索，不使用向量。"""

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

        tokenized = token_string(question)
        logger.info(
            "ES检索[keyword] kb_ids={} question_len={} tokenized_len={} top_n={} top_k={} minimum_should_match={}",
            kb_ids, len(question), len(tokenized), size, top_k,
            float(getattr(settings, "RETRIEVAL_MINIMUM_SHOULD_MATCH", 0.3)),
        )
        logger.info("ES检索[keyword] tokenized_query={}", tokenized)

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