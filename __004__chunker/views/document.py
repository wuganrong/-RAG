"""文本切片（Chunk）接口视图。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.core.paginator import EmptyPage, Paginator
from django.db import transaction
from django.db.models import F, Value
from django.db.models.functions import Greatest
from django.utils import timezone
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.intent.base import IntentResult
from __001__rag.intent.service import IntentService
from __001__rag.llm.service import LLMService
from __001__rag.models import ChunkMethod, Document, Knowledgebase
from __001__rag.search import es_service
from __001__rag.api.utils import doc_to_dict
from __001__rag.chunk.utils import (
    build_chunk_create_doc,
    build_chunk_update_doc,
    build_query_embedding,
    format_chunk_for_response,
    format_doc_aggs,
    strip_chunk_internal_fields,
)
from __001__rag.utils import error_response, success_response

from ..serializers.document import (
    ChunkCreateSerializer,
    ChunkGetSerializer,
    ChunkMethodDetailedResponseSerializer,
    ChunkMethodResponseSerializer,
    ChunkListResponseSerializer,
    ChunkListSerializer,
    ChunkRetrievalResponseSerializer,
    ChunkRetrievalSerializer,
    ChunkRmSerializer,
    ChunkSetSerializer,
    ChunkSwitchSerializer,
    GenericChunkResponseSerializer,
)

_CHUNK_TAG = ["chunk"]


@extend_schema(
    tags=_CHUNK_TAG,
    summary="获取文档方法",
    description=(
        "返回当前数据库配置的文档提取或切分方法。\n\n"
        "- 默认（不传 detail）：返回 `method:显示名` 逗号分隔字符串（兼容旧版）。\n"
        "- `detail=1`：返回结构化 JSON 列表，每项含 `config_schema`，供前端动态渲染表单。"
    ),
    parameters=[
        OpenApiParameter(
            "method_type",
            OpenApiTypes.STR,
            required=False,
            description="方法类型，chunker=切分方法，parser=文档提取方法；默认 chunker",
        ),
        OpenApiParameter(
            "detail",
            OpenApiTypes.STR,
            required=False,
            description="详细模式。传 1 返回含 config_schema 的结构化列表；不传则返回兼容旧版的逗号字符串",
        ),
    ],
    responses={200: ChunkMethodResponseSerializer},
)
@api_view(["GET"])
def chunk_methods(request: Request) -> Response:
    """GET /chunk/methods — 获取文档提取或切分方法列表。"""
    method_error = _ensure_method(request, "GET")
    if method_error:
        return method_error

    method_type = str(request.GET.get("method_type") or "chunker").strip().lower()
    if method_type not in {"chunker", "parser"}:
        return error_response("method_type 仅支持 chunker 或 parser")

    detail = str(request.GET.get("detail") or "").strip()
    try:
        qs = (
            ChunkMethod.objects.filter(method_type=method_type, status="1")
            .order_by("method")
        )
        if detail == "1":
            data = [
                {
                    "method": m.method,
                    "display_name": m.display_name or _default_method_label(m.method),
                    "method_type": m.method_type,
                    "config_schema": m.config_schema or {},
                }
                for m in qs
            ]
        else:
            data = ",".join(
                f"{m.method}:{m.display_name or _default_method_label(m.method)}"
                for m in qs
            )
        return success_response(data)
    except Exception:
        logger.exception("获取切片方法失败")
        return error_response("获取切片方法失败", code=500)


@extend_schema(
    tags=_CHUNK_TAG,
    summary="分页查询切片列表",
    description="按文档 ID 分页查询切片，支持关键词和可用状态过滤。",
    request=ChunkListSerializer,
    responses={200: ChunkListResponseSerializer},
)
@api_view(["POST"])
def chunk_list(request: Request) -> Response:
    """POST /chunk/list — 分页查询切片列表。"""
    method_error = _ensure_method(request, "POST")
    if method_error:
        return method_error

    ser = ChunkListSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    try:
        doc = _get_document(ser.validated_data["doc_id"])
        result = es_service.list_document_chunks(
            kb_id=doc.kb_id,
            doc_id=doc.id,
            page=ser.validated_data["page"],
            size=ser.validated_data["size"],
            keywords=ser.validated_data["keywords"],
            available_int=ser.validated_data.get("available_int"),
        )
    except Document.DoesNotExist:
        return error_response("Document not found!", code=404)
    except Exception:
        logger.exception("查询文档切片失败 doc_id={}", ser.validated_data["doc_id"])
        return error_response("查询切片失败", code=500)

    chunks = _format_chunks(result.chunks, result.highlights)
    return success_response({"total": result.total, "chunks": chunks, "doc": doc_to_dict(doc)})


@extend_schema(
    tags=_CHUNK_TAG,
    summary="启用/停用切片",
    description="批量更新切片 available_int 状态。",
    request=ChunkSwitchSerializer,
    responses={200: GenericChunkResponseSerializer},
)
@api_view(["POST"])
def chunk_switch(request: Request) -> Response:
    """POST /chunk/switch — 启用/停用切片。"""
    method_error = _ensure_method(request, "POST")
    if method_error:
        return method_error

    ser = ChunkSwitchSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    try:
        doc = _get_document(ser.validated_data["doc_id"])
        ok = es_service.update_chunks(
            doc.kb_id,
            ser.validated_data["chunk_ids"],
            {"available_int": int(ser.validated_data["available_int"])},
        )
    except Document.DoesNotExist:
        return error_response("Document not found!", code=404)
    except Exception:
        logger.exception("chunk_switch 更新切片状态失败 doc_id={}", ser.validated_data["doc_id"])
        return error_response("更新切片状态失败", code=500)

    if not ok:
        return error_response("Index updating failure", code=500)
    return success_response(True)


@extend_schema(
    tags=_CHUNK_TAG,
    summary="删除切片",
    description="批量删除指定文档下的切片，并同步扣减文档和知识库 chunk 计数。",
    request=ChunkRmSerializer,
    responses={200: GenericChunkResponseSerializer},
)
@api_view(["POST"])
def chunk_rm(request: Request) -> Response:
    """POST /chunk/rm — 删除切片。"""
    method_error = _ensure_method(request, "POST")
    if method_error:
        return method_error

    ser = ChunkRmSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    try:
        doc = _get_document(ser.validated_data["doc_id"])
        deleted_count = es_service.delete_chunks(doc.kb_id, ser.validated_data["chunk_ids"])
        _decrement_chunk_count(doc.id, doc.kb_id, deleted_count)
    except Document.DoesNotExist:
        return error_response("Document not found!", code=404)
    except Exception:
        logger.exception("chunk_rm 删除切片失败 doc_id={}", ser.validated_data["doc_id"])
        return error_response("删除切片失败", code=500)

    return success_response(True)


@extend_schema(
    tags=_CHUNK_TAG,
    summary="创建切片",
    description="为指定文档创建一条手工切片，写入 ES 并同步文档/知识库 chunk 计数。",
    request=ChunkCreateSerializer,
    responses={200: GenericChunkResponseSerializer},
)
@api_view(["POST"])
def chunk_create(request: Request) -> Response:
    """POST /chunk/create — 创建切片。"""
    method_error = _ensure_method(request, "POST")
    if method_error:
        return method_error

    ser = ChunkCreateSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    try:
        chunk_id = _create_chunk(ser.validated_data)
    except Document.DoesNotExist:
        return error_response("Document not found!", code=404)
    except Exception:
        logger.exception("chunk_create 创建切片失败 doc_id={}", ser.validated_data["doc_id"])
        return error_response("创建切片失败", code=500)

    return success_response({"chunk_id": chunk_id})


@extend_schema(
    tags=_CHUNK_TAG,
    summary="获取单条切片",
    description="按 chunk_id 获取切片详情。无认证接口需传入 kb_id 或 doc_id 辅助定位索引。",
    parameters=[
        OpenApiParameter("chunk_id", OpenApiTypes.STR, required=True, description="切片 ID"),
        OpenApiParameter("doc_id", OpenApiTypes.STR, required=False, description="文档 ID"),
        OpenApiParameter("kb_id", OpenApiTypes.STR, required=False, description="知识库 ID"),
    ],
    responses={200: GenericChunkResponseSerializer},
)
@api_view(["GET"])
def chunk_get(request: Request) -> Response:
    """GET /chunk/get — 获取单条切片。"""
    method_error = _ensure_method(request, "GET")
    if method_error:
        return method_error

    ser = ChunkGetSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    try:
        kb_id = _resolve_kb_id(ser.validated_data)
        if kb_id:
            source = es_service.get_chunk(kb_id, ser.validated_data["chunk_id"])
        else:
            source = es_service.find_chunk(ser.validated_data["chunk_id"])
    except Document.DoesNotExist:
        return error_response("Document not found!", code=404)
    except ValueError as exc:
        return error_response(str(exc))
    except Exception:
        logger.exception("chunk_get 获取切片失败 chunk_id={}", ser.validated_data["chunk_id"])
        return error_response("获取切片失败", code=500)

    if source is None:
        return error_response("Chunk not found!", code=404)
    return success_response(strip_chunk_internal_fields(source))


@extend_schema(
    tags=_CHUNK_TAG,
    summary="更新切片",
    description="更新切片内容、关键词、问题、标签和可用状态，并重新生成向量。",
    request=ChunkSetSerializer,
    responses={200: GenericChunkResponseSerializer},
)
@api_view(["POST"])
def chunk_set(request: Request) -> Response:
    """POST /chunk/set — 更新切片。"""
    method_error = _ensure_method(request, "POST")
    if method_error:
        return method_error

    ser = ChunkSetSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    try:
        doc = _get_document(ser.validated_data["doc_id"])
        update_doc = _build_update_doc(doc.name or "", ser.validated_data)
        ok = es_service.update_chunk(doc.kb_id, ser.validated_data["chunk_id"], update_doc)
    except Document.DoesNotExist:
        return error_response("Document not found!", code=404)
    except Exception:
        logger.exception("chunk_set 更新切片失败 chunk_id={}", ser.validated_data["chunk_id"])
        return error_response("更新切片失败", code=500)

    if not ok:
        return error_response("Chunk not found!", code=404)
    return success_response(True)


@extend_schema(
    tags=_CHUNK_TAG,
    summary="召回测试",
    description="基于当前项目 ES/LLM 能力执行兼容版知识库召回测试。",
    request=ChunkRetrievalSerializer,
    responses={200: ChunkRetrievalResponseSerializer},
)
@api_view(["POST"])
def chunk_retrieval_test(request: Request) -> Response:
    """POST /chunk/retrieval_test — 召回测试。"""
    return _retrieval_response(request, require_kb=True, include_questions=False)


@extend_schema(
    tags=_CHUNK_TAG,
    summary="知识库检索",
    description="先执行意图识别确定目标知识库，再混合检索，可选重排序，返回全量分页结果。",
    request=ChunkRetrievalSerializer,
    responses={200: ChunkRetrievalResponseSerializer},
)
@api_view(["POST"])
def chunk_retrieval_chunks(request: Request) -> Response:
    """POST /chunk/retrieval_chunks — 知识库检索（意图识别 + 混合检索 + 重排序）。"""
    method_error = _ensure_method(request, "POST")
    if method_error:
        return method_error

    ser = ChunkRetrievalSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    data = ser.validated_data
    question: str = data["question"]

    # Step 1: 确定检索的 kb_ids（来自请求 → 意图识别 → 全库兜底）
    kb_ids: list[str] = list(data.get("kb_id") or [])
    intent_name: str | None = None
    actual_question: str = question

    if not kb_ids:
        intent_result = _recognize_intent(question)
        intent_name = intent_result.intent_name
        actual_question = intent_result.actual_question or question
        kb_ids = list(intent_result.kb_ids)
        logger.info(
            "知识库检索：意图识别完成 intent={} matched_kb_count={} actual_question_len={}",
            intent_name, len(kb_ids), len(actual_question),
        )
        if not kb_ids:
            kb_ids = _get_all_active_kb_ids()
            logger.info("知识库检索：意图未匹配，回退到全库检索 kb_count={}", len(kb_ids))

    if not kb_ids:
        return success_response({
            "chunks": [], "labels": None, "total": 0,
            "doc_aggs": [], "questions": [actual_question],
        })

    # Step 2: 检索 + 重排序（默认启用；rerank_id 为空时使用系统默认重排模型）
    rerank_id = (data.get("rerank_id") or "").strip()

    try:
        payload = _retrieve_and_rerank(data, kb_ids, actual_question, rerank_id)
    except Exception:
        logger.exception("知识库检索失败")
        return error_response("检索失败", code=500)

    payload["questions"] = [actual_question]
    if intent_name:
        payload["intent_name"] = intent_name
    return success_response(payload)


def _ensure_method(request: Request, method: str) -> Response | None:
    if request.method != method:
        return error_response(f"Method '{request.method}' not allowed", code=405)
    return None


def _default_method_label(method: str) -> str:
    return " ".join(part.capitalize() for part in method.split("_") if part) or method


def _get_document(doc_id: str) -> Document:
    return Document.objects.get(id=doc_id)


def _resolve_kb_id(data: dict[str, Any]) -> str:
    kb_id = data.get("kb_id") or ""
    if kb_id:
        return kb_id
    doc_id = data.get("doc_id") or ""
    if not doc_id:
        return ""
    return _get_document(doc_id).kb_id


def _format_chunks(chunks: list[dict[str, Any]], highlights: dict[str, Any]) -> list[dict[str, Any]]:
    formatted = []
    for chunk in chunks:
        chunk_id = str(chunk.get("id", ""))
        highlight = _first_highlight(highlights.get(chunk_id))
        formatted.append(format_chunk_for_response(chunk, highlight=highlight))
    return formatted


def _first_highlight(value: Any) -> str | None:
    if isinstance(value, dict):
        values = value.get("content_with_weight")
        if isinstance(values, list) and values:
            return str(values[0])
    if isinstance(value, list) and value:
        return str(value[0])
    return None


@transaction.atomic
def _create_chunk(data: dict[str, Any]) -> str:
    doc = _get_document(data["doc_id"])
    es_doc, token_count = build_chunk_create_doc(
        doc_id=doc.id,
        doc_name=doc.name or "",
        kb_id=doc.kb_id,
        content=data["content_with_weight"],
        important_kwd=data.get("important_kwd", []),
        question_kwd=data.get("question_kwd", []),
        tag_kwd=data.get("tag_kwd", []),
        available_int=int(data.get("available_int", 1)),
    )
    errors = es_service.create_chunk(doc.kb_id, es_doc)
    if errors:
        raise RuntimeError(f"Index updating failure: {errors}")
    _increment_chunk_count(doc.id, doc.kb_id, token_count)
    return str(es_doc["id"])


def _build_update_doc(doc_name: str, data: dict[str, Any]) -> dict[str, Any]:
    return build_chunk_update_doc(
        doc_name=doc_name,
        content=data["content_with_weight"],
        important_kwd=data.get("important_kwd"),
        question_kwd=data.get("question_kwd"),
        tag_kwd=data.get("tag_kwd"),
        available_int=data.get("available_int"),
    )


def _increment_chunk_count(doc_id: str, kb_id: str, token_count: int) -> None:
    now = timezone.now()
    Document.objects.filter(id=doc_id).update(
        chunk_num=F("chunk_num") + 1,
        token_num=F("token_num") + token_count,
        update_date=now,
    )
    Knowledgebase.objects.filter(id=kb_id).update(chunk_num=F("chunk_num") + 1, update_date=now)


def _decrement_chunk_count(doc_id: str, kb_id: str, count: int) -> None:
    if count <= 0:
        return
    now = timezone.now()
    Document.objects.filter(id=doc_id).update(
        chunk_num=Greatest(F("chunk_num") - count, Value(0)),
        update_date=now,
    )
    Knowledgebase.objects.filter(id=kb_id).update(
        chunk_num=Greatest(F("chunk_num") - count, Value(0)),
        update_date=now,
    )


def _retrieval_response(request: Request, *, require_kb: bool, include_questions: bool) -> Response:
    method_error = _ensure_method(request, "POST")
    if method_error:
        return method_error

    ser = ChunkRetrievalSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    data = ser.validated_data
    kb_ids = data.get("kb_id", [])
    if require_kb and not kb_ids:
        return error_response("kb_id is required")
    if not kb_ids:
        return success_response(_empty_retrieval_result(include_questions, data["question"]))

    try:
        payload = _retrieve(data)
    except Exception:
        logger.exception("chunk retrieval 检索失败")
        return error_response("检索失败", code=500)

    if include_questions:
        payload["questions"] = [data["question"]]
    return success_response(payload)


def _empty_retrieval_result(include_questions: bool, question: str) -> dict[str, Any]:
    payload: dict[str, Any] = {"chunks": [], "labels": None, "total": 0, "doc_aggs": []}
    if include_questions:
        payload["questions"] = [question]
    return payload


def _retrieve(
    data: dict[str, Any],
    *,
    kb_ids: list[str] | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    """执行混合检索并返回格式化结果。

    kb_ids / question 未传入时从 data 中取值，以保持对 retrieval_test 的向后兼容。
    """
    effective_kb_ids: list[str] = kb_ids if kb_ids is not None else list(data.get("kb_id") or [])
    effective_question: str = question if question is not None else data["question"]

    embedding = build_query_embedding(effective_question)
    result = es_service.retrieve_chunks(
        kb_ids=effective_kb_ids,
        question=effective_question,
        embedding=embedding,
        page=data["page"],
        size=data["size"],
        top_k=data["top_k"],
        similarity_threshold=data["similarity_threshold"],
        vector_similarity_weight=data["vector_similarity_weight"],
        doc_ids=data.get("doc_ids", []),
        highlight=data.get("highlight", False),
    )
    chunks = [
        format_chunk_for_response(
            chunk,
            highlight=_first_highlight(result.highlights.get(str(chunk.get("id", "")))),
            include_prefix=True,
        )
        for chunk in result.chunks
    ]
    return {
        "chunks": chunks,
        "labels": None,
        "total": result.total,
        "doc_aggs": format_doc_aggs(result.aggregations),
    }


def _recognize_intent(question: str) -> IntentResult:
    """调用意图识别服务；任何异常均返回 fallback 结果，不中断检索主流程。"""
    try:
        return IntentService.recognize(question)
    except Exception:
        logger.exception("意图识别异常，使用 fallback")
        return IntentResult(actual_question=question)


def _get_all_active_kb_ids() -> list[str]:
    """返回全部 status='1' 知识库的 ID 列表。"""
    return list(Knowledgebase.objects.filter(status="1").values_list("id", flat=True))


def _retrieve_and_rerank(
    data: dict[str, Any],
    kb_ids: list[str],
    question: str,
    rerank_id: str,
) -> dict[str, Any]:
    """先拉取 top_k 候选集，再用重排模型打分排序，最后手动分页返回。

    重排失败时自动降级为原始排序结果，不向上抛出异常。
    """
    top_k: int = data["top_k"]
    page: int = data["page"]
    size: int = data["size"]

    embedding = build_query_embedding(question)
    result = es_service.retrieve_chunks(
        kb_ids=kb_ids,
        question=question,
        embedding=embedding,
        page=1,
        size=top_k,
        top_k=top_k,
        similarity_threshold=data["similarity_threshold"],
        vector_similarity_weight=data["vector_similarity_weight"],
        doc_ids=data.get("doc_ids", []),
        highlight=data.get("highlight", False),
    )

    all_chunks: list[dict[str, Any]] = list(result.chunks)
    if not all_chunks:
        return {
            "chunks": [], "labels": None, "total": 0,
            "doc_aggs": format_doc_aggs(result.aggregations),
        }

    # 重排序
    reranked_chunks = _apply_rerank(question, all_chunks, rerank_id)

    # Paginator 分页
    paginator = Paginator(reranked_chunks, size)
    try:
        page_obj = paginator.page(page)
    except EmptyPage:
        page_obj = paginator.page(paginator.num_pages)

    chunks = [
        format_chunk_for_response(
            chunk,
            highlight=_first_highlight(result.highlights.get(str(chunk.get("id", "")))),
            include_prefix=True,
        )
        for chunk in page_obj.object_list
    ]
    return {
        "chunks": chunks,
        "labels": None,
        "total": paginator.count,
        "doc_aggs": format_doc_aggs(result.aggregations),
    }


def _apply_rerank(
    question: str,
    chunks: list[dict[str, Any]],
    rerank_id: str,
) -> list[dict[str, Any]]:
    """调用重排模型对候选切片打分，失败时降级为原始顺序。

    返回按重排分数降序排列的切片列表（每条带更新后的 similarity 字段）。
    """
    documents = [c.get("content_with_weight", "") for c in chunks]
    try:
        ranked: list[tuple[int, float]] = LLMService.rerank(
            query=question,
            documents=documents,
            model_name=rerank_id or None,
            topn=len(documents),
        )
        reranked: list[dict[str, Any]] = []
        for orig_idx, score in ranked:
            if 0 <= orig_idx < len(chunks):
                chunk = dict(chunks[orig_idx])
                chunk["similarity"] = float(score)
                reranked.append(chunk)
        logger.info("重排序完成 input={} output={}", len(chunks), len(reranked))
        return reranked
    except Exception:
        logger.exception("重排序失败，降级为原始顺序")
        return chunks