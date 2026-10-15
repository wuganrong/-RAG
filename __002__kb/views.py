"""知识库（KB）接口视图。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Sum
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.models import Document, File, File2Document, Knowledgebase, KnowledgebaseAcl, Task
from __001__rag.ops import can_access_kb, request_tenant_id, request_user_id, require_kb_access, require_role, write_audit
from __001__rag.search import es_service
from __001__rag.utils import check_duplicate_name, error_response, format_datetime, get_uuid, success_response

from .serializers import (
    KbCreateSerializer,
    KbDetailSerializer,
    KbListSerializer,
    KbRmSerializer,
    KbTagsSerializer,
    KbUpdateSerializer,
    KbAclListSerializer,
    KbAclRmSerializer,
    KbAclSaveSerializer,
)

_KB_TAG = ["kb"]
_DEFAULT_PARSER_ID = "naive"
_KB_SOURCE_TYPE = "knowledgebase"


def _doc_stats_map(kb_ids: list[str]) -> dict[str, dict[str, int]]:
    """按知识库汇总文档数 / 切片数 / 页图数，避免首页只读到过期的 kb.page_num。"""
    if not kb_ids:
        return {}
    rows = (
        Document.objects.filter(kb_id__in=kb_ids)
        .values("kb_id")
        .annotate(docs=Count("id"), chunks=Sum("chunk_num"), pages=Sum("page_num"))
    )
    return {
        row["kb_id"]: {
            "docs": int(row["docs"] or 0),
            "chunks": int(row["chunks"] or 0),
            "pages": int(row["pages"] or 0),
        }
        for row in rows
    }


def _kb_to_dict(kb: Knowledgebase, stats: dict[str, int] | None = None) -> dict[str, Any]:
    """将 Knowledgebase 实例转换为列表接口响应字典。"""
    live = stats or _doc_stats_map([kb.id]).get(kb.id, {})
    return {
        "id": kb.id,
        "tenant_id": getattr(kb, "tenant_id", "default") or "default",
        "name": kb.name,
        "avatar": kb.avatar,
        "description": kb.description,
        "embd_id": kb.embd_id,
        "permission": kb.permission,
        "doc_num": live.get("docs", kb.doc_num or 0),
        "chunk_num": live.get("chunks", kb.chunk_num or 0),
        "parser_id": kb.parser_id,
        "chunker_id": kb.chunker_id,
        "rag_mode": getattr(kb, "rag_mode", "text") or "text",
        "vlm_id": getattr(kb, "vlm_id", "") or "",
        "page_top_n": getattr(kb, "page_top_n", 3) or 3,
        "page_num": live.get("pages", getattr(kb, "page_num", 0) or 0),
        "update_date": format_datetime(kb.update_date),
    }


def _kb_detail_to_dict(kb: Knowledgebase) -> dict[str, Any]:
    """将 Knowledgebase 实例转换为 detail 接口响应字典。"""
    live = _doc_stats_map([kb.id]).get(kb.id, {})
    return {
        "id": kb.id,
        "tenant_id": getattr(kb, "tenant_id", "default") or "default",
        "name": kb.name,
        "avatar": kb.avatar,
        "description": kb.description,
        "embd_id": kb.embd_id,
        "permission": kb.permission,
        "doc_num": live.get("docs", kb.doc_num or 0),
        "chunk_num": live.get("chunks", kb.chunk_num or 0),
        "parser_id": kb.parser_id,
        "chunker_id": kb.chunker_id,
        "chunker_config": kb.chunker_config,
        "rag_mode": getattr(kb, "rag_mode", "text") or "text",
        "vlm_id": getattr(kb, "vlm_id", "") or "",
        "page_top_n": getattr(kb, "page_top_n", 3) or 3,
        "page_num": live.get("pages", getattr(kb, "page_num", 0) or 0),
    }


def _acl_to_dict(row: KnowledgebaseAcl) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "kb_id": row.kb_id,
        "subject_type": row.subject_type,
        "subject_id": row.subject_id,
        "permission": row.permission,
        "status": row.status,
        "update_date": format_datetime(row.update_date),
    }


def _get_es_tags(kb_ids: list[str]) -> list[str]:
    """通过 Elasticsearch 查询知识库的 tag_kwd 标签列表。"""
    return es_service.get_tags(kb_ids)


def _remove_kb_documents(kb_id: str) -> None:
    """删除知识库下所有文档及其关联的文件记录、任务记录（事务内调用）。"""
    doc_ids = list(Document.objects.filter(kb_id=kb_id).values_list("id", flat=True))
    if not doc_ids:
        return

    Task.objects.filter(doc_id__in=doc_ids).delete()

    file_ids = list(
        File2Document.objects.filter(document_id__in=doc_ids).values_list("file_id", flat=True)
    )
    File2Document.objects.filter(document_id__in=doc_ids).delete()

    if file_ids:
        File.objects.filter(id__in=file_ids, source_type=_KB_SOURCE_TYPE).delete()

    Document.objects.filter(kb_id=kb_id).delete()


def _cleanup_kb_es(kb: Knowledgebase) -> None:
    """清理 Elasticsearch 中与知识库相关的数据（失败时静默忽略）。"""
    try:
        es_service.delete_kb_chunks(kb.id)
    except Exception:  # noqa: BLE001
        logger.exception("知识库 ES 数据清理失败 kb_id={}", kb.id)


@extend_schema(
    tags=_KB_TAG,
    summary="分页/条件查询知识库列表",
    description="支持分页和关键词过滤，page_size=0 表示不分页返回全部。",
    parameters=[
        OpenApiParameter("page", OpenApiTypes.INT, description="页码，从 1 开始"),
        OpenApiParameter("page_size", OpenApiTypes.INT, description="每页条数，0 表示不分页"),
        OpenApiParameter("keywords", OpenApiTypes.STR, description="名称关键词模糊搜索"),
        OpenApiParameter("parser_id", OpenApiTypes.STR, description="解析器 ID 过滤"),
        OpenApiParameter("orderby", OpenApiTypes.STR, description="排序字段，默认 create_date"),
        OpenApiParameter("desc", OpenApiTypes.BOOL, description="是否降序，默认 true"),
    ],
    request=KbListSerializer,
    responses={200: None},
)
@api_view(["POST"])
def kb_list(request: Request) -> Response:
    """POST /kb/list — 分页/条件查询知识库列表。"""
    merged: dict[str, Any] = {**request.GET.dict(), **(request.data if isinstance(request.data, dict) else {})}
    ser = KbListSerializer(data=merged)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    keywords: str = vd["keywords"]
    page: int = vd["page"]
    page_size: int = vd["page_size"]
    parser_id: str = vd.get("parser_id", "")
    tenant_id: str = vd.get("tenant_id") or request_tenant_id(request)
    orderby: str = vd["orderby"]
    desc: bool = vd["desc"]

    qs = Knowledgebase.objects.filter(status="1", tenant_id=tenant_id)
    user_id = request_user_id(request)
    if not require_role(request, "admin") is None:
        allowed_ids = [
            kb_id for kb_id in qs.values_list("id", flat=True)
            if can_access_kb(tenant_id, user_id, kb_id, "read")
        ]
        qs = qs.filter(id__in=allowed_ids)
    if keywords:
        qs = qs.filter(name__icontains=keywords)
    if parser_id:
        qs = qs.filter(parser_id=parser_id)

    valid_fields = {f.name for f in Knowledgebase._meta.get_fields()}
    if orderby in valid_fields:
        qs = qs.order_by(f"-{orderby}" if desc else orderby)

    if page_size > 0:
        paginator = Paginator(qs, page_size)
        total: int = paginator.count
        page_obj = paginator.get_page(page)
        objects = list(page_obj.object_list)
    else:
        total = qs.count()
        objects = list(qs)
    stats = _doc_stats_map([kb.id for kb in objects])
    kbs = [_kb_to_dict(kb, stats.get(kb.id)) for kb in objects]

    return success_response({"kbs": kbs, "total": total})


@extend_schema(
    tags=_KB_TAG,
    summary="创建知识库",
    description=(
        "创建一个新的知识库，名称全局唯一。\n\n"
        "**embd_id**：向量模型 ID，如 `bge-m3@VLLM2`；不传时自动从系统配置 `settings.EMBEDDING_MODEL_ID` 读取。\n\n"
        "**chunker_config** 支持字段：\n"
        "- `auto_keywords`：自动抽取关键词数量\n"
        "- `auto_questions`：自动生成问题数量\n"
        "- `chunk_token_num`：分块 token 上限\n"
        "- `delimiter`：分块分隔符，如 `\\n\\n`\n"
        "- `mineru_max_section_chars`：MinerU 单节最大字符数\n"
        "- `use_macbert`：是否使用 MacBERT 重排（bool）"
    ),
    request=KbCreateSerializer,
    responses={200: None},
)
@api_view(["POST"])
def kb_create(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /kb/create — 创建知识库。"""
    ser = KbCreateSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    name: str = vd["name"]

    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    if Knowledgebase.objects.filter(tenant_id=tenant_id, name=name, status="1").exists():
        logger.info("创建知识库失败：名称重复 name={}", name)
        return error_response("知识库名称已存在，请使用其他名称。")

    parser_id = vd.get("parser_id") or _DEFAULT_PARSER_ID
    chunker_id: str = vd["chunker_id"]
    chunker_config: dict = vd.get("chunker_config") or {}
    embd_id = vd.get("embd_id") or getattr(settings, "EMBEDDING_MODEL_ID", "")
    logger.info(
        "开始创建知识库 name={} parser_id={} chunker_id={} embd_id={}",
        name, parser_id, chunker_id, embd_id,
    )
    kb = Knowledgebase.objects.create(
        id=get_uuid(),
        tenant_id=tenant_id,
        name=name,
        description=vd.get("description"),
        permission=vd.get("permission", "me"),
        parser_id=parser_id,
        chunker_id=chunker_id,
        chunker_config=chunker_config,
        avatar=vd.get("avatar"),
        embd_id=embd_id,
        status="1",
        rag_mode=vd.get("rag_mode") or "vision",
        vlm_id=vd.get("vlm_id") or "qwen-vl-plus",
        page_top_n=int(vd.get("page_top_n") or 3),
    )
    logger.info(
        "知识库创建完成 kb_id={} name={} parser_id={} chunker_id={} embd_id={}",
        kb.id, kb.name, kb.parser_id, kb.chunker_id, kb.embd_id,
    )
    KnowledgebaseAcl.objects.get_or_create(
        tenant_id=tenant_id,
        kb_id=kb.id,
        subject_type="user",
        subject_id=request_user_id(request),
        defaults={"id": get_uuid(), "permission": "admin", "status": "1"},
    )
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="create", resource_type="knowledgebase", resource_id=kb.id, detail=_kb_to_dict(kb))
    return success_response({"id": kb.id})


@extend_schema(
    tags=_KB_TAG,
    summary="删除知识库",
    description="删除知识库及其下所有文档、文件关联和 Elasticsearch 索引数据。",
    request=KbRmSerializer,
    responses={200: None},
)
@api_view(["POST"])
def kb_rm(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /kb/rm — 删除知识库（级联删除文档和 ES 数据）。"""
    ser = KbRmSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    kb_id: str = ser.validated_data["kb_id"]
    tenant_id = request_tenant_id(request)
    try:
        kb = Knowledgebase.objects.get(id=kb_id, tenant_id=tenant_id, status="1")
    except Knowledgebase.DoesNotExist:
        return error_response("知识库不存在或已被删除。", code=404)

    with transaction.atomic():
        _remove_kb_documents(kb_id)
        File.objects.filter(source_type=_KB_SOURCE_TYPE, type="folder", name=kb.name).delete()
        kb.delete()

    _cleanup_kb_es(kb)
    try:
        from __010__colpali.index.vision_index import drop_vision_index
        from __010__colpali.paths import BYALDI_DIR

        drop_vision_index(kb_id, BYALDI_DIR)
    except Exception:
        logger.exception("删除知识库视觉索引失败 kb_id={}", kb_id)
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="delete", resource_type="knowledgebase", resource_id=kb_id, detail={"name": kb.name})
    return success_response(True)


@extend_schema(
    tags=_KB_TAG,
    summary="获取知识库详情",
    parameters=[OpenApiParameter("kb_id", OpenApiTypes.STR, required=True, description="知识库 ID")],
    responses={200: None},
)
@api_view(["GET"])
def kb_detail(request: Request) -> Response:
    """GET /kb/detail?kb_id=xxx — 获取知识库详情。"""
    ser = KbDetailSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    kb_id: str = ser.validated_data["kb_id"]
    tenant_id: str = ser.validated_data.get("tenant_id") or request_tenant_id(request)
    try:
        kb = Knowledgebase.objects.get(id=kb_id, tenant_id=tenant_id, status="1")
    except Knowledgebase.DoesNotExist:
        return error_response("知识库不存在。", code=404)
    denied = require_kb_access(request, kb_id, "read")
    if denied is not None:
        return denied

    return success_response(_kb_detail_to_dict(kb))


@extend_schema(
    tags=_KB_TAG,
    summary="更新知识库",
    description=(
        "更新知识库基本信息。`kb_id`、`name`、`parser_id` 为必填项。\n\n"
        "**embd_id**：向量模型 ID，如 `bge-m3@VLLM2`；不传则保持原值不变。\n\n"
        "**chunker_config** 支持字段：\n"
        "- `auto_keywords`：自动抽取关键词数量\n"
        "- `auto_questions`：自动生成问题数量\n"
        "- `chunk_token_num`：分块 token 上限\n"
        "- `delimiter`：分块分隔符，如 `\\n\\n`\n"
        "- `mineru_max_section_chars`：MinerU 单节最大字符数\n"
        "- `use_macbert`：是否使用 MacBERT 重排（bool）\n\n"
        "保存时 `update_date` 自动更新为当前时间。"
    ),
    request=KbUpdateSerializer,
    responses={200: None},
)
@api_view(["POST"])
def kb_update(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /kb/update — 更新知识库信息。"""
    ser = KbUpdateSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    kb_id: str = vd["kb_id"]
    tenant_id: str = vd.get("tenant_id") or request_tenant_id(request)

    try:
        kb = Knowledgebase.objects.get(id=kb_id, tenant_id=tenant_id, status="1")
    except Knowledgebase.DoesNotExist:
        return error_response("知识库不存在。", code=404)

    new_name: str = vd["name"]
    if new_name.lower() != kb.name.lower() and Knowledgebase.objects.filter(
        tenant_id=tenant_id, name=new_name, status="1"
    ).exclude(id=kb_id).exists():
        return error_response("知识库名称已存在，请使用其他名称。")

    old_mode = kb.rag_mode
    update_fields = [
        "name", "description", "parser_id", "permission",
        "chunker_id", "chunker_config", "avatar", "embd_id",
        "rag_mode", "vlm_id", "page_top_n",
    ]
    for field in update_fields:
        if field in vd and vd[field] is not None:
            setattr(kb, field, vd[field])
    kb.save()
    logger.info("知识库更新完成 kb_id={} name={}", kb.id, kb.name)
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="update", resource_type="knowledgebase", resource_id=kb.id, detail=_kb_to_dict(kb))
    if "rag_mode" in vd and vd["rag_mode"] and vd["rag_mode"] != old_mode:
        from __001__rag.tasks import parse_document
        from __010__colpali.index.vision_index import drop_vision_index
        from __010__colpali.paths import BYALDI_DIR

        new_mode = vd["rag_mode"]
        if new_mode == "text":
            drop_vision_index(kb.id, BYALDI_DIR)
        for doc in Document.objects.filter(kb_id=kb.id, status="1"):
            parse_document.delay(doc.id)

    return success_response(_kb_to_dict(kb))


@extend_schema(tags=_KB_TAG, summary="知识库授权列表", responses={200: None})
@api_view(["GET"])
def kb_acl_list(request: Request) -> Response:
    ser = KbAclListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    kb_id = vd["kb_id"]
    denied = require_kb_access(request, kb_id, "admin")
    if denied is not None:
        return denied
    rows = KnowledgebaseAcl.objects.filter(tenant_id=tenant_id, kb_id=kb_id).order_by("subject_type", "subject_id")
    return success_response([_acl_to_dict(row) for row in rows])


@extend_schema(tags=_KB_TAG, summary="保存知识库授权", request=KbAclSaveSerializer, responses={200: None})
@api_view(["POST"])
def kb_acl_save(request: Request) -> Response:
    ser = KbAclSaveSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    kb_id = vd["kb_id"]
    denied = require_kb_access(request, kb_id, "admin")
    if denied is not None:
        return denied
    row, _ = KnowledgebaseAcl.objects.get_or_create(
        tenant_id=tenant_id,
        kb_id=kb_id,
        subject_type=vd["subject_type"],
        subject_id=vd["subject_id"],
        defaults={"id": get_uuid()},
    )
    row.permission = vd["permission"]
    row.status = vd.get("status") or "1"
    row.save()
    payload = _acl_to_dict(row)
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="save_acl", resource_type="knowledgebase", resource_id=kb_id, detail=payload)
    return success_response(payload)


@extend_schema(tags=_KB_TAG, summary="删除知识库授权", request=KbAclRmSerializer, responses={200: None})
@api_view(["POST"])
def kb_acl_rm(request: Request) -> Response:
    ser = KbAclRmSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    row = KnowledgebaseAcl.objects.filter(id=vd["id"], tenant_id=tenant_id).first()
    if row is None:
        return error_response("授权记录不存在。", code=404)
    denied = require_kb_access(request, row.kb_id, "admin")
    if denied is not None:
        return denied
    kb_id = row.kb_id
    row.delete()
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="delete_acl", resource_type="knowledgebase", resource_id=kb_id, detail={"acl_id": vd["id"]})
    return success_response(True)


@extend_schema(
    tags=_KB_TAG,
    summary="查询知识库标签",
    description="根据 kb_ids（逗号分隔）从 Elasticsearch 中检索该知识库下所有的 tag_kwd 标签。",
    parameters=[
        OpenApiParameter(
            "kb_ids", OpenApiTypes.STR,
            description="知识库 ID 列表，逗号分隔，如 'id1,id2'",
        )
    ],
    responses={200: None},
)
@api_view(["GET"])
def kb_tags(request: Request) -> Response:
    """GET /kb/tags?kb_ids=id1,id2 — 查询知识库标签（via Elasticsearch）。"""
    ser = KbTagsSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    kb_ids_raw: str = ser.validated_data.get("kb_ids", "")
    kb_ids: list[str] = [k.strip() for k in kb_ids_raw.split(",") if k.strip()]

    if not kb_ids:
        return success_response([])

    tags = _get_es_tags(kb_ids)
    return success_response(tags)
