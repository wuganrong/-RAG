"""检索方法配置接口视图。"""

from __future__ import annotations

# 1. Python 标准库
from dataclasses import replace

# 2. 第三方库
from drf_spectacular.utils import extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
from __001__rag.assistant.service import AssistantService
from __001__rag.models import AssistantConfig, Knowledgebase, PromptConfig
from __001__rag.utils import get_uuid
from __001__rag.utils import success_response
from __001__rag.utils import error_response
from __005__conversation.utils.service import chunks_format, _do_retrieval
from __007__rag_conf.utils import list_retrieval_methods

_RETRIEVAL_TAG = ["retrieval"]
_STRATEGY_FIELDS = {
    "retrieval_method",
    "similarity_threshold",
    "vector_similarity_weight",
    "top_n",
    "top_k",
    "rerank_id",
    "memory_rounds",
}


def _strategy_payload(config) -> dict:
    return {
        "id": getattr(config, "id", ""),
        "assistant_key": getattr(config, "assistant_key", "chat"),
        "retrieval_method": getattr(config, "retrieval_method", "") or "hybrid",
        "similarity_threshold": float(getattr(config, "similarity_threshold", 0.2) or 0),
        "vector_similarity_weight": float(getattr(config, "vector_similarity_weight", 0.3) or 0),
        "top_n": int(getattr(config, "top_n", 6) or 6),
        "top_k": int(getattr(config, "top_k", 1024) or 1024),
        "rerank_id": getattr(config, "rerank_id", "") or "",
        "memory_rounds": int(getattr(config, "memory_rounds", 5) or 5),
        "llm_setting": getattr(config, "llm_setting", {}) or {},
        "extra_params": getattr(config, "extra_params", {}) or {},
    }


def _get_or_create_chat_assistant() -> AssistantConfig:
    config = AssistantConfig.objects.filter(assistant_key="chat").first()
    if config:
        return config
    prompt = PromptConfig.objects.filter(config_key="chat", status="1").first()
    if prompt is None:
        prompt = PromptConfig.objects.create(config_key="chat", section_name="默认问答")
    return AssistantConfig.objects.create(
        id=get_uuid(),
        assistant_key="chat",
        assistant_type="conversation",
        assistant_name="默认问答助手",
        prompt_config_key=prompt.config_key,
        retrieval_method="hybrid",
        top_n=6,
        top_k=1024,
        similarity_threshold=0.2,
        vector_similarity_weight=0.3,
        status="1",
    )


def _normalize_strategy_value(field: str, value):
    if field in {"top_n", "top_k", "memory_rounds"}:
        return max(0, int(value or 0))
    if field in {"similarity_threshold", "vector_similarity_weight"}:
        return max(0.0, min(float(value or 0), 1.0))
    return value


def _build_debug_result(question: str, kb_ids: list[str], tenant_id: str, top_n: int | None = None, mode: str | None = None) -> dict:
    assistant_cfg = AssistantService.get_config("chat")
    if top_n is not None:
        assistant_cfg = replace(assistant_cfg, top_n=max(1, min(int(top_n or assistant_cfg.top_n), 20)))
    chunks, reference, doc_aggs = _do_retrieval(
        assistant_cfg,
        question,
        kb_ids_override=kb_ids,
        rag_mode_override=mode,
    )
    text_refs = chunks_format({"chunks": chunks}) if chunks else []
    pages = reference.get("pages", []) if isinstance(reference, dict) else []
    kb = Knowledgebase.objects.filter(id=kb_ids[0], tenant_id=tenant_id).first()
    actual_mode = mode or (getattr(kb, "rag_mode", "text") if kb else "text")
    return {
        "question": question,
        "tenant_id": tenant_id,
        "kb_ids": kb_ids,
        "rag_mode": actual_mode,
        "text_chunks": text_refs,
        "vision_pages": pages,
        "doc_aggs": doc_aggs,
        "context_preview": "\n\n".join((item.get("content") or item.get("content_with_weight") or "")[:800] for item in text_refs[:5]),
        "summary": {
            "text_hit_count": len(text_refs),
            "vision_hit_count": len(pages),
            "doc_count": len(doc_aggs),
            "has_reference": bool(text_refs or pages),
        },
    }


@extend_schema(
    tags=_RETRIEVAL_TAG,
    summary="检索方法选项列表",
    description=(
        "查询所有启用状态（status=1）的检索方法配置，按创建时间升序返回选项列表。"
        "字段 label 为前端显示名称（display_name），value 为方法标识（method），"
        "可直接用于前端下拉选项渲染。"
    ),
    responses={200: None},
)
@api_view(["GET"])
def retrieval_method_list(request: Request) -> Response:
    """GET /retrieval/list — 检索方法选项列表。"""
    items = list_retrieval_methods()
    logger.info("查询检索方法列表成功，共 {} 条", len(items))
    return success_response(items)


@extend_schema(tags=_RETRIEVAL_TAG, summary="获取默认问答检索策略", responses={200: None})
@api_view(["GET"])
def retrieval_strategy_get(request: Request) -> Response:
    """GET /retrieval/strategy/get — 获取默认 chat 助手的检索策略。"""
    config = _get_or_create_chat_assistant()
    methods = list_retrieval_methods()
    return success_response({"strategy": _strategy_payload(config), "methods": methods})


@extend_schema(tags=_RETRIEVAL_TAG, summary="保存默认问答检索策略", responses={200: None})
@api_view(["POST"])
def retrieval_strategy_save(request: Request) -> Response:
    """POST /retrieval/strategy/save — 保存默认 chat 助手的检索策略。"""
    data = request.data if isinstance(request.data, dict) else {}
    config = _get_or_create_chat_assistant()
    for field in _STRATEGY_FIELDS:
        if field in data:
            setattr(config, field, _normalize_strategy_value(field, data.get(field)))
    config.save()
    return success_response({"strategy": _strategy_payload(config)})


@extend_schema(tags=_RETRIEVAL_TAG, summary="检索调试", responses={200: None})
@api_view(["POST"])
def retrieval_debug(request: Request) -> Response:
    """POST /retrieval/debug — 展示一次真实检索的文本召回、视觉召回和聚合依据。"""
    data = request.data if isinstance(request.data, dict) else {}
    question = str(data.get("question") or "").strip()
    kb_ids = data.get("kb_ids") or []
    tenant_id = str(data.get("tenant_id") or "default").strip() or "default"
    if isinstance(kb_ids, str):
        kb_ids = [item.strip() for item in kb_ids.split(",") if item.strip()]
    if not question:
        return error_response("question 不能为空。")
    if not kb_ids:
        return error_response("kb_ids 不能为空。")
    valid_ids = list(Knowledgebase.objects.filter(id__in=kb_ids, tenant_id=tenant_id, status="1").values_list("id", flat=True))
    if len(valid_ids) != len(kb_ids):
        return error_response("存在无效或未启用的知识库。")

    return success_response(_build_debug_result(
        question=question,
        kb_ids=kb_ids,
        tenant_id=tenant_id,
        top_n=data.get("top_n"),
        mode=data.get("mode"),
    ))


@extend_schema(tags=_RETRIEVAL_TAG, summary="同问题多模式检索对比", responses={200: None})
@api_view(["POST"])
def retrieval_compare(request: Request) -> Response:
    """POST /retrieval/compare — 同一个问题分别执行 text / vision / hybrid 检索。"""
    data = request.data if isinstance(request.data, dict) else {}
    question = str(data.get("question") or "").strip()
    kb_ids = data.get("kb_ids") or []
    tenant_id = str(data.get("tenant_id") or "default").strip() or "default"
    modes = data.get("modes") or ["text", "vision", "hybrid"]
    if isinstance(kb_ids, str):
        kb_ids = [item.strip() for item in kb_ids.split(",") if item.strip()]
    if isinstance(modes, str):
        modes = [item.strip() for item in modes.split(",") if item.strip()]
    modes = [mode for mode in modes if mode in {"text", "vision", "hybrid"}]
    if not question:
        return error_response("question 不能为空。")
    if not kb_ids:
        return error_response("kb_ids 不能为空。")
    valid_ids = list(Knowledgebase.objects.filter(id__in=kb_ids, tenant_id=tenant_id, status="1").values_list("id", flat=True))
    if len(valid_ids) != len(kb_ids):
        return error_response("存在无效或未启用的知识库。")

    results = []
    for mode in modes:
        try:
            result = _build_debug_result(question, kb_ids, tenant_id, data.get("top_n"), mode)
            result["status"] = "success"
        except Exception as exc:  # noqa: BLE001
            logger.exception("多模式检索对比失败 mode={} error={}", mode, exc)
            result = {
                "question": question,
                "tenant_id": tenant_id,
                "kb_ids": kb_ids,
                "rag_mode": mode,
                "text_chunks": [],
                "vision_pages": [],
                "doc_aggs": [],
                "context_preview": "",
                "summary": {"text_hit_count": 0, "vision_hit_count": 0, "doc_count": 0, "has_reference": False},
                "status": "failed",
                "error": str(exc),
            }
        results.append(result)
    return success_response({"question": question, "kb_ids": kb_ids, "results": results})
