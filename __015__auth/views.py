"""轻量登录认证接口。"""

from __future__ import annotations

from django.core import signing
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from __001__rag.models import Tenant, UserRole
from __001__rag.ops import request_tenant_id, request_user_id, write_audit
from __001__rag.utils import error_response, success_response

_SALT = "yf-rag-auth-token"
_MAX_AGE = 60 * 60 * 12


def make_token(tenant_id: str, user_id: str, role: str) -> str:
    return signing.dumps({"tenant_id": tenant_id, "user_id": user_id, "role": role}, salt=_SALT)


def read_token(token: str) -> dict | None:
    try:
        return signing.loads(token, salt=_SALT, max_age=_MAX_AGE)
    except signing.BadSignature:
        return None


@api_view(["POST"])
def login(request: Request) -> Response:
    data = request.data if isinstance(request.data, dict) else {}
    tenant_id = str(data.get("tenant_id") or "default").strip() or "default"
    user_id = str(data.get("user_id") or "").strip()
    if not user_id:
        return error_response("user_id 不能为空。", code=400)
    if tenant_id != "default" and not Tenant.objects.filter(id=tenant_id, status="1").exists():
        return error_response("租户不存在或已禁用。", code=403)
    role = UserRole.objects.filter(tenant_id=tenant_id, user_id=user_id, status="1").first()
    if role is None:
        return error_response("用户不存在或未启用。", code=403)
    token = make_token(tenant_id, user_id, role.role)
    write_audit(tenant_id=tenant_id, user_id=user_id, action="login", resource_type="auth", resource_id=user_id)
    return success_response({
        "token": token,
        "expires_in": _MAX_AGE,
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role.role,
        "user_name": role.user_name or "",
    })


@api_view(["GET"])
def me(request: Request) -> Response:
    tenant_id = request_tenant_id(request)
    user_id = request_user_id(request)
    role = UserRole.objects.filter(tenant_id=tenant_id, user_id=user_id, status="1").first()
    return success_response({
        "tenant_id": tenant_id,
        "user_id": user_id,
        "role": role.role if role else "",
        "user_name": role.user_name if role else "",
    })


@api_view(["POST"])
def logout(request: Request) -> Response:
    write_audit(
        tenant_id=request_tenant_id(request),
        user_id=request_user_id(request),
        action="logout",
        resource_type="auth",
        resource_id=request_user_id(request),
    )
    return success_response(True)
