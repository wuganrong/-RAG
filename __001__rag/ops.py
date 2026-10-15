"""生产化底座：权限、审计和用量记录。"""

from __future__ import annotations

from typing import Any

from __001__rag.models import AuditLog, KnowledgebaseAcl, UsageLog, UserRole
from __001__rag.utils.responses import error_response
from __001__rag.utils.ids import get_uuid


ROLE_LEVEL = {"viewer": 1, "editor": 2, "admin": 3}
ACL_LEVEL = {"read": 1, "write": 2, "admin": 3}


def request_user_id(request, fallback: str = "admin") -> str:
    if getattr(request, "user_id", None):
        return request.user_id
    data = getattr(request, "data", {}) if isinstance(getattr(request, "data", {}), dict) else {}
    return (
        request.headers.get("X-User-Id")
        or data.get("user_id")
        or request.GET.get("user_id")
        or fallback
    )


def request_tenant_id(request, fallback: str = "default") -> str:
    if getattr(request, "tenant_id", None):
        return request.tenant_id
    data = getattr(request, "data", {}) if isinstance(getattr(request, "data", {}), dict) else {}
    return (
        request.headers.get("X-Tenant-Id")
        or data.get("tenant_id")
        or request.GET.get("tenant_id")
        or fallback
    )


def has_role(tenant_id: str, user_id: str, min_role: str) -> bool:
    if not user_id:
        return False
    if user_id == "admin":
        return True
    row = UserRole.objects.filter(tenant_id=tenant_id, user_id=user_id, status="1").first()
    if not row:
        return False
    return ROLE_LEVEL.get(row.role, 0) >= ROLE_LEVEL.get(min_role, 0)


def require_role(request, min_role: str = "viewer"):
    """返回 None 表示通过，否则返回 DRF Response。"""
    tenant_id = request_tenant_id(request)
    user_id = request_user_id(request)
    if has_role(tenant_id, user_id, min_role):
        return None
    return error_response(f"权限不足，需要 {min_role} 或更高角色。", code=403)


def user_role_name(tenant_id: str, user_id: str) -> str:
    if user_id == "admin":
        return "admin"
    row = UserRole.objects.filter(tenant_id=tenant_id, user_id=user_id, status="1").first()
    return row.role if row else ""


def can_access_kb(tenant_id: str, user_id: str, kb_id: str, min_permission: str = "read") -> bool:
    if has_role(tenant_id, user_id, "admin"):
        return True
    role = user_role_name(tenant_id, user_id)
    min_level = ACL_LEVEL.get(min_permission, 1)
    rows = KnowledgebaseAcl.objects.filter(tenant_id=tenant_id, kb_id=kb_id, status="1").filter(
        subject_type="user", subject_id=user_id
    )
    if role:
        rows = rows.union(KnowledgebaseAcl.objects.filter(tenant_id=tenant_id, kb_id=kb_id, status="1", subject_type="role", subject_id=role))
    return any(ACL_LEVEL.get(row.permission, 0) >= min_level for row in rows)


def require_kb_access(request, kb_id: str, min_permission: str = "read"):
    tenant_id = request_tenant_id(request)
    user_id = request_user_id(request)
    if can_access_kb(tenant_id, user_id, kb_id, min_permission):
        return None
    return error_response(f"无权访问该知识库，需要 {min_permission} 权限。", code=403)


def write_audit(
    *,
    tenant_id: str = "default",
    user_id: str = "",
    action: str,
    resource_type: str,
    resource_id: str = "",
    detail: dict[str, Any] | None = None,
    status: str = "success",
) -> None:
    AuditLog.objects.create(
        id=get_uuid(),
        tenant_id=tenant_id or "default",
        user_id=user_id or "",
        action=action,
        resource_type=resource_type,
        resource_id=resource_id or "",
        detail=detail or {},
        status=status,
    )


def write_usage(
    *,
    tenant_id: str = "default",
    user_id: str = "",
    conversation_id: str = "",
    kb_ids: list[str] | None = None,
    model: str = "",
    call_type: str = "chat",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    duration_ms: int = 0,
    status: str = "success",
    error: str = "",
) -> None:
    UsageLog.objects.create(
        id=get_uuid(),
        tenant_id=tenant_id or "default",
        user_id=user_id or "",
        conversation_id=conversation_id or "",
        kb_ids=kb_ids or [],
        model=model or "",
        call_type=call_type,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=max(0, prompt_tokens) + max(0, completion_tokens),
        duration_ms=max(0, duration_ms),
        status=status,
        error=error or "",
    )
