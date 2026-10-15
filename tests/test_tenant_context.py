"""租户和用户上下文中间件测试。"""

from __future__ import annotations

from django.test import RequestFactory, override_settings

from __000__django.middleware import TenantAuthContextMiddleware


def _ok_response(request):
    request._middleware_seen = True
    from django.http import JsonResponse

    return JsonResponse({"ok": True})


def test_tenant_context_defaults_to_experiment_values():
    request = RequestFactory().get("/v1/kb/list")
    response = TenantAuthContextMiddleware(_ok_response)(request)

    assert response.status_code == 200
    assert request.tenant_id == "default"
    assert request.user_id == "admin"


def test_tenant_context_reads_request_headers():
    request = RequestFactory().get(
        "/v1/kb/list",
        HTTP_X_TENANT_ID="tenant-a",
        HTTP_X_USER_ID="u-100",
    )
    response = TenantAuthContextMiddleware(_ok_response)(request)

    assert response.status_code == 200
    assert request.tenant_id == "tenant-a"
    assert request.user_id == "u-100"


@override_settings()
def test_tenant_context_can_require_explicit_user_header(monkeypatch):
    monkeypatch.setenv("REQUIRE_AUTH", "1")
    request = RequestFactory().get("/v1/kb/list", HTTP_X_TENANT_ID="tenant-a")

    response = TenantAuthContextMiddleware(_ok_response)(request)

    assert response.status_code == 403
