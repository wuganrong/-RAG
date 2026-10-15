"""LLM 响应解析工具。"""

from __future__ import annotations

# 1. Python 标准库
import json
import re


def extract_json_from_llm_response(raw: str) -> dict | None:
    """从 LLM 原始输出中解析 JSON 对象。

    依次尝试: 直接 json.loads → markdown code fence → 正则提取首对花括号。
    """
    if not raw:
        return None
    # 1. 直接解析
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    # 2. 提取 ```json ... ``` 或 ``` ... ``` 中的内容
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    # 3. 尝试找到第一个 JSON 对象
    match = re.search(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(0))
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def extract_list_from_llm_response(raw: str) -> list:
    """提取 LLM 响应中的列表。直接 json.loads 或提取第一个 [...] 。"""
    if not raw:
        return []
    try:
        result = json.loads(raw)
        if isinstance(result, list):
            return result
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(1))
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, TypeError):
            pass
    match = re.search(r"\[.*\]", raw, re.DOTALL)
    if match:
        try:
            result = json.loads(match.group(0))
            if isinstance(result, list):
                return result
        except (json.JSONDecodeError, TypeError):
            pass
    return []
