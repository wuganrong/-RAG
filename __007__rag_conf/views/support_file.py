"""支持文件管理接口视图（文件类型映射 + 解析/切分方法）。"""

from __future__ import annotations

# 2. 第三方库
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.models import ChunkMethod, FileTypeMapping
from __001__rag.utils import error_response, format_datetime, get_uuid, success_response
from __007__rag_conf.utils import (
    filter_mappings,
    get_file_types_by_parser,
    get_mapping_by_id,
    get_method_obj,
    get_parsers_by_file_type,
    normalize_file_type,
    serialize_mapping,
    serialize_method,
)

from ..serializers.support_file import (
    MappingBatchBindSerializer,
    MappingChangeStatusSerializer,
    MappingDeleteSerializer,
    MappingFileTypesSerializer,
    MappingListSerializer,
    MappingParsersSerializer,
    MappingRenameSerializer,
    MappingRmByParserSerializer,
    MappingRmByTypeSerializer,
    MappingSetSerializer,
    MethodChangeStatusSerializer,
    MethodDeleteSerializer,
    MethodListSerializer,
    MethodSetSerializer,
)

_TAG = ["support-files"]


# ---------------------------------------------------------------------------
#  映射管理视图（FileTypeMapping）
# ---------------------------------------------------------------------------


@extend_schema(
    tags=_TAG,
    summary="映射列表",
    description="查询文件类型映射的扁平列表，支持关键词和状态过滤。",
    responses={200: None},
)
@api_view(["GET"])
def mapping_list(request: Request) -> Response:
    """GET /support-files/mapping/list — 映射列表。"""
    ser = MappingListSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    qs = filter_mappings(vd.get("keywords", ""), vd.get("status", ""))
    rows = list(qs.values("id", "file_type", "parser_id", "status", "create_date", "update_date"))
    items = [serialize_mapping(r) for r in rows]

    logger.info("查询映射列表，共 {} 条", len(items))
    return success_response(items)


@extend_schema(
    tags=_TAG,
    summary="映射树形结构",
    description="获取文件类型映射的树形结构，按解析方法分组。",
    responses={200: None},
)
@api_view(["GET"])
def mapping_tree(request: Request) -> Response:
    """GET /support-files/tree — 映射树。"""
    ser = MappingListSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    qs = filter_mappings(vd.get("keywords", ""), vd.get("status", ""))
    mappings = list(qs.values("id", "file_type", "parser_id", "status", "create_date", "update_date"))

    # 获取所有 parser 信息
    parser_ids = {m["parser_id"] for m in mappings}
    parsers = {
        p["method"]: p
        for p in ChunkMethod.objects.filter(
            method__in=parser_ids, method_type="parser"
        ).values("method", "display_name", "method_class")
    }

    # 按 parser 分组
    grouped: dict[str, list[dict]] = {}
    for m in mappings:
        key = m["parser_id"]
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(m)

    # 构建树
    tree = []
    for parser_id in sorted(grouped.keys(), key=lambda pid: parsers.get(pid, {}).get("display_name", pid)):
        parser = parsers.get(parser_id, {})
        children = sorted(
            grouped[parser_id],
            key=lambda x: normalize_file_type(x["file_type"]),
        )
        tree.append({
            "id": f"parser:{parser_id}",
            "nodeType": "parser",
            "label": parser.get("display_name") or parser_id,
            "parser_id": parser_id,
            "display_name": parser.get("display_name") or "",
            "method_class": parser.get("method_class") or "",
            "children": [
                {
                    "id": row["id"],
                    "nodeType": "mapping",
                    "label": f".{normalize_file_type(row['file_type'])}",
                    "file_type": normalize_file_type(row["file_type"]),
                    "parser_id": row["parser_id"],
                    "status": row.get("status") or "1",
                    "create_date": format_datetime(row.get("create_date")),
                    "update_date": format_datetime(row.get("update_date")),
                }
                for row in children
            ],
        })

    logger.info("查询映射树，共 {} 个解析方法，{} 条映射", len(tree), len(mappings))
    return success_response({"tree": tree, "total": len(mappings)})


@extend_schema(
    tags=_TAG,
    summary="新增或更新映射",
    description="不传 id 或 id 为空时新增；传入已存在 id 时更新。",
    request=MappingSetSerializer,
    responses={200: None},
)
@api_view(["POST"])
def mapping_set(request: Request) -> Response:
    """POST /support-files/mapping/set — 新增或更新映射。"""
    ser = MappingSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    file_type = normalize_file_type(vd["file_type"])
    parser_id = vd["parser_id"]
    status = vd.get("status") or "1"

    # 校验 parser 存在且为 parser 类型
    parser_exists = ChunkMethod.objects.filter(
        method=parser_id, method_type="parser"
    ).exists()
    if not parser_exists:
        return error_response("解析方法不存在。", code=400)

    mapping_id = (vd.get("id") or "").strip() or None

    try:
        if mapping_id:
            # 更新
            try:
                mapping = FileTypeMapping.objects.get(id=mapping_id)
            except FileTypeMapping.DoesNotExist:
                return error_response("映射记录不存在。", code=404)

            mapping.file_type = file_type
            mapping.parser_id = parser_id
            mapping.status = status
            mapping.save()
            logger.info("更新映射成功 id={}", mapping_id)
        else:
            # 新增
            mapping_id = get_uuid()
            FileTypeMapping.objects.create(
                id=mapping_id,
                file_type=file_type,
                parser_id=parser_id,
                status=status,
            )
            logger.info("新建映射成功 id={}", mapping_id)

        result = get_mapping_by_id(mapping_id)
        return success_response(result)

    except IntegrityError:
        logger.info("映射唯一性约束冲突 file_type={} parser_id={}", file_type, parser_id)
        return error_response("该文件类型已绑定相同解析方法。", code=400)
    except Exception as exc:  # noqa: BLE001
        logger.info("保存映射失败 error={}", exc)
        return error_response("保存映射失败。", code=500)


@extend_schema(
    tags=_TAG,
    summary="切换映射状态",
    description="启用或禁用文件类型映射。",
    request=MappingChangeStatusSerializer,
    responses={200: None},
)
@api_view(["POST"])
def mapping_change_status(request: Request) -> Response:
    """POST /support-files/mapping/change_status — 切换状态。"""
    ser = MappingChangeStatusSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    mapping_id = vd["id"]
    status = vd["status"]

    updated = FileTypeMapping.objects.filter(id=mapping_id).update(
        status=status, update_date=timezone.now()
    )
    if not updated:
        return error_response("映射记录不存在。", code=404)

    logger.info("切换映射状态成功 id={} status={}", mapping_id, status)
    result = get_mapping_by_id(mapping_id)
    return success_response(result)


@extend_schema(
    tags=_TAG,
    summary="删除映射",
    description="物理删除单条文件类型映射。",
    request=MappingDeleteSerializer,
    responses={200: None},
)
@api_view(["POST"])
def mapping_rm(request: Request) -> Response:
    """POST /support-files/mapping/rm — 删除映射。"""
    ser = MappingDeleteSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    mapping_id = ser.validated_data["id"]
    deleted, _ = FileTypeMapping.objects.filter(id=mapping_id).delete()
    if not deleted:
        return error_response("映射记录不存在。", code=404)

    logger.info("删除映射成功 id={}", mapping_id)
    return success_response({"id": mapping_id})


@extend_schema(
    tags=_TAG,
    summary="重命名文件类型",
    description="批量更新所有指定文件类型的记录为新名称，事务包裹。",
    request=MappingRenameSerializer,
    responses={200: None},
)
@api_view(["POST"])
def mapping_rename(request: Request) -> Response:
    """POST /support-files/mapping/rename — 重命名文件类型。"""
    ser = MappingRenameSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    old_type = normalize_file_type(vd["old_type"])
    new_type = normalize_file_type(vd["new_type"])

    if old_type == new_type:
        rows = list(
            FileTypeMapping.objects.filter(file_type=new_type).values(
                "id", "file_type", "parser_id", "status", "create_date", "update_date"
            )
        )
        return success_response([serialize_mapping(r) for r in rows])

    # 获取所有旧类型记录的 parser_id
    old_records = list(
        FileTypeMapping.objects.filter(file_type=old_type).values_list("parser_id", flat=True)
    )
    if not old_records:
        return error_response("未找到该文件类型的映射记录。", code=404)

    # 检查新类型 + 同 parser_id 是否有唯一冲突
    conflicts = FileTypeMapping.objects.filter(
        file_type=new_type, parser_id__in=old_records
    ).exists()
    if conflicts:
        return error_response("重命名后会与已有记录冲突。", code=400)

    now = timezone.now()
    try:
        with transaction.atomic():
            updated = FileTypeMapping.objects.filter(file_type=old_type).update(
                file_type=new_type, update_date=now
            )
    except IntegrityError:
        return error_response("重命名后会与已有记录冲突。", code=400)

    logger.info("重命名文件类型成功 {} -> {}，共 {} 条", old_type, new_type, updated)

    rows = list(
        FileTypeMapping.objects.filter(file_type=new_type).values(
            "id", "file_type", "parser_id", "status", "create_date", "update_date"
        )
    )
    return success_response([serialize_mapping(r) for r in rows])


@extend_schema(
    tags=_TAG,
    summary="批量绑定文件类型",
    description="将多个文件类型批量绑定到同一解析方法，已存在的跳过。",
    request=MappingBatchBindSerializer,
    responses={200: None},
)
@api_view(["POST"])
def mapping_batch_bind(request: Request) -> Response:
    """POST /support-files/mapping/batch_bind — 批量绑定。"""
    ser = MappingBatchBindSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    parser_id = vd["parser_id"]
    file_types = vd["file_types"]
    status = vd.get("status") or "1"

    # 校验 parser 存在
    parser_exists = ChunkMethod.objects.filter(
        method=parser_id, method_type="parser"
    ).exists()
    if not parser_exists:
        return error_response("解析方法不存在或未启用。", code=400)

    created = 0
    skipped = 0

    for ft in file_types:
        ft_normalized = normalize_file_type(ft)
        _, was_created = FileTypeMapping.objects.get_or_create(
            file_type=ft_normalized,
            parser_id=parser_id,
            defaults={
                "id": get_uuid(),
                "status": status,
            },
        )
        if was_created:
            created += 1
        else:
            skipped += 1

    logger.info("批量绑定完成 parser_id={} created={} skipped={}", parser_id, created, skipped)
    return success_response({"created": created, "skipped": skipped, "total": len(file_types)})


@extend_schema(
    tags=_TAG,
    summary="按解析方法清空映射",
    description="删除指定解析方法下的全部文件类型映射。",
    request=MappingRmByParserSerializer,
    responses={200: None},
)
@api_view(["POST"])
def mapping_rm_by_parser(request: Request) -> Response:
    """POST /support-files/mapping/rm_by_parser — 按 parser 清空。"""
    ser = MappingRmByParserSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    parser_id = ser.validated_data["parser_id"]
    deleted, _ = FileTypeMapping.objects.filter(parser_id=parser_id).delete()

    logger.info("按 parser 清空映射 parser_id={} removed={}", parser_id, deleted)
    return success_response({"removed": deleted})


@extend_schema(
    tags=_TAG,
    summary="按文件类型删除映射",
    description="删除指定文件类型下的全部映射记录。",
    request=MappingRmByTypeSerializer,
    responses={200: None},
)
@api_view(["POST"])
def mapping_rm_by_type(request: Request) -> Response:
    """POST /support-files/mapping/rm_by_type — 按文件类型删除。"""
    ser = MappingRmByTypeSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    file_type = normalize_file_type(ser.validated_data["file_type"])
    deleted, _ = FileTypeMapping.objects.filter(file_type=file_type).delete()

    logger.info("按文件类型删除映射 file_type={} removed={}", file_type, deleted)
    return success_response({"removed": deleted})


# ---------------------------------------------------------------------------
#  方法管理视图（ChunkMethod）
# ---------------------------------------------------------------------------


@extend_schema(
    tags=_TAG,
    summary="方法库列表",
    description="查询解析/切分方法库列表，支持按方法类型和关键词过滤。",
    responses={200: None},
)
@api_view(["GET"])
def method_list(request: Request) -> Response:
    """GET /support-files/method/list — 方法库列表。"""
    ser = MethodListSerializer(data=request.query_params)
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
            "status", "create_date", "update_date"
        )
    )
    items = [serialize_method(r) for r in rows]

    logger.info("查询方法库列表，共 {} 条", len(items))
    return success_response(items)


@extend_schema(
    tags=_TAG,
    summary="新增或更新方法",
    description="不传 original_method 时新增；传入 original_method 时更新。方法标识变更时级联更新映射。",
    request=MethodSetSerializer,
    responses={200: None},
)
@api_view(["POST"])
def method_set(request: Request) -> Response:
    """POST /support-files/method/set — 新增或更新方法。"""
    ser = MethodSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    method = vd["method"]
    method_type = vd["method_type"]
    display_name = vd["display_name"]
    method_class = vd["method_class"]
    status = vd.get("status") or "1"
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
            )
            logger.info("新建方法成功 method={}", method)

        result = get_method_obj(method, method_type)
        return success_response(result)

    except Exception as exc:  # noqa: BLE001
        logger.info("保存方法失败 error={}", exc)
        return error_response("保存方法失败。", code=500)


@extend_schema(
    tags=_TAG,
    summary="删除方法",
    description="物理删除方法，被映射引用时拒绝删除。",
    request=MethodDeleteSerializer,
    responses={200: None},
)
@api_view(["POST"])
def method_rm(request: Request) -> Response:
    """POST /support-files/method/rm — 删除方法。"""
    ser = MethodDeleteSerializer(data=request.data)
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
    request=MethodChangeStatusSerializer,
    responses={200: None},
)
@api_view(["POST"])
def method_change_status(request: Request) -> Response:
    """POST /support-files/method/change_status — 切换状态。"""
    ser = MethodChangeStatusSerializer(data=request.data)
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
    result = get_method_obj(method, method_type)
    return success_response(result)


# ---------------------------------------------------------------------------
#  快捷查询视图
# ---------------------------------------------------------------------------


@extend_schema(
    tags=_TAG,
    summary="查询解析方法支持的文件类型",
    description="根据解析方法标识查询该解析方法支持的启用状态文件类型列表。",
    parameters=[
        OpenApiParameter("parser_id", OpenApiTypes.STR, required=True, description="解析方法标识"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def mapping_file_types(request: Request) -> Response:
    """GET /support-files/mapping/file_types — 查询允许的文件类型。"""
    ser = MappingFileTypesSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    parser_id = ser.validated_data["parser_id"]
    file_types = get_file_types_by_parser(parser_id)

    logger.info("查询文件类型列表 parser_id={} count={}", parser_id, len(file_types))
    return success_response(file_types)


@extend_schema(
    tags=_TAG,
    summary="查询文件类型可用的解析方法",
    description="根据文件类型查询该类型可用的启用状态解析方法列表（含显示名称）。",
    parameters=[
        OpenApiParameter("file_type", OpenApiTypes.STR, required=True, description="文件类型"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def mapping_parsers(request: Request) -> Response:
    """GET /support-files/mapping/parsers — 查询可用的解析方法。"""
    ser = MappingParsersSerializer(data=request.query_params)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    file_type = normalize_file_type(ser.validated_data["file_type"])
    parsers = get_parsers_by_file_type(file_type)

    logger.info("查询解析方法列表 file_type={} count={}", file_type, len(parsers))
    return success_response(parsers)
