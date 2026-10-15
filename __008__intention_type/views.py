"""意图类型（Intention Type）接口视图。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.models import IntentionType
from __001__rag.utils import error_response, format_datetime, success_response
from __008__intention_type.utils import build_intention_tree, calc_depth_and_path

from .serializers import (
    IntentionTypeDetailSerializer,
    IntentionTypeListSerializer,
    IntentionTypeRmSerializer,
    IntentionTypeSetSerializer,
)

_INTENTION_TYPE_TAG = ["intention_type"]


def _intention_node_to_dict(it: IntentionType) -> dict[str, Any]:
    """将 IntentionType 实例转为包含全字段的 API 响应字典。"""
    return {
        "id": it.id,
        "label": it.intention or "",
        "intention": it.intention or "",
        "intention_description": it.intention_description or "",
        "parent_id": it.parent_id,
        "path": it.path or "",
        "depth": it.depth,
        "intent_type": it.intent_type,
        "status": it.status,
        "is_default": it.is_default,
        "is_fallback": it.is_fallback,
        "child_match_policy": it.child_match_policy,
        "inherit_slots": it.inherit_slots,
        "kb_ids": it.kb_ids if isinstance(it.kb_ids, list) else [],
        "sys_prompt": it.sys_prompt or "",
        "create_date": format_datetime(it.create_date),
        "update_date": format_datetime(it.update_date),
    }


@extend_schema(
    tags=_INTENTION_TYPE_TAG,
    summary="获取意图类型树形列表",
    description=(
        "返回符合 Element UI Tree 组件格式的完整意图树。"
        "每个节点含 label（意图名称）、children（子节点列表）及全部字段信息。"
        "可通过 status 参数过滤节点状态，不传则返回全部节点。"
    ),
    parameters=[
        OpenApiParameter(
            "status",
            OpenApiTypes.STR,
            description="状态过滤：1=有效，0=无效，不传则返回全部",
        ),
    ],
    responses={200: None},
)
@api_view(["GET"])
def intention_type_list(request: Request) -> Response:
    """GET /v1/intention_type/list — 返回 Element UI Tree 格式意图树。"""
    ser = IntentionTypeListSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    status_filter: str = ser.validated_data.get("status", "")
    logger.info("查询意图类型树 status_filter={}", status_filter or "全部")

    tree = build_intention_tree(status=status_filter)
    return success_response(tree)


@extend_schema(
    tags=_INTENTION_TYPE_TAG,
    summary="获取意图类型详情",
    description="通过 id 查询单个意图类型的完整字段信息（不含 children 嵌套）。",
    parameters=[
        OpenApiParameter(
            "id",
            OpenApiTypes.STR,
            required=True,
            description="意图类型 ID",
        ),
    ],
    responses={200: None},
)
@api_view(["GET"])
def intention_type_detail(request: Request) -> Response:
    """GET /v1/intention_type/detail?id=xxx — 获取单个意图类型详情。"""
    ser = IntentionTypeDetailSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    intention_id: int = ser.validated_data["id"]
    logger.info("查询意图类型详情 id={}", intention_id)

    try:
        it = IntentionType.objects.get(id=intention_id)
    except IntentionType.DoesNotExist:
        logger.info("意图类型不存在 id={}", intention_id)
        return error_response("意图类型不存在", code=404)

    return success_response(_intention_node_to_dict(it))


@extend_schema(
    tags=_INTENTION_TYPE_TAG,
    summary="新增或更新意图类型",
    description=(
        "不传 id 时新建意图类型；传入已存在 id 时更新对应记录。\n\n"
        "新建时 depth 和 path 由后端根据 parent_id 自动计算，无需前端传入。\n"
        "更新时若 parent_id 发生变化则重新计算 depth 和 path。"
    ),
    request=IntentionTypeSetSerializer,
    responses={200: None},
)
@api_view(["POST"])
def intention_type_set(request: Request) -> Response:
    """POST /v1/intention_type/set — 新增或更新意图类型。"""
    ser = IntentionTypeSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    intention_id: int | None = vd.get("id")
    intention: str = vd["intention"]
    intention_description: str = vd.get("intention_description") or ""
    parent_id: int | None = vd.get("parent_id")
    intent_type: str = vd.get("intent_type", "T")
    status_val: str = vd.get("status", "1")
    is_default: str = vd.get("is_default", "0")
    kb_ids: list = vd.get("kb_ids") or []
    sys_prompt: str = vd.get("sys_prompt") or ""
    inherit_slots: bool = vd.get("inherit_slots", False)
    child_match_policy: str = vd.get("child_match_policy", "L")
    is_fallback: bool = vd.get("is_fallback", False)

    if intention_id:
        # 更新逻辑
        logger.info("更新意图类型 id={}", intention_id)
        try:
            it = IntentionType.objects.get(id=intention_id)
        except IntentionType.DoesNotExist:
            logger.info("意图类型不存在 id={}", intention_id)
            return error_response("意图类型不存在", code=404)

        parent_changed = it.parent_id != parent_id
        it.intention = intention
        it.intention_description = intention_description
        it.parent_id = parent_id
        it.intent_type = intent_type
        it.status = status_val
        it.is_default = is_default
        it.kb_ids = kb_ids
        it.sys_prompt = sys_prompt
        it.inherit_slots = inherit_slots
        it.child_match_policy = child_match_policy
        it.is_fallback = is_fallback

        if parent_changed or not it.path:
            depth, path = calc_depth_and_path(parent_id, intention)
            it.depth = depth
            it.path = path

        it.save()
        logger.info("意图类型更新成功 id={} intention={}", intention_id, intention)
    else:
        # 新建逻辑
        depth, path = calc_depth_and_path(parent_id, intention)
        it = IntentionType.objects.create(
            intention=intention,
            intention_description=intention_description,
            parent_id=parent_id,
            depth=depth,
            path=path,
            intent_type=intent_type,
            status=status_val,
            is_default=is_default,
            kb_ids=kb_ids,
            sys_prompt=sys_prompt,
            inherit_slots=inherit_slots,
            child_match_policy=child_match_policy,
            is_fallback=is_fallback,
        )
        logger.info("意图类型新建成功 id={} intention={} parent_id={}", it.id, intention, parent_id)

    return success_response(_intention_node_to_dict(it))


def _collect_all_descendant_ids(root_id: int) -> list[int]:
    """BFS 收集某节点（含自身）的所有后代 ID 列表，用于级联删除。"""
    all_ids: list[int] = []
    queue: list[int] = [root_id]
    while queue:
        current_ids = queue[:]
        queue = []
        all_ids.extend(current_ids)
        children_ids = list(
            IntentionType.objects.filter(parent_id__in=current_ids).values_list("id", flat=True)
        )
        queue.extend(children_ids)
    return all_ids


@extend_schema(
    tags=_INTENTION_TYPE_TAG,
    summary="删除意图类型（支持级联）",
    description=(
        "通过 id 删除指定意图类型及其所有子孙节点（级联删除）。\n\n"
        "返回实际删除的节点数量。"
    ),
    request=IntentionTypeRmSerializer,
    responses={200: None},
)
@api_view(["POST"])
def intention_type_rm(request: Request) -> Response:
    """POST /v1/intention_type/rm — 删除意图类型（级联删除所有子孙节点）。"""
    ser = IntentionTypeRmSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    intention_id: int = ser.validated_data["id"]
    logger.info("删除意图类型（级联）id={}", intention_id)

    try:
        it = IntentionType.objects.get(id=intention_id)
    except IntentionType.DoesNotExist:
        logger.info("意图类型不存在 id={}", intention_id)
        return error_response("意图类型不存在", code=404)

    intention_name = it.intention
    all_ids = _collect_all_descendant_ids(intention_id)
    deleted_count, _ = IntentionType.objects.filter(id__in=all_ids).delete()
    logger.info(
        "意图类型级联删除成功 id={} intention={} 共删除节点数={}",
        intention_id, intention_name, deleted_count,
    )

    return success_response({"deleted_count": deleted_count}, msg="删除成功")
