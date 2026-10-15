"""提示词配置接口视图。"""

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
from __001__rag.models import PromptConfig
from __001__rag.utils import error_response, format_datetime, success_response
from __007__rag_conf.utils import get_prompt_detail, get_prompt_detail_by_id, list_prompt_configs

from ..serializers.prompt import (
    PromptDeleteSerializer,
    PromptDetailSerializer,
    PromptListPageSerializer,
    PromptSetSerializer,
)

_PROMPT_TAG = ["prompt"]

_PROMPT_SET_FIELDS = frozenset(
    {"config_key", "section_name", "system_prompt", "user_prompt_template", "status"}
)


def _serialize_list_row(row: dict[str, Any]) -> dict[str, Any]:
    """将 ORM values 行转为可 JSON 序列化的字典。"""
    cd = row.get("create_date")
    return {
        "id": row["id"],
        "config_key": row["config_key"],
        "section_name": row["section_name"] or "",
        "status": row["status"] or "1",
        "create_date": format_datetime(cd),
    }


@extend_schema(
    tags=_PROMPT_TAG,
    summary="提示词列表",
    description=(
        "查询所有启用状态（status=1）的提示词配置，按创建时间升序返回选项列表，"
        "字段 label 为提示词名称（section_name），value 为配置唯一键（config_key）。"
    ),
    responses={200: None},
)
@api_view(["GET"])
def prompt_list(request: Request) -> Response:
    """GET /prompt/list — 提示词选项列表。"""
    items = list_prompt_configs()
    logger.info("查询提示词列表成功，共 {} 条", len(items))
    return success_response(items)


@extend_schema(
    tags=_PROMPT_TAG,
    summary="提示词详情",
    description=(
        "通过提示词唯一键 config_key 查询详情（仅启用记录），或通过 id 查询（管理端，不限状态）。"
        "config_key 与 id 二选一。"
    ),
    parameters=[
        OpenApiParameter(
            "config_key",
            OpenApiTypes.STR,
            required=False,
            description="提示词模板唯一键，如 chat",
        ),
        OpenApiParameter(
            "id",
            OpenApiTypes.INT,
            required=False,
            description="提示词配置主键（管理端）",
        ),
    ],
    responses={200: None},
)
@api_view(["GET"])
def prompt_detail(request: Request) -> Response:
    """GET /prompt/detail — 提示词详情。"""
    ser = PromptDetailSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    detail_id = vd.get("id")
    if detail_id:
        detail = get_prompt_detail_by_id(detail_id)
        if detail is None:
            return error_response("提示词模板不存在。", code=404)
        logger.info("查询提示词详情成功 id={}", detail_id)
        return success_response(detail)

    config_key: str = vd["config_key"]  # type: ignore[assignment]
    detail = get_prompt_detail(config_key)
    if detail is None:
        return error_response("提示词模板不存在或未启用。", code=404)

    logger.info("查询提示词详情成功 config_key={}", config_key)
    return success_response(detail)


@extend_schema(
    tags=_PROMPT_TAG,
    summary="分页查询提示词（管理）",
    description="按提示词名称关键词分页查询全部提示词配置（含禁用）。",
    parameters=[
        OpenApiParameter("page", OpenApiTypes.INT, description="页码，从 1 开始"),
        OpenApiParameter("page_size", OpenApiTypes.INT, description="每页条数"),
        OpenApiParameter("keywords", OpenApiTypes.STR, description="按 section_name 模糊匹配"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def prompt_list_page(request: Request) -> Response:
    """GET /prompt/list_page — 分页列表。"""
    ser = PromptListPageSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    keywords = vd.get("keywords", "") or ""
    qs = (
        PromptConfig.objects.values("id", "config_key", "section_name", "status", "create_date")
        .order_by("-create_date", "-id")
    )
    if keywords:
        qs = qs.filter(section_name__icontains=keywords)

    paginator = Paginator(qs, vd["page_size"])
    page_obj = paginator.get_page(vd["page"])
    rows = [_serialize_list_row(r) for r in page_obj]

    return success_response({"prompts": rows, "total": paginator.count})


def _build_prompt_update_data(validated_data: dict[str, Any]) -> dict[str, Any]:
    """从校验后的入参中提取可写字段。"""
    result: dict[str, Any] = {}
    for field in _PROMPT_SET_FIELDS:
        if field not in validated_data:
            continue
        val = validated_data[field]
        if field == "status":
            sv = (val or "").strip() if isinstance(val, str) else ""
            if sv not in {"0", "1"}:
                continue
            val = sv
        result[field] = val
    return result


@extend_schema(
    tags=_PROMPT_TAG,
    summary="新增或更新提示词（管理）",
    description="不传 id 或 id 为空时新增；传入已存在 id 时更新。新建时 config_key、section_name 必填。",
    request=PromptSetSerializer,
    responses={200: None},
)
@api_view(["POST"])
def prompt_set(request: Request) -> Response:
    """POST /prompt/set — 新增或更新。"""
    ser = PromptSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    prompt_id = vd.get("id")
    update_data = _build_prompt_update_data(vd)

    try:
        if prompt_id is not None:
            try:
                config = PromptConfig.objects.get(id=prompt_id)
            except PromptConfig.DoesNotExist:
                return error_response("提示词配置不存在。", code=404)

            if "config_key" in update_data and update_data["config_key"] != config.config_key:
                if PromptConfig.objects.filter(config_key=update_data["config_key"]).exclude(
                    id=prompt_id
                ).exists():
                    return error_response("模板唯一键 config_key 已存在。", code=400)

            for field, value in update_data.items():
                setattr(config, field, value)
            config.save()
            logger.info("更新提示词成功 id={}", prompt_id)
            detail = get_prompt_detail_by_id(prompt_id)
            if is_gb_chunk_related_key(config.config_key):
                clear_gb_chunk_config_cache()
            return success_response(detail)

        # 新建
        ck = (vd.get("config_key") or "").strip()
        if not ck:
            return error_response("config_key 为必填字段。", code=400)
        name = (vd.get("section_name") or "").strip()
        if not name:
            return error_response("提示词名称 section_name 为必填字段。", code=400)

        config = PromptConfig.objects.create(
            config_key=ck,
            section_name=name,
            system_prompt=(vd.get("system_prompt") or "") or "",
            user_prompt_template=(vd.get("user_prompt_template") or "") or "",
            status=(vd.get("status") or "1").strip() or "1",
        )
        logger.info("新建提示词成功 id={} config_key={}", config.id, ck)
        detail = get_prompt_detail_by_id(config.id)
        if is_gb_chunk_related_key(ck):
            clear_gb_chunk_config_cache()
        return success_response(detail)
    except IntegrityError:
        logger.info("保存提示词唯一性约束失败")
        return error_response("模板唯一键 config_key 已存在。", code=400)
    except Exception as exc:  # noqa: BLE001
        logger.info("保存提示词失败 error={}", exc)
        return error_response("保存提示词失败。", code=500)


@extend_schema(
    tags=_PROMPT_TAG,
    summary="删除提示词（管理）",
    description="按主键物理删除提示词配置。",
    request=PromptDeleteSerializer,
    responses={200: None},
)
@api_view(["POST"])
def prompt_delete(request: Request) -> Response:
    """POST /prompt/delete — 删除。"""
    ser = PromptDeleteSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    prompt_id = ser.validated_data["id"]
    prompt = PromptConfig.objects.filter(id=prompt_id).only("config_key").first()
    deleted, _ = PromptConfig.objects.filter(id=prompt_id).delete()
    if not deleted:
        return error_response("提示词配置不存在。", code=404)

    if prompt and is_gb_chunk_related_key(prompt.config_key):
        clear_gb_chunk_config_cache()

    logger.info("删除提示词成功 id={}", prompt_id)
    return success_response({"id": prompt_id})
