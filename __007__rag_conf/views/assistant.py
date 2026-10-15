"""助理配置接口视图。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.core.paginator import Paginator
from django.db import IntegrityError
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.chunk.utils.pdf_llm import clear_gb_chunk_config_cache, is_gb_chunk_related_key
from __001__rag.models import AssistantConfig, AssistantType, PromptConfig
from __001__rag.utils import error_response, get_uuid, success_response
from __007__rag_conf.utils import build_assistant_config_response, get_valid_kb_names, prompt_config_to_dict

from ..serializers.assistant import (
    AssistantConfigDetailSerializer,
    AssistantConfigListSerializer,
    AssistantConfigSetSerializer,
)

_ASSISTANT_CONFIG_TAG = ["assistant_config"]
_SET_FIELDS = {
    "assistant_key",
    "assistant_type",
    "assistant_name",
    "prompt_config_key",
    "model_name",
    "llm_setting",
    "max_tokens",
    "extra_params",
    "retrieval_method",
    "similarity_threshold",
    "vector_similarity_weight",
    "top_n",
    "rerank_id",
    "kb_ids",
    "memory_rounds",
    "top_k",
    "prologue",
    "status",
}


def _get_assistant_config_queryset(keywords: str):
    """按助理名称构建查询集，仅取列表所需字段。"""
    qs = AssistantConfig.objects.values(
        "id", "assistant_name", "assistant_key", "assistant_type", "status"
    ).order_by("-create_date")
    if keywords:
        qs = qs.filter(assistant_name__icontains=keywords)
    return qs


def _validate_assistant_key_unique(assistant_key: str, assistant_id: str | None = None) -> Response | None:
    """校验助理唯一键唯一性。"""
    qs = AssistantConfig.objects.filter(assistant_key=assistant_key)
    if assistant_id:
        qs = qs.exclude(id=assistant_id)
    if qs.exists():
        return error_response("助理唯一键 assistant_key 已存在。", code=400)
    return None


def _validate_kb_ids(kb_ids: list[str]) -> Response | None:
    """校验知识库 ID 是否均存在且启用。"""
    valid_kb_ids, _ = get_valid_kb_names(kb_ids)
    invalid_kb_ids = set(kb_ids) - set(valid_kb_ids)
    if invalid_kb_ids:
        return error_response(f"知识库不存在或未启用: {', '.join(invalid_kb_ids)}", code=400)
    return None


def _build_update_data(validated_data: dict[str, Any]) -> dict[str, Any]:
    """从校验后的入参中提取可写字段。"""
    return {field: validated_data[field] for field in _SET_FIELDS if field in validated_data}


@extend_schema(
    tags=_ASSISTANT_CONFIG_TAG,
    summary="分页/条件查询助理配置列表",
    description="按助理名称关键词分页查询助理配置，列表项返回 id、assistant_name、assistant_key、assistant_type、status。",
    parameters=[
        OpenApiParameter("page", OpenApiTypes.INT, description="页码，从 1 开始，默认 1"),
        OpenApiParameter("page_size", OpenApiTypes.INT, description="每页条数，默认 10"),
        OpenApiParameter("keywords", OpenApiTypes.STR, description="关键词，仅按助理名称 assistant_name 过滤"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def assistant_config_list(request: Request) -> Response:
    """GET /assistant_config/list — 分页/条件查询助理配置列表。"""
    ser = AssistantConfigListSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    qs = _get_assistant_config_queryset(vd.get("keywords", ""))
    paginator = Paginator(qs, vd["page_size"])
    page_obj = paginator.get_page(vd["page"])

    return success_response({"assistants": list(page_obj), "total": paginator.count})


@extend_schema(
    tags=_ASSISTANT_CONFIG_TAG,
    summary="获取助理配置详情",
    description="通过助理配置 ID 获取详情，返回助理设置、提示引擎、模型设置三段数据。",
    parameters=[
        OpenApiParameter("id", OpenApiTypes.STR, required=True, description="助理配置 ID"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def assistant_config_detail(request: Request) -> Response:
    """GET /assistant_config/detail — 获取助理配置详情。"""
    ser = AssistantConfigDetailSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    assistant_id: str = ser.validated_data["id"]
    try:
        config = AssistantConfig.objects.get(id=assistant_id)
    except AssistantConfig.DoesNotExist:
        return error_response("助理配置不存在。", code=404)

    return success_response(build_assistant_config_response(config))


@extend_schema(
    tags=_ASSISTANT_CONFIG_TAG,
    summary="新增或更新助理配置",
    description="不传 id 时新增助理配置，传入已存在 id 时更新对应配置。",
    request=AssistantConfigSetSerializer,
    responses={200: None},
)
@api_view(["POST"])
def assistant_config_set(request: Request) -> Response:
    """POST /assistant_config/set — 新增或更新助理配置。"""
    ser = AssistantConfigSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    raw_id = vd.get("id")
    assistant_id = raw_id.strip() if isinstance(raw_id, str) and raw_id.strip() else None
    update_data = _build_update_data(vd)

    # 校验并缓存 prompt_config，避免 build_assistant_config_response 重复查库
    fetched_prompt_config: PromptConfig | None = None
    if "prompt_config_key" in update_data:
        try:
            fetched_prompt_config = PromptConfig.objects.get(
                config_key=update_data["prompt_config_key"], status="1"
            )
        except PromptConfig.DoesNotExist:
            return error_response("提示词模板不存在或未启用。", code=400)

    if "assistant_key" in update_data:
        unique_error = _validate_assistant_key_unique(update_data["assistant_key"], assistant_id)
        if unique_error is not None:
            return unique_error

    if "kb_ids" in update_data:
        kb_error = _validate_kb_ids(update_data["kb_ids"])
        if kb_error is not None:
            return kb_error

    try:
        if assistant_id:
            config = AssistantConfig.objects.get(id=assistant_id)
            for field, value in update_data.items():
                setattr(config, field, value)
            config.save()
        else:
            if not update_data.get("assistant_key"):
                return error_response("assistant_key 为必填字段。", code=400)
            if not update_data.get("assistant_type"):
                return error_response("assistant_type 为必填字段。", code=400)
            if not update_data.get("prompt_config_key"):
                return error_response("prompt_config_key 为必填字段。", code=400)

            config = AssistantConfig.objects.create(
                id=get_uuid(),
                **update_data,
            )
    except AssistantConfig.DoesNotExist:
        return error_response("助理配置不存在。", code=404)
    except IntegrityError:
        logger.info("保存助理配置唯一性约束失败 assistant_id={}", assistant_id)
        return error_response("助理唯一键 assistant_key 已存在。", code=400)
    except Exception as exc:  # noqa: BLE001
        logger.info("保存助理配置失败 error={}", exc)
        return error_response("保存助理配置失败。", code=500)

    prompt_config_map = (
        {config.prompt_config_key: prompt_config_to_dict(fetched_prompt_config)}
        if fetched_prompt_config is not None
        else None
    )
    if is_gb_chunk_related_key(config.assistant_key) or is_gb_chunk_related_key(config.prompt_config_key):
        clear_gb_chunk_config_cache()
    return success_response(build_assistant_config_response(config, prompt_config_map=prompt_config_map))


@extend_schema(
    tags=_ASSISTANT_CONFIG_TAG,
    summary="获取助理类型枚举",
    description="从 rag.models.AssistantType 枚举动态返回可选类型列表。",
    responses={200: None},
)
@api_view(["GET"])
def assistant_type_options(request: Request) -> Response:
    """GET /assistant/type_options — 从模型枚举动态获取助理类型列表。"""
    options = [{"value": value, "label": label} for value, label in AssistantType.choices]
    return success_response(options)
