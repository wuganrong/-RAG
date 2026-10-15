"""LLM 调用相关通用工具。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any
from urllib.parse import urljoin


def normalize_api_base(api_base: str) -> str:
    """规范化 OpenAI 兼容接口 base_url。"""
    normalized = (api_base or "").strip()
    if not normalized:
        raise ValueError("api_base 不能为空")
    return normalized.rstrip("/")


def derive_rerank_endpoint(api_base: str) -> str:
    """从 api_base 派生 rerank endpoint。"""
    normalized = normalize_api_base(api_base)
    lowered = normalized.lower()
    if "dashscope.aliyuncs.com" in lowered:
        return "https://dashscope.aliyuncs.com/compatible-api/v1/reranks"
    if lowered.endswith("/rerank"):
        return normalized
    return urljoin(f"{normalized}/", "rerank")


def get_usage_value(usage: Any, name: str, default: int = 0) -> int:
    """兼容 SDK 对象和字典格式的 usage 字段读取。"""
    if usage is None:
        return default
    if isinstance(usage, dict):
        value = usage.get(name, default)
    else:
        value = getattr(usage, name, default)
    return int(value or default)


def normalize_rerank_results(payload: Any) -> list[tuple[int, float]]:
    """标准化常见 OpenAI 兼容 rerank 响应。"""
    if isinstance(payload, dict):
        output = payload.get("output") if isinstance(payload.get("output"), dict) else {}
        candidates = (
            payload.get("results")
            or payload.get("data")
            or output.get("results")
            or []
        )
    else:
        candidates = payload or []

    results: list[tuple[int, float]] = []
    for item in candidates:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        if index is None:
            document = item.get("document")
            if isinstance(document, dict):
                index = document.get("index")
        score = item.get("relevance_score", item.get("score"))
        if index is None or score is None:
            continue
        results.append((int(index), float(score)))

    results.sort(key=lambda value: value[1], reverse=True)
    return results
