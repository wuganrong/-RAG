"""DRF 全局异常处理器 — 统一捕获未处理异常并记录日志。"""

from __future__ import annotations

# 2. 第三方库
from loguru import logger
from rest_framework.views import exception_handler

# 3. 本地应用
from __001__rag.utils.responses import error_response


def custom_exception_handler(exc, context):
    """捕获所有未处理的 DRF / 视图异常，统一日志和响应格式。

    - DRF 内置异常（ValidationError、NotFound 等）：记录 info + 交默认处理
    - 非 DRF 异常（500 级别）：记录 exception（含堆栈）+ 返回通用 500
    """
    view = context.get("view")
    view_name = view.__class__.__name__ if view else "unknown"
    request = context.get("request")
    method = getattr(request, "method", "?")
    path = getattr(request, "path", "?")

    # DRF 内置异常 → 交给默认处理器
    response = exception_handler(exc, context)
    if response is not None:
        logger.info(
            "HTTP {} {} DRF 异常 view={} status={} detail={}",
            method,
            path,
            view_name,
            response.status_code,
            response.data,
        )
        return response

    # 非 DRF 异常（500 级别）→ 记录完整堆栈
    logger.exception("HTTP {} {} 未处理异常 view={}", method, path, view_name)
    return error_response("服务器内部错误", code=500)
