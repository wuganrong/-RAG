"""LLM 接口视图。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.db.models import Q
from drf_spectacular.utils import extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.models import LLM as LLMModel
from __001__rag.models import APIKeyRotationLog, LLMFactories
from __001__rag.llm.base import ChatMessage
from __001__rag.llm.service import LLMService
from __001__rag.ops import request_tenant_id, request_user_id, require_role, write_audit
from __001__rag.utils import error_response, success_response
from __001__rag.utils.ids import get_uuid
from __001__rag.utils.secrets import protect_secret, reveal_secret

from .serializers import (
    LLMCreateSerializer,
    LLMFactorySerializer,
    LLMIdSerializer,
    LLMListQuerySerializer,
    LLMListResponseSerializer,
    LLMStatusSerializer,
    LLMUpdateSerializer,
)


@extend_schema(
    tags=["llm"],
    summary="获取可用模型列表",
    description="返回已配置的 LLM 模型列表，按厂商分组；默认仅返回 model_type=chat 的模型，可通过查询参数覆盖。",
    parameters=[LLMListQuerySerializer],
    responses={200: LLMListResponseSerializer},
)
@api_view(["GET"])
def llm_list(request: Request) -> Response:
    qser = LLMListQuerySerializer(data=request.query_params)
    if not qser.is_valid():
        return error_response(str(qser.errors))
    model_type: str = qser.validated_data["model_type"]
    tenant_id: str = qser.validated_data.get("tenant_id") or request_tenant_id(request)
    model_type_key = model_type.lower()
    flat = request.query_params.get("flat") in {"1", "true", "True"}
    raw_model_type = request.query_params.get("model_type")

    try:
        query = Q()
        if not (flat and raw_model_type == ""):
            query = Q(model_type__iexact=model_type)

        tenant_llms = LLMModel.objects.filter(query, tenant_id=tenant_id).values(
            "id", "llm_name", "model_type", "fid", "max_tokens", "status", "tenant_id"
        )

        if flat:
            return success_response(list(tenant_llms.order_by("model_type", "fid", "llm_name")))

        available_factories = {llm["fid"] for llm in tenant_llms if llm["llm_name"] and llm["fid"]}

        all_llms = LLMModel.objects.filter(status="1", tenant_id=tenant_id, fid__in=available_factories)

        excluded_factories = {"Youdao", "FastEmbed", "BAAI"}
        self_deployed_factories = {"Ollama", "LocalAI"}

        llm_data = []
        for m in all_llms:
            if m.fid in excluded_factories:
                continue
            is_available = (
                m.fid in available_factories
                or m.llm_name.lower() == "flag-embedding"
                or m.fid in self_deployed_factories
            )
            llm_data.append({
                "id": m.id,
                "llm_name": m.llm_name,
                "model_type": m.model_type,
                "fid": m.fid,
                "max_tokens": m.max_tokens,
                "status": m.status,
                "available": is_available,
            })

        existing_keys = {(l["llm_name"], l["fid"]) for l in llm_data}
        for llm in tenant_llms:
            if (llm["llm_name"], llm["fid"]) not in existing_keys:
                llm_data.append({
                    "id": llm["id"],
                    "llm_name": llm["llm_name"],
                    "model_type": llm["model_type"],
                    "fid": llm["fid"],
                    "max_tokens": llm["max_tokens"],
                    "status": llm["status"],
                    "available": True,
                })

        result: dict[str, list[dict[str, Any]]] = {}
        for m in llm_data:
            if (m.get("model_type") or "").lower() != model_type_key:
                continue
            factory = m["fid"]
            if factory not in result:
                result[factory] = []
            result[factory].append(m)

        return success_response(result)
    except Exception:
        logger.exception("获取 LLM 列表失败")
        return error_response("Failed to fetch llm list", code=500)


@extend_schema(tags=["llm"], summary="创建模型", request=LLMCreateSerializer, responses={200: None})
@api_view(["POST"])
def llm_create(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = LLMCreateSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    if LLMModel.objects.filter(tenant_id=tenant_id, fid=vd["fid"], llm_name=vd["llm_name"]).exists():
        return error_response("同厂商下模型名称已存在。", code=400)
    model = LLMModel.objects.create(
        id=get_uuid(),
        llm_name=vd["llm_name"],
        model_type=vd["model_type"],
        fid=vd["fid"],
        tenant_id=tenant_id,
        max_tokens=vd.get("max_tokens") or 0,
        status=vd.get("status") or "1",
    )
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="create", resource_type="llm", resource_id=model.id, detail=_llm_to_dict(model))
    return success_response(_llm_to_dict(model))


@extend_schema(tags=["llm"], summary="更新模型", request=LLMUpdateSerializer, responses={200: None})
@api_view(["POST"])
def llm_update(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = LLMUpdateSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    try:
        model = LLMModel.objects.get(id=vd["id"], tenant_id=tenant_id)
    except LLMModel.DoesNotExist:
        return error_response("模型不存在。", code=404)
    dup = LLMModel.objects.filter(tenant_id=tenant_id, fid=vd["fid"], llm_name=vd["llm_name"]).exclude(id=model.id)
    if dup.exists():
        return error_response("同厂商下模型名称已存在。", code=400)
    model.llm_name = vd["llm_name"]
    model.model_type = vd["model_type"]
    model.fid = vd["fid"]
    model.tenant_id = tenant_id
    model.max_tokens = vd.get("max_tokens") or 0
    model.status = vd.get("status") or "1"
    model.save()
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="update", resource_type="llm", resource_id=model.id, detail=_llm_to_dict(model))
    return success_response(_llm_to_dict(model))


@extend_schema(tags=["llm"], summary="删除模型", request=LLMIdSerializer, responses={200: None})
@api_view(["POST"])
def llm_rm(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = LLMIdSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    model_id = ser.validated_data["id"]
    tenant_id = ser.validated_data.get("tenant_id") or request_tenant_id(request)
    deleted, _ = LLMModel.objects.filter(id=model_id, tenant_id=tenant_id).delete()
    if not deleted:
        return error_response("模型不存在。", code=404)
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="delete", resource_type="llm", resource_id=model_id)
    return success_response(True)


@extend_schema(tags=["llm"], summary="启用或禁用模型", request=LLMStatusSerializer, responses={200: None})
@api_view(["POST"])
def llm_set_status(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = LLMStatusSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    model_id = ser.validated_data["id"]
    tenant_id = ser.validated_data.get("tenant_id") or request_tenant_id(request)
    updated = LLMModel.objects.filter(id=model_id, tenant_id=tenant_id).update(status=ser.validated_data["status"])
    if not updated:
        return error_response("模型不存在。", code=404)
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="set_status", resource_type="llm", resource_id=model_id, detail={"status": ser.validated_data["status"]})
    return success_response(True)


@extend_schema(tags=["llm"], summary="模型配置测试", request=LLMIdSerializer, responses={200: None})
@api_view(["POST"])
def llm_test(request: Request) -> Response:
    ser = LLMIdSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    tenant_id = ser.validated_data.get("tenant_id") or request_tenant_id(request)
    try:
        model = LLMModel.objects.get(id=ser.validated_data["id"], tenant_id=tenant_id)
    except LLMModel.DoesNotExist:
        return error_response("模型不存在。", code=404)
    if model.status != "1":
        return success_response({
            "ok": False,
            "message": "模型已禁用，请先启用。",
            "model": _llm_to_dict(model),
        })
    model_ref = f"{model.llm_name}@{model.fid}"
    try:
        if model.model_type == "chat":
            resp = LLMService.chat(
                [ChatMessage(role="user", content="请只回复：ok")],
                model_name=model_ref,
                max_tokens=16,
            )
            return success_response({
                "ok": True,
                "message": "Chat 模型真实调用成功。",
                "latency": "已完成",
                "sample": resp.content,
                "tokens": resp.total_tokens,
                "model": _llm_to_dict(model),
            })
        if model.model_type == "embedding":
            vec = LLMService.embed(["模型连通性测试"], model_name=model_ref)
            return success_response({
                "ok": True,
                "message": "Embedding 模型真实调用成功。",
                "dimension": len(vec[0]) if vec else 0,
                "model": _llm_to_dict(model),
            })
        if model.model_type == "rerank":
            ranks = LLMService.rerank("苹果公司", ["苹果是一种水果", "Apple 是一家科技公司"], model_name=model_ref, topn=2)
            return success_response({
                "ok": True,
                "message": "Rerank 模型真实调用成功。",
                "sample": ranks,
                "model": _llm_to_dict(model),
            })
        if model.model_type == "vlm":
            return success_response({
                "ok": False,
                "message": "VLM 已用于多模态问答链路，但当前尚未封装独立 VLM 连通性测试适配器。",
                "model": _llm_to_dict(model),
            })
    except Exception as exc:
        logger.exception("模型真实连通性测试失败 model={}", model_ref)
        return success_response({
            "ok": False,
            "message": f"模型调用失败: {exc}",
            "model": _llm_to_dict(model),
        })
    return success_response({
        "ok": False,
        "message": f"暂不支持该模型类型测试: {model.model_type}",
        "model": _llm_to_dict(model),
    })


@extend_schema(tags=["llm"], summary="获取模型厂商列表", responses={200: None})
@api_view(["GET"])
def llm_factory_list(request: Request) -> Response:
    rows = LLMFactories.objects.all().order_by("name")
    return success_response([_factory_to_dict(row) for row in rows])


@extend_schema(tags=["llm"], summary="新增或更新模型厂商", request=LLMFactorySerializer, responses={200: None})
@api_view(["POST"])
def llm_factory_set(request: Request) -> Response:
    denied = require_role(request, "admin")
    if denied is not None:
        return denied
    ser = LLMFactorySerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    factory, _ = LLMFactories.objects.get_or_create(
        name=vd["name"],
        defaults={"id": get_uuid()},
    )
    old_key = reveal_secret(factory.api_key or "")
    if "api_base" in vd:
        factory.api_base = vd.get("api_base") or ""
    if "api_key" in vd and vd.get("api_key"):
        factory.api_key = protect_secret(vd["api_key"])
        APIKeyRotationLog.objects.create(
            id=get_uuid(),
            factory_name=factory.name,
            operator=request_user_id(request),
            action="rotate",
            old_key_masked=_mask_key(old_key),
            new_key_masked=_mask_key(vd["api_key"]),
        )
    factory.status = vd.get("status") or "1"
    factory.save()
    return success_response(_factory_to_dict(factory))


@extend_schema(tags=["llm"], summary="查询 API Key 轮换记录", responses={200: None})
@api_view(["GET"])
def llm_factory_rotation_list(request: Request) -> Response:
    name = request.GET.get("name") or ""
    qs = APIKeyRotationLog.objects.all().order_by("-create_date")[:100]
    if name:
        qs = APIKeyRotationLog.objects.filter(factory_name=name).order_by("-create_date")[:100]
    return success_response([
        {
            "id": row.id,
            "factory_name": row.factory_name,
            "operator": row.operator or "",
            "action": row.action,
            "old_key_masked": row.old_key_masked or "",
            "new_key_masked": row.new_key_masked or "",
            "create_date": row.create_date.strftime("%Y-%m-%d %H:%M:%S") if row.create_date else "",
        }
        for row in qs
    ])


def _llm_to_dict(model: LLMModel) -> dict[str, Any]:
    return {
        "id": model.id,
        "llm_name": model.llm_name,
        "model_type": model.model_type,
        "fid": model.fid,
        "tenant_id": getattr(model, "tenant_id", "default") or "default",
        "max_tokens": model.max_tokens,
        "status": model.status,
    }


def _factory_to_dict(factory: LLMFactories) -> dict[str, Any]:
    return {
        "id": factory.id,
        "name": factory.name,
        "api_base": factory.api_base or "",
        "api_key_masked": _mask_key(reveal_secret(factory.api_key or "")),
        "status": factory.status,
    }


def _mask_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "****"
    return value[:4] + "****" + value[-4:]
