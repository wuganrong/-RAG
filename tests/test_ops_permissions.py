"""权限、审计和用量底座测试。"""

from __future__ import annotations

import pytest
from django.test import RequestFactory

from __001__rag.models import AuditLog, UsageLog, UserRole
from __001__rag.ops import has_role, request_tenant_id, request_user_id, require_role, write_audit, write_usage


@pytest.mark.django_db
def test_has_role_allows_admin_shortcut():
    assert has_role("tenant-a", "admin", "admin") is True


@pytest.mark.django_db
def test_has_role_checks_persisted_user_role():
    UserRole.objects.create(
        id="role-1",
        tenant_id="tenant-a",
        user_id="u-100",
        user_name="张三",
        role="editor",
        status="1",
    )

    assert has_role("tenant-a", "u-100", "viewer") is True
    assert has_role("tenant-a", "u-100", "editor") is True
    assert has_role("tenant-a", "u-100", "admin") is False


@pytest.mark.django_db
def test_require_role_returns_403_response_when_role_is_missing():
    request = RequestFactory().get("/v1/kb/list", HTTP_X_TENANT_ID="tenant-a", HTTP_X_USER_ID="u-404")

    response = require_role(request, "viewer")

    assert response is not None
    assert response.status_code == 200
    assert response.data["code"] == 403


def test_request_context_prefers_middleware_attributes():
    request = RequestFactory().get("/v1/kb/list", HTTP_X_TENANT_ID="from-header", HTTP_X_USER_ID="from-header")
    request.tenant_id = "from-middleware"
    request.user_id = "from-middleware"

    assert request_tenant_id(request) == "from-middleware"
    assert request_user_id(request) == "from-middleware"


@pytest.mark.django_db
def test_write_audit_and_usage_logs():
    write_audit(
        tenant_id="tenant-a",
        user_id="u-100",
        action="kb.create",
        resource_type="knowledgebase",
        resource_id="kb-1",
        detail={"name": "测试知识库"},
    )
    write_usage(
        tenant_id="tenant-a",
        user_id="u-100",
        conversation_id="c-1",
        kb_ids=["kb-1"],
        model="deepseek",
        call_type="chat",
        prompt_tokens=10,
        completion_tokens=20,
    )

    assert AuditLog.objects.filter(tenant_id="tenant-a", action="kb.create").count() == 1
    usage = UsageLog.objects.get(tenant_id="tenant-a", conversation_id="c-1")
    assert usage.total_tokens == 30
