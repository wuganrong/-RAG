"""ID 相关工具函数。"""

from __future__ import annotations

# 1. Python 标准库
import secrets
import time
import uuid


def get_uuid() -> str:
    """生成 32 位无连字符的 UUID。"""
    return uuid.uuid4().hex


def get_numeric_id() -> int:
    """生成可存入 BigIntegerField 的毫秒级数字 ID。"""
    return int(time.time() * 1000) * 100000 + secrets.randbelow(100000)
