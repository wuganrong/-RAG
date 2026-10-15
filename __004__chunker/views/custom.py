"""自定义切片（Custom Chunk）接口视图。"""

from __future__ import annotations

# 1. Python 标准库
import datetime
from typing import Any

# 2. 第三方库
import xxhash
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.keyword_extraction import create_keyword_extractor
from __001__rag.llm.service import LLMService
from __001__rag.models import Document, File, File2Document
from __001__rag.search import es_service
from __001__rag.storage import minio_service
from __001__rag.api.utils import doc_to_dict
from __001__rag.nlp.utils import build_token_metadata, token_string
from __001__rag.question_generate import create_question_generator
from __001__rag.utils import error_response, format_datetime, get_uuid, success_response

from ..serializers.custom import (
    CustomChunkCreateChunkSerializer,
    CustomChunkExtractKeywordsSerializer,
    CustomChunkExtractQuestionsSerializer,
    CustomChunkFileListSerializer,
    CustomChunkGetSerializer,
    CustomChunkListSerializer,
    CustomChunkRmSerializer,
    CustomChunkSetSerializer,
    CustomChunkUpdateDocidSerializer,
)

_CUSTOM_CHUNK_TAG = ["custom_chunk"]
_ALLOWED_FILE_EXTENSIONS = {"docx", "ppt", "pptx", "pdf", "xlsx", "xls"}


def _get_user_id(request: Request) -> str:
    """兼容前端 body/query 自动并入 user_id，以及后续接入认证的请求头。"""
    return (
        str(request.data.get("user_id") or "")
        or str(request.GET.get("user_id") or "")
        or request.META.get("HTTP_X_USER_ID", "")
    )


def _get_create_user_name(data: dict[str, Any], user_id: str) -> str:
    """yf-rag 暂无 User 表，优先使用前端传入的名称，否则用 user_id 兜底便于列表搜索。"""
    return str(data.get("create_user_name") or data.get("user_name") or user_id or "")


def _get_create_questions(data: dict[str, Any]) -> list[str]:
    """创建接口兼容旧版 questions 与 ES 字段 question_kwd。"""
    questions = data.get("question_kwd") or data.get("questions") or []
    return [str(item) for item in questions]


def _get_custom_kb_id() -> str:
    """获取自定义知识库 ID。"""
    return getattr(settings, "CUSTOM_KB_ID", "0")


@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="自定义切片列表查询",
    description="分页查询自定义切片列表，支持按标题、创建者姓名模糊搜索，按可用状态过滤。",
    request=CustomChunkListSerializer,
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_list(request: Request) -> Response:
    """POST /custom_chunk/list — 自定义切片列表查询。"""
    ser = CustomChunkListSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    page: int = vd.get("page", 1)
    size: int = vd.get("page_size", 30)
    chunk_title_kwd: str = vd.get("chunk_title_kwd", "")
    user_name: str = vd.get("user_name", "")
    available_int: int | None = vd.get("available_int")

    kb_id = _get_custom_kb_id()

    try:
        data = es_service.list_chunks(
            kb_id=kb_id,
            page=page,
            size=size,
            chunk_title_kwd=chunk_title_kwd,
            user_name=user_name,
            available_int=available_int,
        )
        return success_response(data)

    except Exception as e:
        error_msg = str(e)
        if "not_found" in error_msg or "NotFoundError" in type(e).__name__:
            return success_response({"total": 0, "chunks": [], "doc": {}})
        logger.exception("自定义切片列表查询失败")
        return error_response(f"查询失败: {error_msg}", code=500)


@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="创建自定义切片",
    description="创建新的自定义切片，包含内容分词、向量化并存储到 ES。",
    request=CustomChunkCreateChunkSerializer,
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_create_chunk(request: Request) -> Response:
    """POST /custom_chunk/create_chunk — 创建自定义切片。"""
    ser = CustomChunkCreateChunkSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    content_with_weight: str = vd["content_with_weight"]
    chunk_title_kwd: str = vd["chunk_title_kwd"]
    questions: list[str] = _get_create_questions(vd)
    keywords: list[str] = vd.get("important_kwd", [])
    available_int: int = vd.get("available_int", 1)
    tag_kwd: list[str] = vd.get("tag_kwd", [])
    user_id: str = _get_user_id(request)
    create_user_name = _get_create_user_name(vd, user_id)

    kb_id = _get_custom_kb_id()

    try:
        chunk_id = xxhash.xxh64(content_with_weight.encode("utf-8")).hexdigest()
        index_name = es_service.chunk_index_name(kb_id)

        token_fields = build_token_metadata(content_with_weight, chunk_title_kwd)

        now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now_ts = datetime.datetime.now().timestamp()

        doc: dict[str, Any] = {
            "id": chunk_id,
            "content_with_weight": content_with_weight,
            "important_kwd": keywords,
            "important_tks": token_string(" ".join(keywords)) if keywords else "",
            "question_kwd": questions,
            "question_tks": token_string("\n".join(questions)) if questions else "",
            "chunk_title_kwd": chunk_title_kwd,
            "create_time": now_str,
            "create_timestamp_flt": now_ts,
            "create_user_id": user_id,
            "create_user_name": create_user_name,
            "kb_id": [kb_id],
            "available_int": available_int,
            **token_fields,
        }

        if tag_kwd:
            doc["tag_kwd"] = tag_kwd

        vector = _generate_embedding(chunk_title_kwd, content_with_weight, questions)
        vector_field = None
        if vector is not None:
            vector_field = f"q_{len(vector)}_vec"
            doc[vector_field] = vector

        errors = es_service.create_chunks_to_index(index_name, kb_id, [doc])
        if errors:
            return error_response(f"创建切片失败: {errors}", code=500)

        return success_response({"chunk_id": chunk_id})

    except Exception:
        logger.exception("创建自定义切片失败")
        return error_response("创建切片失败", code=500)


def _generate_embedding(title: str, content: str, questions: list[str]) -> list[float] | None:
    """生成文本向量。"""
    try:
        model_name = getattr(settings, "EMBEDDING_MODEL_ID", None)
        texts_for_embedding = [title, content if not questions else "\n".join(questions)]
        embeddings = LLMService.embed(texts_for_embedding, model_name=model_name)

        if len(embeddings) >= 2:
            return [
                0.1 * title_value + 0.9 * body_value
                for title_value, body_value in zip(embeddings[0], embeddings[1], strict=False)
            ]

        return embeddings[0] if embeddings else None
    except Exception:
        logger.exception("生成向量失败")
        return None


@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="获取自定义切片详情",
    description="根据 chunk_id 获取单个切片的详细信息。",
    parameters=[
        OpenApiParameter("chunk_id", OpenApiTypes.STR, required=True, description="切片 ID"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def custom_chunk_get(request: Request) -> Response:
    """GET /custom_chunk/get?chunk_id=xxx — 获取切片详情。"""
    ser = CustomChunkGetSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    chunk_id: str = ser.validated_data["chunk_id"]
    kb_id = _get_custom_kb_id()

    try:
        source = es_service.get_chunk(kb_id, chunk_id)
        if source is None:
            return error_response("切片不存在", code=404)

        return success_response(source)

    except Exception as e:
        if "NotFoundError" in type(e).__name__ or "not_found" in str(e).lower():
            return error_response("切片不存在", code=404)
        logger.exception("获取自定义切片失败")
        return error_response(f"获取切片失败: {e}", code=500)


@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="更新自定义切片",
    description="更新切片内容、关键词、问题等字段，并重新生成向量。",
    request=CustomChunkSetSerializer,
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_set(request: Request) -> Response:
    """POST /custom_chunk/set — 更新切片。"""
    ser = CustomChunkSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    chunk_id: str = vd["chunk_id"]

    kb_id = _get_custom_kb_id()

    try:
        content = vd["content_with_weight"]
        title = vd["chunk_title_kwd"]
        doc: dict[str, Any] = {
            "id": chunk_id,
            "content_with_weight": content,
            "chunk_title_kwd": title,
            **build_token_metadata(content, title),
        }

        if "important_kwd" in vd:
            keywords = vd["important_kwd"]
            doc["important_kwd"] = keywords
            doc["important_tks"] = token_string(" ".join(keywords))

        if "question_kwd" in vd:
            questions = vd["question_kwd"]
            doc["question_kwd"] = questions
            doc["question_tks"] = token_string("\n".join(questions))

        if "tag_kwd" in vd:
            doc["tag_kwd"] = vd["tag_kwd"]

        if "available_int" in vd:
            doc["available_int"] = vd["available_int"]

        if "doc_id" in vd:
            doc["doc_id"] = vd["doc_id"]
            if "docnm_kwd" in vd:
                doc["docnm_kwd"] = vd["docnm_kwd"]
        else:
            doc["doc_id"] = ""
            doc["docnm_kwd"] = ""

        questions = vd.get("question_kwd", [])
        vector = _generate_embedding(title, content, questions)
        if vector is not None:
            doc[f"q_{len(vector)}_vec"] = vector

        if not es_service.update_chunk(kb_id, chunk_id, doc):
            return error_response("切片不存在", code=404)

        return success_response(True)

    except Exception:
        logger.exception("更新自定义切片失败")
        return error_response("更新切片失败", code=500)


@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="删除自定义切片",
    description="从 ES 中删除指定的切片。",
    request=CustomChunkRmSerializer,
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_rm(request: Request) -> Response:
    """POST /custom_chunk/rm — 删除切片。"""
    ser = CustomChunkRmSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    chunk_id: str = ser.validated_data["chunk_id"]
    kb_id = _get_custom_kb_id()

    try:
        es_service.delete_chunk(kb_id, chunk_id)
        return success_response(True)

    except Exception as e:
        if "NotFoundError" in type(e).__name__ or "not_found" in str(e).lower():
            return success_response(True)
        logger.exception("删除自定义切片失败")
        return error_response(f"删除切片失败: {e}", code=500)


@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="更新切片关联文档 ID",
    description="批量更新指定切片的关联文档 ID 和文档名称。",
    request=CustomChunkUpdateDocidSerializer,
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_update_docid(request: Request) -> Response:
    """POST /custom_chunk/update_docid — 更新切片关联文档 ID。"""
    ser = CustomChunkUpdateDocidSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    chunk_ids: list[str] = vd["chunk_ids"]
    doc_id: str = vd["doc_id"]

    try:
        doc = Document.objects.get(id=doc_id)
        doc_name = doc.name
    except Document.DoesNotExist:
        return error_response("文档不存在", code=404)

    kb_id = _get_custom_kb_id()

    try:
        if not es_service.update_chunks_doc(kb_id, chunk_ids, doc_id, doc_name):
            return error_response("索引更新失败", code=500)

        return success_response(True)

    except Exception:
        logger.exception("更新切片关联文档失败")
        return error_response("更新文档关联失败", code=500)


@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="抽取关键词",
    description="使用 LLM 从文本内容中抽取关键词。",
    request=CustomChunkExtractKeywordsSerializer,
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_extract_keywords(request: Request) -> Response:
    """POST /custom_chunk/extract_keywords — 抽取关键词。"""
    ser = CustomChunkExtractKeywordsSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    content: str = vd["content"]
    topn: int = vd.get("topn", 15)

    try:
        keyword_list = _extract_keywords_with_llm(content, topn)
        if not keyword_list:
            return success_response({"keywords": []}, msg="未抽取到关键词")
        return success_response({"keywords": keyword_list})

    except Exception:
        logger.exception("抽取关键词失败")
        return error_response("关键词抽取失败", code=500)


def _extract_keywords_with_llm(content: str, topn: int) -> list[str]:
    """使用 LLM 抽取关键词。"""
    extractor = create_keyword_extractor()
    return extractor.extract(content, topn=topn)



@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="抽取问题",
    description="使用 LLM 从文本内容中自动生成问题。",
    request=CustomChunkExtractQuestionsSerializer,
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_extract_questions(request: Request) -> Response:
    """POST /custom_chunk/extract_questions — 抽取问题。"""
    ser = CustomChunkExtractQuestionsSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    content: str = vd["content"]
    topn: int = vd.get("topn", 10)

    try:
        questions = create_question_generator().generate(content, max_questions=topn)
        if not questions:
            return success_response({"questions": []}, msg="未生成问题")
        return success_response({"questions": questions})

    except Exception:
        logger.exception("抽取问题失败")
        return error_response("问题生成失败", code=500)



@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="上传文档",
    description="上传文档到自定义切片知识库，支持 docx, ppt, pptx, pdf, xlsx, xls 格式。",
    request={
        "multipart/form-data": {
            "type": "object",
            "properties": {
                "file": {"type": "string", "format": "binary", "description": "上传的文档文件"},
                "user_id": {"type": "string", "description": "用户 ID（可选）"},
            },
            "required": ["file"],
        }
    },
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_upload(request: Request) -> Response:
    """POST /custom_chunk/upload — 上传文档。"""

    if "file" not in request.FILES:
        return error_response("没有上传文件", code=400)

    file_obj = request.FILES["file"]
    if not file_obj.name:
        return error_response("文件名为空", code=400)

    kb_id = _get_custom_kb_id()
    user_id = request.POST.get("user_id", "") or request.GET.get("user_id", "") or request.META.get("HTTP_X_USER_ID", "")

    file_ext = file_obj.name.split(".")[-1].lower() if "." in file_obj.name else ""
    if file_ext not in _ALLOWED_FILE_EXTENSIONS:
        return error_response(
            f"不支持的文件类型: {file_ext}，仅允许: {', '.join(_ALLOWED_FILE_EXTENSIONS)}",
            code=400,
        )

    try:
        doc_id = get_uuid()
        file_id = get_uuid()
        f2d_id = get_uuid()
        blob = file_obj.read()
        location = f"{doc_id}.{file_ext}"
        content_type = file_obj.content_type or "application/octet-stream"

        minio_service.put(bucket=kb_id, name=location, data=blob, content_type=content_type)

        with transaction.atomic():
            doc = Document.objects.create(
                id=doc_id,
                kb_id=kb_id,
                parser_id="",
                chunker_id="",
                chunker_config={},
                source_type="custom",
                type=file_ext,
                created_by=user_id,
                name=file_obj.name,
                location=location,
                size=len(blob),
                status="1",
            )
            File.objects.create(
                id=file_id,
                name=file_obj.name,
                parent_id=minio_service.normalize_bucket(kb_id),
                location=location,
                size=len(blob),
                type=file_ext,
                source_type="custom",
                created_by=user_id,
            )
            File2Document.objects.create(
                id=f2d_id,
                file_id=file_id,
                document_id=doc_id,
            )

        return success_response(doc_to_dict(doc))

    except Exception:
        logger.exception("自定义切片上传文档失败")
        return error_response("上传失败", code=500)


@extend_schema(
    tags=_CUSTOM_CHUNK_TAG,
    summary="自定义切片文件列表",
    description="分页查询自定义切片知识库中的文件列表。",
    request=CustomChunkFileListSerializer,
    responses={200: None},
)
@api_view(["POST"])
def custom_chunk_file_list(request: Request) -> Response:
    """POST /custom_chunk/file_list — 文件列表。"""
    ser = CustomChunkFileListSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    keywords: str = vd.get("keywords", "")
    current: int = vd.get("page", 1)
    size: int = vd.get("page_size", 15)

    kb_id = _get_custom_kb_id()

    try:
        qs = Document.objects.filter(kb_id=kb_id)
        if keywords:
            qs = qs.filter(name__icontains=keywords)

        total = qs.count()
        offset = (current - 1) * size
        records = list(qs.order_by("-create_date")[offset: offset + size])

        file_list: list[dict[str, Any]] = []
        for doc in records:
            file_list.append({
                "id": doc.id,
                "kb_id": doc.kb_id,
                "name": doc.name,
                "size": doc.size,
                "type": doc.type,
                "create_date": format_datetime(doc.create_date),
            })

        return success_response({
            "total": total,
            "records": file_list,
            "page": current,
            "page_size": size,
        })

    except Exception:
        logger.exception("自定义切片文件列表查询失败")
        return error_response("查询文件列表失败", code=500)
