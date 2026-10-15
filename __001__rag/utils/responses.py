"""DRF 响应相关工具函数。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from rest_framework.response import Response


def success_response(data: Any = None, msg: str = "success") -> Response:
    """返回统一格式的成功响应。"""
    return Response({"code": 0, "msg": msg, "data": data})


def error_response(msg: str, code: int = 400) -> Response:
    """返回统一格式的错误响应。"""
    return Response({"code": code, "msg": msg, "data": None})
