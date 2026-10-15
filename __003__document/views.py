"""文档（Document）接口视图"""

from __future__ import annotations

# 1. Python 标准库
import io
import json
import mimetypes
import pathlib
import re
import zipfile
from datetime import datetime
from typing import Any

# 2. 第三方库
from celery import current_app
from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.models import (
    Document,
    DocumentVersion,
    RUN_CANCEL,
    RUN_DONE,
    RUN_IDLE,
    RUN_RUNNING,
    STATUS_DISABLED,
    File, File2Document, Knowledgebase, Task
)
from __001__rag.search import es_service
from __001__rag.storage import minio_service
from __001__rag.tasks import parse_document
from __001__rag.api.utils import doc_to_dict
from __001__rag.utils import error_response, get_file_extension, get_uuid, success_response
from __001__rag.utils.time import format_datetime
from __007__rag_conf.utils.support_file import get_parsers_by_file_type

from .serializers import (
    DocBatchDownloadSerializer,
    DocChangeParserSerializer,
    DocChangeStatusSerializer,
    DocListSerializer,
    DocRenameSerializer,
    DocRmSerializer,
    DocRunSerializer,
    DocTaskListSerializer,
    DocVersionListSerializer,
    DocSetMetaSerializer,
)
from __001__rag.ops import request_tenant_id, request_user_id, require_kb_access, require_role, write_audit

_DOC_TAG = ["document"]
_KB_SOURCE_TYPE = "knowledgebase"


@extend_schema(
    tags=_DOC_TAG,
    summary="文档分页列表",
    description="根据知识库 ID 分页查询文档列表，支持关键词过滤和多字段排序。",
    parameters=[
        OpenApiParameter("kb_id", OpenApiTypes.STR, required=True, description="知识库 ID"),
        OpenApiParameter("keywords", OpenApiTypes.STR, description="文件名关键词（模糊匹配）"),
        OpenApiParameter("page", OpenApiTypes.INT, description="页码，从 1 开始，默认 1"),
        OpenApiParameter("page_size", OpenApiTypes.INT, description="每页条数，默认 15"),
        OpenApiParameter("orderby", OpenApiTypes.STR, description="排序字段，默认 create_date"),
        OpenApiParameter("desc", OpenApiTypes.BOOL, description="是否降序，默认 true"),
        OpenApiParameter("status", OpenApiTypes.STR, description="启用状态过滤，如 0=未启用，1=启用，不传则不过滤"),
        OpenApiParameter(
            "run", OpenApiTypes.STR,
            description="解析运行状态过滤，如 0=未运行，1=已完成，2=运行中，3=取消，-1=报错；支持逗号分隔多值",
        ),
    ],
    responses={200: None},
)
@api_view(["GET"])
def document_list(request: Request) -> Response:
    """GET /document/list — 文档分页列表。"""
    ser = DocListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    kb_id: str = vd["kb_id"]
    keywords: str = vd["keywords"]
    page: int = vd["page"]
    page_size: int = vd["page_size"]
    orderby: str = _normalize_orderby(vd["orderby"])
    desc: bool = vd["desc"]
    status: str = vd.get("status") or ""
    run_values: list[str] = vd.get("run") or []
    tenant_id: str = vd.get("tenant_id") or ""
    denied = require_kb_access(request, kb_id, "read")
    if denied is not None:
        return denied

    qs = Document.objects.filter(kb_id=kb_id)
    if tenant_id:
        qs = qs.filter(tenant_id=tenant_id)
    if keywords:
        qs = qs.filter(name__icontains=keywords)
    if status:
        qs = qs.filter(status=status)
    if run_values:
        qs = qs.filter(run__in=run_values)

    valid_fields = {f.name for f in Document._meta.get_fields()}
    if orderby in valid_fields:
        qs = qs.order_by(f"-{orderby}" if desc else orderby)
    else:
        qs = qs.order_by("-create_date")

    paginator = Paginator(qs, page_size)
    page_obj = paginator.get_page(page)
    total: int = paginator.count
    docs_qs = page_obj.object_list

    docs: list[dict[str, Any]] = []
    for doc in docs_qs:
        _heal_completed_document(doc)
        d = doc_to_dict(doc)
        d.pop("thumbnail", None)
        docs.append(d)

    return success_response({"total": total, "docs": docs})


@extend_schema(
    tags=_DOC_TAG,
    summary="获取文档图片",
    description="根据列表/缩略图接口返回的 image_id 从 MinIO 读取图片。",
    parameters=[OpenApiParameter("image_id", OpenApiTypes.STR, location="path", description="图片 ID")],
    responses={200: None},
)
@api_view(["GET"])
def document_image(request: Request, image_id: str) -> HttpResponse:
    """GET /document/image/<image_id> — 获取文档缩略图、原图或解析页图。"""
    doc = Document.objects.filter(id=image_id).first()
    if doc is not None:
        try:
            bucket, name = minio_service.get_storage_address(doc.id)
            file_bytes = minio_service.get(bucket, name)
            return HttpResponse(file_bytes, content_type=_guess_content_type(doc.name or name, default="image/jpeg"))
        except Exception as exc:  # noqa: BLE001
            logger.info("按文档 ID 读取原图失败，回退页图目录 doc_id={} error={}", image_id, exc)
            page_dir = pathlib.Path(settings.BASE_DIR) / "data" / "page_images"
            matches = sorted(page_dir.rglob(f"*{image_id}*")) if page_dir.exists() else []
            if matches:
                data = matches[0].read_bytes()
                return HttpResponse(data, content_type=_guess_content_type(matches[0].name, default="image/png"))
            return HttpResponse("Image not found.", status=404)
    try:
        bucket, name = _parse_image_id(image_id)
    except ValueError:
        logger.info("文档图片获取失败：图片标识无效 image_id={}", image_id)
        return HttpResponse("Image not found.", status=404)

    try:
        exists = minio_service.obj_exist(bucket, name)
    except Exception:
        exists = False
    if not exists:
        logger.info("文档图片不存在 image_id={} bucket={} name={}", image_id, bucket, name)
        return HttpResponse("Image not found.", status=404)

    try:
        file_bytes = minio_service.get(bucket, name)
    except Exception as exc:
        logger.exception("文档图片读取失败 image_id={}", image_id)
        return HttpResponse(f"图片下载失败: {exc}", status=500)
    return HttpResponse(file_bytes, content_type=_guess_content_type(name, default="image/jpeg"))


@extend_schema(
    tags=_DOC_TAG,
    summary="变更文档状态",
    description="修改文档的可用状态（0=禁用，1=启用），同时同步更新 Elasticsearch 中的 available_int 字段。",
    request=DocChangeStatusSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_change_status(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /document/change_status — 变更文档状态。"""
    ser = DocChangeStatusSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    doc_id: str = vd["doc_id"]
    status: str = vd["status"]

    try:
        doc = Document.objects.get(id=doc_id)
    except Document.DoesNotExist:
        return error_response("文档不存在。", code=404)
    denied = require_kb_access(request, doc.kb_id, "write")
    if denied is not None:
        return denied

    Document.objects.filter(id=doc_id).update(
        status=status,
        update_date=timezone.now(),
    )

    _sync_es_available(doc.kb_id, doc_id, int(status))

    logger.info("文档状态变更完成 doc_id={} status={}", doc_id, status)
    return success_response(True)


@extend_schema(
    tags=_DOC_TAG,
    summary="触发文档解析",
    description=(
            "触发一个或多个文档的解析任务。run='2'=运行，run='3'=取消。"
            "delete=true 时会先清空已有 chunk 数据再重新解析。"
    ),
    request=DocRunSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_run(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /document/run — 触发文档解析任务。"""
    ser = DocRunSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    doc_ids: list[str] = vd["doc_ids"]
    run: str = vd["run"]
    delete: bool = vd["delete"]

    errors: list[str] = []
    for doc_id in doc_ids:
        doc = Document.objects.filter(id=doc_id).first()
        if doc is None:
            errors.append(f"文档不存在: {doc_id}")
            continue
        denied = require_kb_access(request, doc.kb_id, "write")
        if denied is not None:
            errors.append(f"无权操作文档: {doc_id}")
            continue
        err = _trigger_run(doc_id, run, delete)
        if err:
            logger.exception("文档解析运行处理失败 doc_id={}", doc_id)
            errors.append(err)

    if errors:
        return error_response("; ".join(errors))
    write_audit(tenant_id=request_tenant_id(request), user_id=request_user_id(request), action="run", resource_type="document", detail={"doc_ids": doc_ids, "run": run, "delete": delete})
    return success_response(True)


@extend_schema(
    tags=_DOC_TAG,
    summary="切换解析器",
    description=(
            "切换文档的解析器。图片类文档只能使用 picture 解析器；"
            "PPT/PPTX/Pages 可使用 presentation 或 FileTypeMapping 中已启用的解析方法（如 mineru）。"
            "切换后文档进度重置为 0，已有 chunk 将被清除。"
    ),
    request=DocChangeParserSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_change_parser(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /document/change_parser — 切换文档解析器。"""
    ser = DocChangeParserSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    doc_id: str = vd["doc_id"]
    parser_id: str = vd["parser_id"]
    chunker_id: str | None = vd.get("chunker_id")
    chunker_config: dict | None = vd.get("chunker_config")

    try:
        doc = Document.objects.get(id=doc_id)
    except Document.DoesNotExist:
        return error_response("文档不存在。", code=404)
    denied = require_kb_access(request, doc.kb_id, "write")
    if denied is not None:
        return denied

    # 已是相同解析器/切分器且配置未变时直接返回
    if doc.parser_id.lower() == parser_id.lower():
        same_chunker = chunker_id is None or (doc.chunker_id or "").lower() == chunker_id.lower()
        same_config = chunker_config is None or chunker_config == (doc.chunker_config or {})
        if same_chunker and same_config:
            logger.info("文档解析器未变化，跳过切换 doc_id={} parser_id={}", doc_id, parser_id)
            return success_response(True)

    # 文件类型约束校验
    err = _validate_parser_type(doc, parser_id)
    if err:
        logger.exception("文档解析器类型不兼容 doc_id={} parser_id={}", doc_id, parser_id)
        return error_response(err)

    update_fields: dict[str, Any] = {
        "parser_id": parser_id,
        "progress": 0.0,
        "progress_msg": "",
        "run": RUN_IDLE,
        "chunk_num": 0,
        "token_num": 0,
        "process_duration": 0.0,
        "update_date": timezone.now(),
    }
    if chunker_id is not None:
        update_fields["chunker_id"] = chunker_id
    if chunker_config is not None:
        update_fields["chunker_config"] = chunker_config

    with transaction.atomic():
        Document.objects.filter(id=doc_id).update(**update_fields)
        _decrement_kb_chunk_num(doc.kb_id, doc.chunk_num)

    # 清除旧 chunk 数据（ES）
    if doc.token_num > 0 or doc.chunk_num > 0:
        _cleanup_doc_es(doc)

    logger.info("文档解析器切换完成 doc_id={} parser_id={}", doc_id, parser_id)
    return success_response(True)


@extend_schema(
    tags=_DOC_TAG,
    summary="设置文档元数据",
    description="设置文档的 meta_fields 元数据，meta 必须为 JSON 对象格式。",
    request=DocSetMetaSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_set_meta(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /document/set_meta — 设置文档元数据。"""
    ser = DocSetMetaSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    doc_id: str = vd["doc_id"]
    meta: dict = vd["meta"]

    if not Document.objects.filter(id=doc_id).exists():
        return error_response("文档不存在。", code=404)
    doc = Document.objects.get(id=doc_id)
    denied = require_kb_access(request, doc.kb_id, "write")
    if denied is not None:
        return denied

    Document.objects.filter(id=doc_id).update(
        meta_fields=meta,
        update_date=timezone.now(),
    )
    return success_response(True)


@extend_schema(
    tags=_DOC_TAG,
    summary="重命名文档",
    description="重命名文档，不允许修改扩展名。同一知识库内文件名不可重复。",
    request=DocRenameSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_rename(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /document/rename — 重命名文档。"""
    ser = DocRenameSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    doc_id: str = vd["doc_id"]
    new_name: str = vd["name"]

    try:
        doc = Document.objects.get(id=doc_id)
    except Document.DoesNotExist:
        return error_response("文档不存在。", code=404)

    # 扩展名不可修改
    old_suffix = pathlib.Path(doc.name or "").suffix.lower()
    new_suffix = pathlib.Path(new_name).suffix.lower()
    if old_suffix != new_suffix:
        return error_response("不允许修改文件扩展名。")

    # 同知识库内不可重名
    if Document.objects.filter(kb_id=doc.kb_id, name=new_name).exclude(id=doc_id).exists():
        return error_response("同一知识库中已存在同名文档。")

    Document.objects.filter(id=doc_id).update(
        name=new_name,
        update_date=timezone.now(),
    )

    # 同步更新 File 表
    _sync_file_rename(doc_id, new_name)

    return success_response(True)


@extend_schema(
    tags=_DOC_TAG,
    summary="删除文档",
    description="删除一个或多个文档，同时删除关联的 Task、File2Document、File 记录及 MinIO 存储对象。",
    request=DocRmSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_rm(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /document/rm — 删除文档（支持批量）。"""
    ser = DocRmSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    doc_ids: list[str] = ser.validated_data["doc_id"]
    tenant_id = request_tenant_id(request)
    user_id = request_user_id(request)
    errors: list[str] = []

    for doc_id in doc_ids:
        err = _delete_single_doc(doc_id)
        if err:
            logger.exception("文档删除失败 doc_id={}", doc_id)
            errors.append(err)

    if errors:
        return error_response("; ".join(errors))
    write_audit(tenant_id=tenant_id, user_id=user_id, action="delete", resource_type="document", detail={"doc_ids": doc_ids})
    return success_response(True)


@extend_schema(
    tags=_DOC_TAG,
    summary="上传文档",
    description=(
            "上传一个或多个文档到指定知识库。"
            "请求为 multipart/form-data，必须包含 kb_id 字段和至少一个 file 文件。"
    ),
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "kb_id": {"type": "string", "description": "知识库 ID"},
                "file": {
                    "type": "array",
                    "items": {"type": "string", "format": "binary"},
                    "description": "一个或多个文档文件",
                },
            },
            "required": ["kb_id", "file"],
        }
    },
    responses={200: None},
)
@api_view(["POST"])
def document_upload(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    """POST /document/upload — 上传文档到知识库。"""
    kb_id: str = request.data.get("kb_id", "").strip()
    if not kb_id:
        return error_response('缺少必填参数 "kb_id"。')

    if "file" not in request.FILES:
        return error_response("请求中未包含文件（file 字段）。")

    try:
        kb = Knowledgebase.objects.get(id=kb_id, tenant_id=request_tenant_id(request))
    except Knowledgebase.DoesNotExist:
        return error_response("知识库不存在。", code=404)

    file_objs = request.FILES.getlist("file")
    if not file_objs:
        return error_response("未选择任何文件。")

    embd_id, parser_id, chunker_id, chunker_config = _get_processing_options(kb)

    uploaded: list[dict[str, Any]] = []
    errors: list[str] = []

    for file_obj in file_objs:
        if not file_obj.name:
            logger.info("跳过文件名为空的上传文件 kb_id={}", kb_id)
            errors.append("存在文件名为空的文件，已跳过。")
            continue
        try:
            doc_dict = _upload_single_file(
                file_obj,
                kb,
                embd_id=embd_id,
                parser_id=parser_id,
                chunker_id=chunker_id,
                chunker_config=chunker_config,
            )
            uploaded.append(doc_dict)
        except Exception as exc:
            logger.exception("单个文件上传失败 kb_id={} filename={}", kb_id, file_obj.name)
            errors.append(f"{file_obj.name}: {exc}")

    if errors and not uploaded:
        return error_response("\n".join(errors))

    logger.info("文档上传完成 kb_id={} uploaded_count={} error_count={}", kb_id, len(uploaded), len(errors))
    write_audit(
        tenant_id=getattr(kb, "tenant_id", "default") or "default",
        user_id=request_user_id(request),
        action="upload",
        resource_type="document",
        resource_id=kb_id,
        detail={"files": [item.get("name") for item in uploaded], "errors": errors},
        status="success" if not errors else "partial",
    )
    return success_response(uploaded)


@extend_schema(
    tags=_DOC_TAG,
    summary="下载/获取原始文档",
    description="通过文档 ID 从 MinIO 下载原始文件，按文件扩展名设置正确的 Content-Type。",
    parameters=[OpenApiParameter("id", OpenApiTypes.STR, location="path", description="文档 ID")],
    responses={200: None},
)
@api_view(["GET"])
def document_get_id(request: Request, id: str) -> HttpResponse:
    """GET /document/get/<id> — 下载原始文档。"""
    try:
        doc = Document.objects.get(id=id)
    except Document.DoesNotExist:
        return HttpResponse("文档不存在。", status=404)

    try:
        if getattr(settings, "CHUNK_LEGACY_COMPAT", False):
            # 旧版兼容模式：MinIO 中以文件名存储，bucket 按 kb_id 推算
            bucket = minio_service.normalize_bucket(doc.kb_id)
            name = doc.name or id
            logger.info(
                "旧版兼容模式：按文档名获取文件 doc_id={} bucket={} object={}",
                id, bucket, name,
            )
        else:
            bucket, name = minio_service.get_storage_address(id)

        file_bytes = minio_service.get(bucket, name)
    except Exception as exc:
        logger.exception("原始文档下载失败 doc_id={}", id)
        return HttpResponse(f"文件下载失败: {exc}", status=500)

    content_type = _guess_content_type(doc.name or name)
    response = HttpResponse(file_bytes, content_type=content_type)
    response["Content-Disposition"] = f'inline; filename="{doc.name or name}"'
    return response


@extend_schema(
    tags=_DOC_TAG,
    summary="批量下载文档",
    description="将多个文档打包为 ZIP 文件后下载。请求体为 JSON，包含 doc_ids 列表。",
    request=DocBatchDownloadSerializer,
    responses={200: None},
)
@api_view(["POST"])
def document_batch_download(request: Request) -> HttpResponse | Response:
    """POST /document/batch_download — 批量下载文档（ZIP）。"""
    ser = DocBatchDownloadSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    doc_ids: list[str] = ser.validated_data["doc_ids"]

    zip_buffer = io.BytesIO()
    added = 0

    used_names: dict[str, int] = {}
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for doc_id in doc_ids:
            try:
                doc = Document.objects.get(id=doc_id)

                # 优先通过 File2Document 链获取存储地址，失败时用 Document 字段兜底
                file_bytes = None
                try:
                    bucket, name = minio_service.get_storage_address(doc_id)
                    file_bytes = minio_service.get(bucket, name)
                except Exception:
                    bucket = doc.kb_id
                    name = doc.location or doc.id
                    file_bytes = minio_service.get(bucket, name)

                # ZIP 内文件名去重：同名文件追加后缀
                filename = doc.name or doc_id
                if filename in used_names:
                    used_names[filename] += 1
                    stem, _, ext = filename.rpartition(".")
                    filename = f"{stem}({used_names[filename]}).{ext}" if ext else f"{filename}({used_names[filename]})"
                else:
                    used_names[filename] = 0

                zf.writestr(filename, file_bytes)
                added += 1
            except Exception as exc:
                logger.exception("批量下载跳过文档 doc_id={}", doc_id)

    if added == 0:
        logger.info("批量下载没有有效文件 doc_ids={}", doc_ids)
        return HttpResponse("没有可下载的有效文件。", status=404)

    zip_buffer.seek(0)
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    filename = f"batch_download_{timestamp}.zip"

    response = HttpResponse(zip_buffer.getvalue(), content_type="application/zip")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    logger.info("批量下载打包完成 added_count={} zip_bytes={} filename={}", added, len(zip_buffer.getvalue()), filename)
    return response


@extend_schema(
    tags=_DOC_TAG,
    summary="查询文档处理任务",
    description="按知识库或文档查询解析/索引任务，用于任务中心和文档详情展示。",
    parameters=[
        OpenApiParameter("kb_id", OpenApiTypes.STR, required=False, description="知识库 ID"),
        OpenApiParameter("doc_id", OpenApiTypes.STR, required=False, description="文档 ID"),
        OpenApiParameter("page", OpenApiTypes.INT, required=False, description="页码"),
        OpenApiParameter("page_size", OpenApiTypes.INT, required=False, description="每页条数"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def document_task_list(request: Request) -> Response:
    ser = DocTaskListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    qs = Task.objects.all().order_by("-create_date")
    doc_id = vd.get("doc_id") or ""
    kb_id = vd.get("kb_id") or ""
    tenant_id = vd.get("tenant_id") or ""
    if doc_id:
        qs = qs.filter(doc_id=doc_id)
    if kb_id:
        doc_filter = {"kb_id": kb_id}
        if tenant_id:
            doc_filter["tenant_id"] = tenant_id
        doc_ids = Document.objects.filter(**doc_filter).values_list("id", flat=True)
        qs = qs.filter(doc_id__in=doc_ids)
    elif tenant_id:
        doc_ids = Document.objects.filter(tenant_id=tenant_id).values_list("id", flat=True)
        qs = qs.filter(doc_id__in=doc_ids)

    paginator = Paginator(qs, vd["page_size"])
    page_obj = paginator.get_page(vd["page"])
    docs = {
        d.id: d
        for d in Document.objects.filter(id__in=[task.doc_id for task in page_obj.object_list])
    }
    tasks = []
    for task in page_obj.object_list:
        doc = docs.get(task.doc_id)
        _heal_waiting_vision_task(task, doc)
        tasks.append(_task_to_dict(task, doc))
    return success_response({
        "total": paginator.count,
        "tasks": tasks,
    })


@extend_schema(tags=_DOC_TAG, summary="文档版本列表", responses={200: None})
@api_view(["GET"])
def document_version_list(request: Request) -> Response:
    ser = DocVersionListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    qs = DocumentVersion.objects.filter(document_id=vd["doc_id"]).order_by("-version")
    if vd.get("tenant_id"):
        qs = qs.filter(tenant_id=vd["tenant_id"])
    return success_response([{
        "id": row.id,
        "tenant_id": row.tenant_id,
        "kb_id": row.kb_id,
        "document_id": row.document_id,
        "version": row.version,
        "file_name": row.file_name,
        "file_size": row.file_size,
        "location": row.location or "",
        "is_current": row.is_current,
        "created_by": row.created_by or "",
        "create_date": format_datetime(row.create_date),
    } for row in qs[:100]])


def _heal_completed_document(doc: Document) -> None:
    """补齐历史脏数据：已完成却进度<1，或已有切片/页图却未写入 index_modes。"""
    extras: dict[str, Any] = {}
    modes = [part for part in (doc.index_modes or "").split(",") if part]
    if int(doc.chunk_num or 0) > 0 and "text" not in modes:
        modes.append("text")
    if int(doc.page_num or 0) > 0 and "vision" not in modes:
        modes.append("vision")
    joined = ",".join(modes)
    if joined != (doc.index_modes or ""):
        extras["index_modes"] = joined
        doc.index_modes = joined
    if doc.run == RUN_DONE and float(doc.progress or 0) < 1:
        extras["progress"] = 1.0
        doc.progress = 1.0
    if extras:
        Document.objects.filter(id=doc.id).update(**extras)


def _heal_waiting_vision_task(task: Task, doc: Document | None) -> None:
    """文本阶段留下的“等待视觉建索”任务，在文档已完成后对齐为 100%。"""
    if doc is None or doc.run != RUN_DONE:
        return
    progress = float(task.progress or 0)
    msg = task.progress_msg or ""
    waiting = ("等待视觉" in msg) or ("跳过文本解析" in msg)
    if waiting and 0 <= progress < 1:
        Task.objects.filter(id=task.id).update(progress=1.0, progress_msg="视觉索引写入完成")
        task.progress = 1.0
        task.progress_msg = "视觉索引写入完成"


def _task_to_dict(task: Task, doc: Document | None = None) -> dict[str, Any]:
    return {
        "id": task.id,
        "doc_id": task.doc_id,
        "doc_name": doc.name if doc else "",
        "kb_id": doc.kb_id if doc else "",
        "task_type": task.task_type,
        "progress": task.progress,
        "progress_msg": task.progress_msg or "",
        "retry_count": task.retry_count,
        "process_duration": task.process_duration,
        "priority": task.priority,
        "create_date": format_datetime(task.create_date),
        "update_date": format_datetime(task.update_date),
    }


def _upload_single_file(
    file_obj: Any,
    kb: Knowledgebase,
    *,
    embd_id: str,
    parser_id: str,
    chunker_id: str,
    chunker_config: dict[str, Any],
) -> dict[str, Any]:
    """上传单个文件到 MinIO 并创建 Document / File / File2Document 数据库记录。

    Args:
        file_obj: Django InMemoryUploadedFile 或 TemporaryUploadedFile。
        kb: 目标知识库模型实例。

    Returns:
        doc_to_dict(doc) 字典。

    Raises:
        RuntimeError: MinIO 上传或数据库写入失败。
    """
    file_data: bytes = file_obj.read()
    file_name: str = file_obj.name
    file_size: int = len(file_data)
    file_ext: str = pathlib.Path(file_name).suffix.lstrip(".").lower()
    content_type: str = file_obj.content_type or "application/octet-stream"

    doc_id = get_uuid()
    file_id = get_uuid()
    f2d_id = get_uuid()

    bucket = minio_service.normalize_bucket(kb.id)
    # 旧版兼容模式：以文件名作为对象名，与旧版存储约定保持一致
    if getattr(settings, "CHUNK_LEGACY_COMPAT", False):
        object_name = file_name
    else:
        object_name = doc_id

    # 上传到 MinIO
    minio_service.put(bucket, object_name, file_data, content_type)

    with transaction.atomic():
        # 创建 Document 记录
        doc = Document.objects.create(
            id=doc_id,
            kb_id=kb.id,
            tenant_id=getattr(kb, "tenant_id", "default") or "default",
            name=file_name,
            type=file_ext,
            size=file_size,
            location=object_name,
            source_type="local",
            embd_id=embd_id,
            parser_id=parser_id,
            chunker_id=chunker_id,
            chunker_config=chunker_config,
            created_by=kb.created_by,
            run=RUN_IDLE,
            status=STATUS_DISABLED,
            progress=0.0,
            chunk_num=0,
            token_num=0,
        )

        # 创建 File 记录（parent_id = bucket，location = object_name）
        File.objects.create(
            id=file_id,
            name=file_name,
            parent_id=bucket,
            location=object_name,
            size=file_size,
            type=file_ext,
            source_type=_KB_SOURCE_TYPE,
            created_by=kb.created_by,
        )

        # 创建 File2Document 关联
        File2Document.objects.create(
            id=f2d_id,
            file_id=file_id,
            document_id=doc_id,
        )

        DocumentVersion.objects.create(
            id=get_uuid(),
            tenant_id=getattr(kb, "tenant_id", "default") or "default",
            kb_id=kb.id,
            document_id=doc_id,
            version=1,
            file_name=file_name,
            file_size=file_size,
            location=object_name,
            is_current="1",
            created_by=kb.created_by,
        )

        # 更新知识库文档计数
        Knowledgebase.objects.filter(id=kb.id).update(
            doc_num=F("doc_num") + 1,
            update_date=timezone.now(),
        )
    return doc_to_dict(doc)


def _get_processing_options(kb: Knowledgebase) -> tuple[str, str, str, dict[str, Any]]:
    """从知识库配置中读取向量模型、解析器和切分器设置。"""
    return kb.embd_id, kb.parser_id, kb.chunker_id, kb.chunker_config or {}


def _delete_single_doc(doc_id: str) -> str | None:
    """删除单个文档及其所有关联记录和 MinIO 存储对象。

    Args:
        doc_id: 文档 ID。

    Returns:
        成功时返回 None；失败时返回错误描述字符串。
    """
    try:
        doc = Document.objects.get(id=doc_id)
    except Document.DoesNotExist:
        return f"文档 {doc_id} 不存在。"
    kb_id = doc.kb_id

    # 获取 MinIO 存储地址（删库前先记录，避免关联被删后找不到）
    bucket: str | None = None
    object_name: str | None = None
    try:
        bucket, object_name = minio_service.get_storage_address(doc_id)
    except Exception as exc:
        logger.exception("待删除文档存储地址查询失败 doc_id={}", doc_id)

    try:
        with transaction.atomic():
            Task.objects.filter(doc_id=doc_id).delete()

            f2d_qs = File2Document.objects.filter(document_id=doc_id)
            file_ids: list[str] = list(f2d_qs.values_list("file_id", flat=True))
            f2d_qs.delete()

            if file_ids:
                File.objects.filter(id__in=file_ids, source_type=_KB_SOURCE_TYPE).delete()

            _decrement_kb_stats(kb_id, doc.chunk_num)

            doc.delete()

    except Exception as exc:
        logger.exception("删除文档数据库记录失败 doc_id={}", doc_id)
        return f"删除文档 {doc_id} 失败: {exc}"

    # 删除 MinIO 对象（在事务外执行，失败仅记录日志）
    if bucket and object_name:
        minio_service.rm(bucket, object_name)

    # 清除 ES 数据
    _cleanup_doc_es_by_id(kb_id, doc_id)
    try:
        from __010__colpali.tasks import rebuild_kb_vision_index

        rebuild_kb_vision_index(kb_id)
    except Exception:
        logger.exception("删除文档后重建视觉索引失败 kb_id={}", kb_id)

    logger.info("单个文档删除完成 doc_id={}", doc_id)
    return None


def _trigger_run(doc_id: str, run: str, delete: bool) -> str | None:
    """触发单个文档的解析任务。

    Args:
        doc_id: 文档 ID。
        run: 运行状态值（'1'=完成，'2'=解析中，'3'=取消）。
        delete: 是否先清除已有 chunk 数据。

    Returns:
        成功时返回 None；失败时返回错误描述字符串。
    """
    try:
        doc = Document.objects.get(id=doc_id)
    except Document.DoesNotExist:
        return f"文档 {doc_id} 不存在。"
    update_info: dict[str, Any] = {
        "run": run,
        "update_date": timezone.now(),
    }
    if run == RUN_RUNNING or delete:
        update_info["progress"] = 0.0
    elif run == RUN_DONE:
        update_info["progress"] = 1.0

    if delete:
        update_info.update({
            "progress_msg": "",
            "chunk_num": 0,
            "token_num": 0,
            "process_duration": 0.0,
        })

    with transaction.atomic():
        Document.objects.filter(id=doc_id).update(**update_info)
        if delete:
            _decrement_kb_chunk_num(doc.kb_id, doc.chunk_num)

    if delete:
        Task.objects.filter(doc_id=doc_id).delete()
        _cleanup_doc_es(doc)

    if run == RUN_RUNNING:
        parse_document.delay(doc_id)
    elif run == RUN_CANCEL:
        _cancel_running_task(doc_id)
    return None


def _cancel_running_task(doc_id: str) -> None:
    """取消文档正在执行的解析任务。

    从 Task 记录的 digest 字段读取 celery_task_id，调用 Celery revoke。
    同时也为 chord 子任务取消做准备（更新 Document.run 状态后，
    chord 回调 finalize_document 会检查并跳过写入）。
    """
    active_task = Task.objects.filter(
        doc_id=doc_id, progress__gte=0.0, progress__lt=1.0,
    ).order_by("-create_date").first()

    if not active_task:
        logger.info("未找到活跃任务，无需取消 doc_id={}", doc_id)
        return

    # 从 digest 提取 celery_task_id 和 sub_task_ids
    celery_task_id = None
    sub_task_ids: list[str] = []
    if active_task.digest:
        try:
            digest = json.loads(active_task.digest) if isinstance(active_task.digest, str) else active_task.digest
            celery_task_id = digest.get("celery_task_id")
            sub_task_ids = digest.get("sub_task_ids", [])
        except (json.JSONDecodeError, TypeError, AttributeError):
            logger.exception("[DEGRADE] 任务摘要解析失败 doc_id={}", doc_id)

    # 先撤销主任务
    if celery_task_id:
        logger.info("正在撤销 Celery 主任务 doc_id={} celery_task_id={}", doc_id, celery_task_id)
        current_app.control.revoke(celery_task_id, terminate=True)

    # 再批量撤销所有子任务（关键词/问题/Embedding）
    if sub_task_ids:
        logger.info("正在撤销 Celery 子任务 doc_id={} count={}", doc_id, len(sub_task_ids))
        for sid in sub_task_ids:
            try:
                current_app.control.revoke(sid, terminate=True)
            except Exception:
                logger.exception("撤销子任务失败 task_id={}", sid)

    if not celery_task_id and not sub_task_ids:
        logger.info("Task 记录中无 celery_task_id 可撤销 doc_id={} task_id={}", doc_id, active_task.id)

    # 更新 Task 记录为已取消
    Task.objects.filter(id=active_task.id).update(
        progress=-1.0,
        progress_msg="任务已取消",
        update_date=timezone.now(),
    )


def _sync_file_rename(doc_id: str, new_name: str) -> None:
    """将重命名操作同步到 File 表。

    Args:
        doc_id: 文档 ID。
        new_name: 新文件名。
    """
    try:
        f2d = File2Document.objects.filter(document_id=doc_id).first()
        if f2d:
            File.objects.filter(id=f2d.file_id).update(
                name=new_name,
                update_date=timezone.now(),
            )
    except Exception as exc:
        logger.exception("同步文件名到 File 表失败 doc_id={}", doc_id)


def _decrement_kb_stats(kb_id: str, chunk_num: int) -> None:
    """删除文档时同步扣减知识库文档数与 chunk 数。"""
    logger.info("扣减知识库文档数和切片数 kb_id={} chunk_num={}", kb_id, chunk_num)
    Knowledgebase.objects.filter(id=kb_id).update(
        doc_num=Greatest(F("doc_num") - Value(1), Value(0)),
        chunk_num=Greatest(F("chunk_num") - Value(max(chunk_num, 0)), Value(0)),
        update_date=timezone.now(),
    )


def _decrement_kb_chunk_num(kb_id: str, chunk_num: int) -> None:
    """清空文档解析结果时同步扣减知识库 chunk 数。"""
    if chunk_num <= 0:
        logger.info("跳过扣减知识库切片数 kb_id={} chunk_num={}", kb_id, chunk_num)
        return
    logger.info("扣减知识库切片数 kb_id={} chunk_num={}", kb_id, chunk_num)
    Knowledgebase.objects.filter(id=kb_id).update(
        chunk_num=Greatest(F("chunk_num") - Value(chunk_num), Value(0)),
        update_date=timezone.now(),
    )


def _sync_es_available(kb_id: str, doc_id: str, available: int) -> None:
    """将文档可用状态同步到 Elasticsearch。

    失败时静默记录日志，不影响主流程。

    Args:
        kb_id: 知识库 ID（决定 ES 索引名）。
        doc_id: 文档 ID。
        available: 0=禁用，1=启用。
    """
    try:
        es_service.update_doc_available(kb_id, doc_id, available)
    except Exception as exc:
        logger.exception("文档可用状态同步到 ES 失败 kb_id={} doc_id={}", kb_id, doc_id)


def _cleanup_doc_es(doc: Document) -> None:
    """清除 Elasticsearch 中与文档相关的 chunk 数据。

    失败时静默忽略。

    Args:
        doc: Document 模型实例。
    """
    try:
        es_service.delete_doc_chunks(doc.kb_id, doc.id)
    except Exception as exc:
        logger.exception("文档 ES 切片清理失败 kb_id={} doc_id={}", doc.kb_id, doc.id)


def _cleanup_doc_es_by_id(kb_id: str, doc_id: str) -> None:
    """按文档 ID 清除 Elasticsearch 中与文档相关的 chunk 数据。"""
    try:
        es_service.delete_doc_chunks(kb_id, doc_id)
    except Exception as exc:
        logger.exception("按 ID 清理文档 ES 切片失败 kb_id={} doc_id={}", kb_id, doc_id)


def _validate_parser_type(doc: Document, parser_id: str) -> str | None:
    """校验文档类型与解析器的兼容性。

    Args:
        doc: Document 模型实例。
        parser_id: 目标解析器 ID。

    Returns:
        None 表示校验通过；字符串表示错误原因。
    """
    visual_types = {"jpg", "jpeg", "png", "gif", "bmp", "webp", "tiff", "svg"}
    ppt_types = {"ppt", "pptx", "pages"}
    ppt_pattern = re.compile(r"\.(ppt|pptx|pages)$", re.IGNORECASE)

    if doc.type in visual_types and parser_id != "picture":
        return "图片类型文档只能使用 picture 解析器。"

    file_type = (doc.type or "").strip().lower()
    if not file_type and doc.name:
        file_type = (get_file_extension(doc.name) or "").lower()
    is_ppt_family = file_type in ppt_types or bool(doc.name and ppt_pattern.search(doc.name))

    if is_ppt_family:
        if parser_id == "presentation":
            return None
        allowed = {p["method"] for p in get_parsers_by_file_type(file_type or "pptx")}
        if parser_id in allowed:
            return None
        allowed_hint = ", ".join(sorted(allowed)) or "mineru"
        return (
            f"PPT/PPTX/Pages 文件不支持解析器 {parser_id}，"
            f"请使用 presentation 或已映射的解析方法（如 {allowed_hint}）。"
        )

    return None


def _normalize_orderby(orderby: str) -> str:
    """兼容旧版响应字段名与本地模型字段名。"""
    aliases = {
        "create_time": "create_date",
        "update_time": "update_date",
    }
    return aliases.get(orderby, orderby)


def _parse_image_id(image_id: str) -> tuple[str, str]:
    """解析列表接口生成的 {bucket}-{object_name} 图片标识。"""
    if "-" not in image_id:
        raise ValueError("invalid image_id")
    bucket, name = image_id.rsplit("-", 1)
    if not bucket or not name:
        raise ValueError("invalid image_id")
    return minio_service.normalize_bucket(bucket), name


def _guess_content_type(filename: str, default: str = "application/octet-stream") -> str:
    """根据文件名猜测 Content-Type。

    Args:
        filename: 文件名（含扩展名）。

    Returns:
        MIME 类型字符串，猜测失败时返回 application/octet-stream。
    """
    content_type, _ = mimetypes.guess_type(filename)
    return content_type or default
