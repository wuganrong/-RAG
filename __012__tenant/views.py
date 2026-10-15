"""租户与用户角色管理接口。"""

from __future__ import annotations

from typing import Any

from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from django.db.models import Sum

from __001__rag.models import Document, Tenant, TenantQuota, UsageLog, UserRole
from __001__rag.ops import request_tenant_id, request_user_id, require_role, write_audit
from __001__rag.utils import error_response, format_datetime, get_uuid, success_response

from .serializers import (
    TenantIdSerializer,
    TenantSaveSerializer,
    UserRoleIdSerializer,
    UserRoleListSerializer,
    UserRoleSaveSerializer,
    TenantQuotaSerializer,
)


def _tenant_to_dict(row: Tenant) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "description": row.description or "",
        "status": row.status,
        "create_date": format_datetime(row.create_date),
        "update_date": format_datetime(row.update_date),
    }


def _user_role_to_dict(row: UserRole) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "user_id": row.user_id,
        "user_name": row.user_name or "",
        "role": row.role,
        "status": row.status,
        "create_date": format_datetime(row.create_date),
        "update_date": format_datetime(row.update_date),
    }


def _quota_to_dict(row: TenantQuota, usage: dict[str, Any] | None = None) -> dict[str, Any]:
    usage = usage or {}
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "storage_quota_mb": row.storage_quota_mb,
        "document_quota": row.document_quota,
        "token_quota": row.token_quota,
        "vision_page_quota": row.vision_page_quota,
        "model_call_quota": row.model_call_quota,
        "status": row.status,
        "usage": usage,
        "update_date": format_datetime(row.update_date),
    }


def _quota_usage(tenant_id: str) -> dict[str, Any]:
    docs = Document.objects.filter(tenant_id=tenant_id)
    usage = UsageLog.objects.filter(tenant_id=tenant_id)
    return {
        "storage_used_mb": round(float((docs.aggregate(v=Sum("size"))["v"] or 0) / 1024 / 1024), 2),
        "document_used": docs.count(),
        "token_used": usage.aggregate(v=Sum("total_tokens"))["v"] or 0,
        "vision_page_used": docs.aggregate(v=Sum("page_num"))["v"] or 0,
        "model_call_used": usage.count(),
    }


def _get_or_create_quota(tenant_id: str) -> TenantQuota:
    row, _ = TenantQuota.objects.get_or_create(
        tenant_id=tenant_id,
        defaults={"id": get_uuid()},
    )
    return row


@extend_schema(tags=["tenant"], summary="租户列表", responses={200: None})
@api_view(["GET"])
def tenant_list(request: Request) -> Response:
    rows = Tenant.objects.all().order_by("-create_date", "name")
    return success_response([_tenant_to_dict(row) for row in rows])


@extend_schema(tags=["tenant"], summary="新增或更新租户", request=TenantSaveSerializer, responses={200: None})
@api_view(["POST"])
def tenant_save(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = TenantSaveSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("id") or get_uuid()
    existed = Tenant.objects.filter(name=vd["name"]).exclude(id=tenant_id).exists()
    if existed:
        return error_response("租户名称已存在。")
    tenant, _ = Tenant.objects.get_or_create(id=tenant_id, defaults={"name": vd["name"]})
    tenant.name = vd["name"]
    tenant.description = vd.get("description") or ""
    tenant.status = vd.get("status") or "1"
    tenant.save()
    write_audit(tenant_id=tenant.id, user_id=request_user_id(request), action="save", resource_type="tenant", resource_id=tenant.id, detail=_tenant_to_dict(tenant))
    return success_response(_tenant_to_dict(tenant))


@extend_schema(tags=["tenant"], summary="删除租户", request=TenantIdSerializer, responses={200: None})
@api_view(["POST"])
def tenant_rm(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = TenantIdSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    tenant_id = ser.validated_data["id"]
    if tenant_id == "default":
        return error_response("默认租户不能删除。")
    deleted, _ = Tenant.objects.filter(id=tenant_id).delete()
    UserRole.objects.filter(tenant_id=tenant_id).delete()
    write_audit(tenant_id=request_tenant_id(request), user_id=request_user_id(request), action="delete", resource_type="tenant", resource_id=tenant_id)
    return success_response({"deleted": deleted})


@extend_schema(
    tags=["tenant"],
    summary="用户角色列表",
    parameters=[OpenApiParameter("tenant_id", OpenApiTypes.STR, required=False, description="租户 ID")],
    responses={200: None},
)
@api_view(["GET"])
def user_role_list(request: Request) -> Response:
    ser = UserRoleListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    qs = UserRole.objects.all().order_by("tenant_id", "user_id")
    tenant_id = ser.validated_data.get("tenant_id") or ""
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    return success_response([_user_role_to_dict(row) for row in qs])


@extend_schema(tags=["tenant"], summary="新增或更新用户角色", request=UserRoleSaveSerializer, responses={200: None})
@api_view(["POST"])
def user_role_save(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = UserRoleSaveSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or "default"
    if not Tenant.objects.filter(id=tenant_id, status="1").exists() and tenant_id != "default":
        return error_response("租户不存在或已禁用。")
    if vd.get("id"):
        row, _ = UserRole.objects.get_or_create(id=vd["id"], defaults={"tenant_id": tenant_id, "user_id": vd["user_id"]})
    else:
        row, _ = UserRole.objects.get_or_create(tenant_id=tenant_id, user_id=vd["user_id"], defaults={"id": get_uuid()})
    row.tenant_id = tenant_id
    row.user_id = vd["user_id"]
    row.user_name = vd.get("user_name") or ""
    row.role = vd.get("role") or "viewer"
    row.status = vd.get("status") or "1"
    row.save()
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="save", resource_type="user_role", resource_id=row.id, detail=_user_role_to_dict(row))
    return success_response(_user_role_to_dict(row))


@extend_schema(tags=["tenant"], summary="删除用户角色", request=UserRoleIdSerializer, responses={200: None})
@api_view(["POST"])
def user_role_rm(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = UserRoleIdSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    role_id = ser.validated_data["id"]
    row = UserRole.objects.filter(id=role_id).first()
    deleted, _ = UserRole.objects.filter(id=role_id).delete()
    write_audit(tenant_id=row.tenant_id if row else request_tenant_id(request), user_id=request_user_id(request), action="delete", resource_type="user_role", resource_id=role_id)
    return success_response({"deleted": deleted})


@extend_schema(tags=["tenant"], summary="租户配额详情", responses={200: None})
@api_view(["GET"])
def quota_get(request: Request) -> Response:
    tenant_id = request.GET.get("tenant_id") or request_tenant_id(request)
    row = _get_or_create_quota(tenant_id)
    return success_response(_quota_to_dict(row, _quota_usage(tenant_id)))


@extend_schema(tags=["tenant"], summary="保存租户配额", request=TenantQuotaSerializer, responses={200: None})
@api_view(["POST"])
def quota_save(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = TenantQuotaSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    row = _get_or_create_quota(tenant_id)
    for field in ("storage_quota_mb", "document_quota", "token_quota", "vision_page_quota", "model_call_quota", "status"):
        if field in vd:
            setattr(row, field, vd[field])
    row.save()
    payload = _quota_to_dict(row, _quota_usage(tenant_id))
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="save", resource_type="tenant_quota", resource_id=row.id, detail=payload)
    return success_response(payload)
