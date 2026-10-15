"""评测问题集接口。"""

from __future__ import annotations

import re
from typing import Any
from dataclasses import replace

from drf_spectacular.utils import extend_schema
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

from __001__rag.assistant.service import AssistantService
from __001__rag.models import EvaluationQuestion, EvaluationResult, Knowledgebase
from __001__rag.ops import request_tenant_id, request_user_id, require_role, write_audit
from __001__rag.utils import error_response, format_datetime, get_uuid, success_response
from __005__conversation.utils.service import _do_retrieval

from .serializers import (
    EvalQuestionIdSerializer,
    EvalQuestionListSerializer,
    EvalQuestionSaveSerializer,
    EvalResultListSerializer,
    EvalRunSerializer,
)


def _expected_hit_flag(expected: str, chunks: list, pages: list) -> str:
    """关键词命中：整句包含，或过半 token 出现在文本/页图元数据中。"""
    expected = (expected or "").strip()
    if not expected:
        return "0"
    parts: list[str] = []
    for chunk in chunks or []:
        if isinstance(chunk, dict):
            parts.append(str(chunk.get("content") or chunk.get("content_with_weight") or ""))
        else:
            parts.append(str(chunk))
    for page in pages or []:
        if isinstance(page, dict):
            parts.extend(str(page.get(key) or "") for key in ("content", "text", "caption", "ocr", "docnm_kwd", "image_id"))
        else:
            parts.append(str(page))
    blob = "\n".join(parts).lower()
    if expected.lower() in blob:
        return "1"
    tokens = [token for token in re.split(r"[\s,;，、|/]+", expected) if token]
    if not tokens:
        return "0"
    hits = sum(1 for token in tokens if token.lower() in blob)
    return "1" if hits >= max(1, (len(tokens) + 1) // 2) else "0"


def _eval_to_dict(row: EvaluationQuestion) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "kb_id": row.kb_id,
        "question": row.question,
        "expected_answer": row.expected_answer or "",
        "tags": row.tags or [],
        "status": row.status,
        "create_date": format_datetime(row.create_date),
        "update_date": format_datetime(row.update_date),
    }


def _result_to_dict(row: EvaluationResult) -> dict[str, Any]:
    return {
        "id": row.id,
        "tenant_id": row.tenant_id,
        "kb_id": row.kb_id,
        "question_id": row.question_id,
        "question": row.question,
        "expected_answer": row.expected_answer or "",
        "text_hit_count": row.text_hit_count,
        "vision_hit_count": row.vision_hit_count,
        "has_reference": row.has_reference,
        "expected_hit": row.expected_hit,
        "score": row.score,
        "detail": row.detail or {},
        "status": row.status,
        "error": row.error or "",
        "create_date": format_datetime(row.create_date),
    }


@extend_schema(tags=["evaluation"], summary="评测问题列表", responses={200: None})
@api_view(["GET"])
def question_list(request: Request) -> Response:
    ser = EvalQuestionListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or "default"
    qs = EvaluationQuestion.objects.filter(tenant_id=tenant_id).order_by("-create_date")
    if vd.get("kb_id"):
        qs = qs.filter(kb_id=vd["kb_id"])
    return success_response([_eval_to_dict(row) for row in qs[:300]])


@extend_schema(tags=["evaluation"], summary="新增或更新评测问题", request=EvalQuestionSaveSerializer, responses={200: None})
@api_view(["POST"])
def question_save(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    ser = EvalQuestionSaveSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    if not Knowledgebase.objects.filter(id=vd["kb_id"], tenant_id=tenant_id, status="1").exists():
        return error_response("知识库不存在或未启用。")
    row, _ = EvaluationQuestion.objects.get_or_create(id=vd.get("id") or get_uuid(), defaults={"tenant_id": tenant_id, "kb_id": vd["kb_id"]})
    row.tenant_id = tenant_id
    row.kb_id = vd["kb_id"]
    row.question = vd["question"].strip()
    row.expected_answer = vd.get("expected_answer") or ""
    row.tags = vd.get("tags") or []
    row.status = vd.get("status") or "1"
    row.save()
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="save", resource_type="evaluation_question", resource_id=row.id)
    return success_response(_eval_to_dict(row))


@extend_schema(tags=["evaluation"], summary="删除评测问题", request=EvalQuestionIdSerializer, responses={200: None})
@api_view(["POST"])
def question_rm(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    ser = EvalQuestionIdSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    row_id = ser.validated_data["id"]
    deleted, _ = EvaluationQuestion.objects.filter(id=row_id, tenant_id=request_tenant_id(request)).delete()
    write_audit(tenant_id=request_tenant_id(request), user_id=request_user_id(request), action="delete", resource_type="evaluation_question", resource_id=row_id)
    return success_response({"deleted": deleted})


@extend_schema(tags=["evaluation"], summary="运行评测问题集", request=EvalRunSerializer, responses={200: None})
@api_view(["POST"])
def run_eval(request: Request) -> Response:
    denied = require_role(request, "editor")
    if denied is not None:
        return denied
    ser = EvalRunSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    tenant_id = vd.get("tenant_id") or request_tenant_id(request)
    kb_id = vd["kb_id"]
    if not Knowledgebase.objects.filter(id=kb_id, tenant_id=tenant_id, status="1").exists():
        return error_response("知识库不存在或未启用。")
    questions = list(EvaluationQuestion.objects.filter(tenant_id=tenant_id, kb_id=kb_id, status="1").order_by("create_date"))
    if not questions:
        return error_response("当前知识库没有启用的评测问题。")

    assistant_cfg = replace(AssistantService.get_config("chat"), top_n=vd.get("top_n") or 6)
    results = []
    for q in questions:
        try:
            chunks, reference, doc_aggs = _do_retrieval(assistant_cfg, q.question, kb_ids_override=[kb_id])
            pages = reference.get("pages", []) if isinstance(reference, dict) else []
            expected_hit = _expected_hit_flag(q.expected_answer or "", chunks, pages)
            has_reference = "1" if chunks or pages else "0"
            score = 0.0
            if has_reference == "1":
                score += 0.6
            if expected_hit == "1":
                score += 0.4
            row = EvaluationResult.objects.create(
                id=get_uuid(),
                tenant_id=tenant_id,
                kb_id=kb_id,
                question_id=q.id,
                question=q.question,
                expected_answer=q.expected_answer or "",
                text_hit_count=len(chunks),
                vision_hit_count=len(pages),
                has_reference=has_reference,
                expected_hit=expected_hit,
                score=round(score, 2),
                detail={"doc_aggs": doc_aggs, "top_chunks": chunks[:3], "top_pages": pages[:3]},
                status="success",
            )
        except Exception as exc:
            row = EvaluationResult.objects.create(
                id=get_uuid(),
                tenant_id=tenant_id,
                kb_id=kb_id,
                question_id=q.id,
                question=q.question,
                expected_answer=q.expected_answer or "",
                status="failed",
                error=str(exc),
            )
        results.append(_result_to_dict(row))
    write_audit(tenant_id=tenant_id, user_id=request_user_id(request), action="run", resource_type="evaluation", resource_id=kb_id, detail={"count": len(results)})
    avg_score = round(sum(item["score"] for item in results) / len(results), 3)
    return success_response({"total": len(results), "avg_score": avg_score, "results": results})


@extend_schema(tags=["evaluation"], summary="评测结果列表", responses={200: None})
@api_view(["GET"])
def result_list(request: Request) -> Response:
    ser = EvalResultListSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))
    vd = ser.validated_data
    qs = EvaluationResult.objects.filter(tenant_id=vd.get("tenant_id") or "default").order_by("-create_date")
    if vd.get("kb_id"):
        qs = qs.filter(kb_id=vd["kb_id"])
    if vd.get("question_id"):
        qs = qs.filter(question_id=vd["question_id"])
    return success_response([_result_to_dict(row) for row in qs[:300]])
