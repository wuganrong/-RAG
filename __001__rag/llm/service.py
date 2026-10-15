"""LLM 业务调用门面。"""

from __future__ import annotations

# 1. Python 标准库
import time
from collections.abc import Iterable

# 2. 第三方库
from loguru import logger

# 3. 本地应用
from __001__rag.llm.base import ChatMessage, ChatRequest, ChatResponse
from __001__rag.llm.factory import build_chat_model, build_embedding_model, build_rerank_model


def _mask_key(api_key: str | None) -> str:
    """脱敏 API Key，仅保留末 4 位。"""
    if not api_key:
        return "-"
    return f"***{api_key[-4:]}" if len(api_key) > 4 else "***"


def _config_info(config) -> str:
    """格式化模型配置信息。"""
    return "model={} api_base={} factory={} api_key={}".format(
        config.model_name, config.api_base, config.factory or "-",
        _mask_key(config.api_key),
    )


class LLMService:
    """对业务层暴露统一的 LLM 调用入口。"""

    @staticmethod
    def chat(
        messages: list[ChatMessage],
        model_name: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        extra: dict | None = None,
    ) -> ChatResponse:
        start = time.monotonic()
        model = build_chat_model(model_name)
        request = ChatRequest(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            extra=extra or {},
        )
        try:
            result = model.chat(request)
            elapsed = (time.monotonic() - start) * 1000
            content = result.content or ""
            logger.info(
                "[LLM.chat] {} elapsed={:.1f}ms tokens={} content={}",
                _config_info(model.config), elapsed, result.total_tokens,
                content[:200] + ("..." if len(content) > 200 else ""),
            )
            return result
        except Exception:
            logger.exception("LLM.chat failed model={}", model_name)
            raise

    @staticmethod
    def stream_chat(
        messages: list[ChatMessage],
        model_name: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        extra: dict | None = None,
    ) -> Iterable[str]:
        start = time.monotonic()
        model = build_chat_model(model_name)
        request = ChatRequest(
            messages=messages,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            stream=True,
            extra=extra or {},
        )
        try:
            stream = model.stream_chat(request)
        except Exception:
            logger.exception("LLM.stream_chat failed model={}", model_name)
            raise

        config_info = _config_info(model.config)

        def _traced_stream():
            chunk_count = 0
            try:
                for chunk in stream:
                    chunk_count += 1
                    print(chunk, end="", flush=True)
                    yield chunk
            finally:
                elapsed = (time.monotonic() - start) * 1000
                logger.info(
                    "[LLM.stream_chat] {} elapsed={:.1f}ms chunks={}",
                    config_info, elapsed, chunk_count,
                )

        return _traced_stream()

    @staticmethod
    def embed(texts: list[str], model_name: str | None = None) -> list[list[float]]:
        start = time.monotonic()
        model = build_embedding_model(model_name)
        try:
            result = model.encode(texts)
            elapsed = (time.monotonic() - start) * 1000
            dim = len(result[0]) if result else 0
            logger.info(
                "[LLM.embed] {} elapsed={:.1f}ms count={} dim={}",
                _config_info(model.config), elapsed, len(result), dim,
            )
            return result
        except Exception:
            logger.exception("LLM.embed failed model={} count={}", model_name, len(texts))
            raise

    @staticmethod
    def rerank(
        query: str,
        documents: list[str],
        model_name: str | None = None,
        topn: int | None = None,
    ) -> list[tuple[int, float]]:
        start = time.monotonic()
        model = build_rerank_model(model_name)
        try:
            result = model.rerank(query=query, documents=documents, topn=topn)
            elapsed = (time.monotonic() - start) * 1000
            top1_score = result[0][1] if result else 0
            logger.info(
                "[LLM.rerank] {} elapsed={:.1f}ms doc_count={} top1_score={:.4f}",
                _config_info(model.config), elapsed, len(documents), top1_score,
            )
            return result
        except Exception:
            logger.exception("LLM.rerank failed model={} doc_count={}", model_name, len(documents))
            raise
