"""问题生成相关的纯工具函数。"""

from __future__ import annotations

# 1. Python 标准库
import json
import math
import re
from typing import Any


def strip_thinking(text: str) -> str:
    """移除 LLM 返回中的 <think> 块。"""
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def clean_list_item(text: str) -> str:
    """清理 LLM 列表项中的编号和多余标点。"""
    item = (text or "").strip()
    item = re.sub(r"^\s*[-*•]\s*", "", item)
    item = re.sub(r"^\s*\d+[.、)]\s*", "", item)
    return item.strip(" \t\r\n\"'，,；;")


def dedupe_nonempty(items: Any) -> list[str]:
    """保持顺序的非空去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        cleaned = clean_list_item(str(item))
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        result.append(cleaned)
    return result


def parse_question_list(text: str, topn: int) -> list[str]:
    """从 LLM 返回文本中解析问题列表。"""
    payload = (text or "").strip()
    if not payload:
        return []

    payload = re.sub(r"^```(?:json)?\s*", "", payload, flags=re.IGNORECASE)
    payload = re.sub(r"\s*```$", "", payload)

    for candidate in _json_candidates(payload):
        try:
            data = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        questions = _questions_from_json(data)
        if questions:
            return questions[:topn]

    parts = [line for line in payload.splitlines() if line.strip()]
    return dedupe_nonempty(clean_list_item(part) for part in parts)[:topn]


def _json_candidates(payload: str) -> list[str]:
    """生成 JSON 解析候选字符串。"""
    candidates = [payload]
    array_start = payload.find("[")
    array_end = payload.rfind("]")
    if array_start >= 0 and array_end > array_start:
        candidates.append(payload[array_start:array_end + 1])
    object_start = payload.find("{")
    object_end = payload.rfind("}")
    if object_start >= 0 and object_end > object_start:
        candidates.append(payload[object_start:object_end + 1])
    return candidates


def _questions_from_json(data: Any) -> list[str]:
    """从解析后的 JSON 中提取问题列表。"""
    if isinstance(data, list):
        return dedupe_nonempty(str(item) for item in data)
    if isinstance(data, dict):
        for key in ("questions", "question_kwd", "items", "data"):
            value = data.get(key)
            if isinstance(value, list):
                return dedupe_nonempty(str(item) for item in value)
    return []


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    """将值钳制在 [minimum, maximum] 范围内的整数。"""
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))
