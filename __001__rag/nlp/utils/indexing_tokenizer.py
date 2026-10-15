"""切片索引使用的分词辅助函数。"""

from __future__ import annotations

# 1. Python 标准库
import hashlib
import importlib
import re
from collections.abc import Iterable

# 2. 第三方库
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.startup import wait_nlp_ready

_TOKEN_RE = re.compile(r"[一-鿿]|[A-Za-z0-9_]+(?:[-.][A-Za-z0-9_]+)*", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def _get_ready_tokenizer():
    """获取已加载词典的自定义分词器模块。"""
    tokenizer_mod = importlib.import_module("__001__rag.nlp.tokenizer")

    if len(tokenizer_mod.tokenizer.trie_) > 0:
        return tokenizer_mod

    try:
        _nlp_timeout = float(getattr(settings, "NLP_TOKENIZER_READY_TIMEOUT", 30.0))
        wait_nlp_ready(timeout=_nlp_timeout)
    except Exception as exc:
        logger.info("等待 NLP 后台加载失败，准备同步加载词典 error={}", exc)

    if len(tokenizer_mod.tokenizer.trie_) > 0:
        return tokenizer_mod

    logger.info("自定义分词器词典未就绪，开始同步加载")
    try:
        tokenizer_mod.tokenizer.load_dict()
    except Exception:
        logger.info("自定义分词器同步加载失败，将使用当前词典状态")
    return tokenizer_mod


def rag_tokenize(text: str) -> list[str]:
    """Tokenize mixed Chinese/English text without external NLP dependencies."""
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text or "")]


def token_string(text: str) -> str:
    """返回 `*_tks` 字段使用的自定义分词结果。"""
    tokenizer_mod = _get_ready_tokenizer()
    return tokenizer_mod.tokenize(text or "")


def small_token_string(text: str) -> str:
    """返回 `*_sm_tks` 字段使用的细粒度分词结果。"""
    tokenizer_mod = _get_ready_tokenizer()
    return tokenizer_mod.fine_grained_tokenize(tokenizer_mod.tokenize(text or ""))


def estimate_token_count(text: str) -> int:
    """Estimate token count with a deterministic local tokenizer."""
    tokens = rag_tokenize(text)
    if tokens:
        return len(tokens)
    stripped = _SPACE_RE.sub("", text or "")
    return max(1, len(stripped) // 2) if stripped else 0


def estimate_many_token_count(texts: Iterable[str]) -> int:
    """Estimate total token count for a sequence of text fragments."""
    return sum(estimate_token_count(text) for text in texts if text)


def make_chunk_id(doc_id: str, order: int, content: str) -> str:
    """Build a stable chunk id from __003__document id, order and content."""
    digest = hashlib.sha1(f"{doc_id}:{order}:{content}".encode("utf-8")).hexdigest()
    return digest[:32]


def build_token_metadata(content: str, title: str | None = None) -> dict[str, str]:
    """Build common token fields expected by the search index."""
    title_text = title or ""
    return {
        "content_ltks": token_string(content),
        "content_sm_ltks": small_token_string(content),
        "title_tks": token_string(title_text),
        "title_sm_tks": small_token_string(title_text),
    }
