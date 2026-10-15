"""检索增强管道：使用 FulltextQueryer 单例进行同义词替换 + 关键词权重计算。

替代原先的 _replace_synonyms（简单文本替换）和 _keyword_extraction（LLM 关键词提取）。
"""

from __future__ import annotations

# 2. 第三方库
from django.conf import settings
from loguru import logger

# 3. 本地应用
import __001__rag.nlp.query as q_mod
import __001__rag.nlp.synonym as syn_mod
from __001__rag.search.base import MatchTextExpr
from __001__rag.startup import wait_nlp_ready


def _get_synonym_dealer():
    """获取同义词单例；若后台加载未完成则等待，超时后回退新建。"""
    if syn_mod.dealer is not None:
        return syn_mod.dealer

    _nlp_timeout = float(getattr(settings, "NLP_TOKENIZER_READY_TIMEOUT", 30.0))
    if wait_nlp_ready(timeout=_nlp_timeout) and syn_mod.dealer is not None:
        return syn_mod.dealer

    logger.info("同义词单例仍未就绪，回退新建（首次查询可能较慢）")
    syn_mod.dealer = syn_mod.Dealer()
    return syn_mod.dealer


def _get_queryer():
    """获取 FulltextQueryer 单例；若后台加载未完成则等待，超时后回退新建。"""
    if q_mod.queryer is not None:
        return q_mod.queryer

    _nlp_timeout = float(getattr(settings, "NLP_TOKENIZER_READY_TIMEOUT", 30.0))
    if wait_nlp_ready(timeout=_nlp_timeout) and q_mod.queryer is not None:
        return q_mod.queryer

    logger.info("FulltextQueryer 单例仍未就绪，回退新建（首次查询可能较慢）")
    q_mod.queryer = q_mod.FulltextQueryer()
    return q_mod.queryer


def _enhance_query(question: str) -> tuple[str, MatchTextExpr | None]:
    """用 FulltextQueryer 增强查询：同义词替换 + 关键词权重计算。

    Returns:
        (enhanced_question, match_expr):
        - enhanced_question: 原始问题拼接关键词（用于向量检索的 embedding）
        - match_expr: ES 全文检索的复杂查询表达式（用于 BM25 检索），可能为 None
    """
    # 1. ReplaceSynonym 表做问句级文本替换
    syn_dealer = _get_synonym_dealer()
    replaced = syn_dealer.replace_questions([question])[0]

    # 2. FulltextQueryer 构建加权查询表达式
    queryer = _get_queryer()
    match_expr, keywords = queryer.question(replaced)

    # 3. 拼接关键词到问题文本（用于向量检索）
    if keywords:
        enhanced = f"{replaced} {' '.join(keywords)}"
    else:
        enhanced = replaced

    if enhanced != question:
        logger.info(
            "检索增强 before_len={} after_len={} keywords_count={}",
            len(question), len(enhanced), len(keywords),
        )

    return enhanced, match_expr
