"""文档方法库（document_method_config）增删改查接口视图。"""

from __future__ import annotations

# 2. 第三方库
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.models import ChunkMethod, FileTypeMapping
from __001__rag.utils import error_response, format_datetime, success_response

from ..serializers.document_method import (
    DocumentMethodChangeStatusSerializer,
    DocumentMethodDeleteSerializer,
    DocumentMethodListSerializer,
    DocumentMethodSetSerializer,
)

_TAG = ["document-method"]


def _serialize_method(row: dict) -> dict:
    """将 ORM values 行转为可 JSON 序列化的方法字典（含 config_schema）。"""
    return {
        "method": row["method"],
        "method_type": row["method_type"],
        "display_name": row.get("display_name") or "",
        "method_class": row.get("method_class") or "",
        "status": row.get("status") or "1",
        "config_schema": row.get("config_schema") or [],
        "create_date": format_datetime(row.get("create_date")),
        "update_date": format_datetime(row.get("update_date")),
    }


def _get_method_detail(method: str, method_type: str = "") -> dict | None:
    """获取单条方法记录。"""
    qs = ChunkMethod.objects.filter(method=method)
    if method_type:
        qs = qs.filter(method_type=method_type)
    rows = list(
        qs.values(
            "method", "method_type", "display_name", "method_class",
            "status", "config_schema", "create_date", "update_date",
        )
    )
    return _serialize_method(rows[0]) if rows else None


@extend_schema(
    tags=_TAG,
    summary="方法库列表",
    description="查询解析/切分方法库列表，支持按方法类型和关键词过滤，含 config_schema。",
    responses={200: None},
)
@api_view(["GET"])
def document_method_list(request: Request) -> Response:
    """GET /document-method/list — 方法库列表。"""
    ser = DocumentMethodListSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    qs = ChunkMethod.objects.all()

    method_type = vd.get("method_type", "")
    if method_type:
        qs = qs.filter(method_type=method_type)

    keywords = vd.get("keywords", "")
    if keywords:
        qs = qs.filter(
            Q(method__icontains=keywords)
            | Q(display_name__icontains=keywords)
            | Q(method_class__icontains=keywords)
        )

    rows = list(
        qs.order_by("method_type", "method").values(
            "method", "method_type", "display_name", "method_class",
            "status", "config_schema", "create_date", "update_date",
        )
    )
    items = [_serialize_method(r) for r in rows]

    logger.info("查询方法库列表，共 {} 条", len(items))
    return success_response(items)


@extend_schema(
    tags=_TAG,
    summary="方法详情",
    description="根据方法标识和方法类型查询单条方法详情（含 config_schema）。",
    parameters=[
        OpenApiParameter("method", OpenApiTypes.STR, required=True, description="方法标识"),
        OpenApiParameter("method_type", OpenApiTypes.STR, required=False, description="方法类型：parser / chunker"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def document_method_detail(request: Request) -> Response:
    """GET /document-method/detail — 方法详情。"""
    method = str(request.GET.get("method") or "").strip()
    if not method:
        return error_response("method 参数不能为空。")

    method_type = str(request.GET.get("method_type") or "").strip()
    result = _get_method_detail(method, method_type)
    if not result:
        return error_response("方法不存在。", code=404)

    return success_response(result)


@extend_schema(
    tags=_TAG,
    summary="新增或更新方法",
    description="不传 original_method 时新增；传入 original_method 时更新。方法标识变更时级联更新映射。",
    request=DocumentMethodSetSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_method_set(request: Request) -> Response:
    """POST /document-method/set — 新增或更新方法。"""
    ser = DocumentMethodSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    method = vd["method"]
    method_type = vd["method_type"]
    display_name = vd["display_name"]
    method_class = vd["method_class"]
    status = vd.get("status") or "1"
    config_schema = vd.get("config_schema", [])
    original_method = (vd.get("original_method") or "").strip() or None

    try:
        if original_method:
            # 更新
            qs = ChunkMethod.objects.filter(method=original_method, method_type=method_type)
            if not qs.exists():
                return error_response("方法不存在。", code=404)

            # 如果 method 值变更，检查新值是否冲突
            if method != original_method:
                conflict = ChunkMethod.objects.filter(
                    method=method, method_type=method_type
                ).exclude(method=original_method).exists()
                if conflict:
                    return error_response("方法标识已存在。", code=400)

            obj = qs.first()
            old_method = obj.method
            obj.method = method
            obj.display_name = display_name
            obj.method_class = method_class
            obj.status = status
            obj.config_schema = config_schema
            obj.save()

            # 如果是 parser 且 method 值变更，级联更新映射
            if method_type == "parser" and old_method != method:
                FileTypeMapping.objects.filter(parser_id=old_method).update(
                    parser_id=method, update_date=timezone.now()
                )
                logger.info("级联更新映射 parser_id {} -> {}", old_method, method)

            logger.info("更新方法成功 method={}", method)
        else:
            # 新增：检查是否已存在
            conflict = ChunkMethod.objects.filter(
                method=method, method_type=method_type
            ).exists()
            if conflict:
                return error_response("方法标识已存在。", code=400)

            ChunkMethod.objects.create(
                method=method,
                method_type=method_type,
                display_name=display_name,
                method_class=method_class,
                status=status,
                config_schema=config_schema,
            )
            logger.info("新建方法成功 method={}", method)

        result = _get_method_detail(method, method_type)
        return success_response(result)

    except Exception as exc:  # noqa: BLE001
        logger.exception("保存方法失败 error={}", exc)
        return error_response("保存方法失败。", code=500)


@extend_schema(
    tags=_TAG,
    summary="删除方法",
    description="物理删除方法，被映射引用时拒绝删除。",
    request=DocumentMethodDeleteSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_method_rm(request: Request) -> Response:
    """POST /document-method/rm — 删除方法。"""
    ser = DocumentMethodDeleteSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    method = vd["method"]
    method_type = vd.get("method_type", "")

    # 检查是否被映射引用（仅 parser 类型需要检查）
    if FileTypeMapping.objects.filter(parser_id=method).exists():
        return error_response("该方法已被文件类型映射引用，无法删除。", code=400)

    qs = ChunkMethod.objects.filter(method=method)
    if method_type:
        qs = qs.filter(method_type=method_type)

    deleted, _ = qs.delete()
    if not deleted:
        return error_response("方法不存在。", code=404)

    logger.info("删除方法成功 method={}", method)
    return success_response({"method": method})


@extend_schema(
    tags=_TAG,
    summary="切换方法状态",
    description="启用或禁用解析/切分方法。",
    request=DocumentMethodChangeStatusSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_method_change_status(request: Request) -> Response:
    """POST /document-method/change_status — 切换状态。"""
    ser = DocumentMethodChangeStatusSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    method = vd["method"]
    status = vd["status"]
    method_type = vd.get("method_type", "")

    qs = ChunkMethod.objects.filter(method=method)
    if method_type:
        qs = qs.filter(method_type=method_type)

    updated = qs.update(status=status, update_date=timezone.now())
    if not updated:
        return error_response("方法不存在。", code=404)

    logger.info("切换方法状态成功 method={} status={}", method, status)
    result = _get_method_detail(method, method_type)
    return success_response(result)
