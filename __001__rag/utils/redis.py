"""Redis JSON 序列化辅助函数。"""

from __future__ import annotations

# 1. Python 标准库
import json
from typing import Any


def redis_json_dumps(value: Any) -> str:
    """按项目接口习惯序列化 Redis JSON 值。"""
    return json.dumps(value, ensure_ascii=False)


def redis_json_loads(value: str | bytes | None, default: Any = None) -> Any:
    """反序列化 Redis JSON 值，空值返回 default。"""
    if value is None:
        return default
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    return json.loads(value)
