"""Django 中间件 — 请求日志与 trace_id 注入。"""

from __future__ import annotations

# 1. Python 标准库
import time
import os

# 2. 第三方库
from django.http import JsonResponse
from loguru import logger

# 3. 本地应用
from __001__rag.utils.context import set_trace_id
from __015__auth.views import read_token


class RequestLoggingMiddleware:
    """为每个 HTTP 请求注入 trace_id 并记录入口/出口日志。"""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        trace_id = set_trace_id()
        request.trace_id = trace_id

        start = time.monotonic()
        response = self.get_response(request)
        elapsed = (time.monotonic() - start) * 1000

        logger.info(
            "HTTP {} {} status={} elapsed={:.1f}ms",
            request.method,
            request.path,
            response.status_code,
            elapsed,
        )
        return response


class TenantAuthContextMiddleware:
    """统一注入租户和用户上下文。

    默认兼容实验环境：没有请求头时使用 default/admin。
    设置 REQUIRE_AUTH=1 后，/v1/ API 必须显式传 X-User-Id。
    """

    def __init__(self, get_response):
        self.get_response = get_response
        self.require_auth = os.environ.get("REQUIRE_AUTH", "0").lower() in {"1", "true", "yes"}

    def __call__(self, request):
        token_payload = None
        auth_header = request.headers.get("Authorization", "")
        if auth_header.lower().startswith("bearer "):
            token_payload = read_token(auth_header.split(" ", 1)[1].strip())

        tenant_id = (
            (token_payload or {}).get("tenant_id")
            or
            request.headers.get("X-Tenant-Id")
            or request.GET.get("tenant_id")
            or "default"
        )
        user_id = (
            (token_payload or {}).get("user_id")
            or
            request.headers.get("X-User-Id")
            or request.GET.get("user_id")
            or "admin"
        )
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            data = getattr(request, "data", None)
            if isinstance(data, dict):
                tenant_id = data.get("tenant_id") or tenant_id
                user_id = data.get("user_id") or user_id

        if self.require_auth and request.path.startswith("/v1/") and request.path != "/v1/auth/login":
            if not request.headers.get("X-User-Id") and token_payload is None:
                return JsonResponse({"code": 403, "message": "缺少认证信息。", "data": None}, status=403)

        request.tenant_id = tenant_id
        request.user_id = user_id
        return self.get_response(request)
