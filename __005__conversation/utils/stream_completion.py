"""SSE 流式 completion 生成器。"""

from __future__ import annotations

# 1. Python 标准库
from dataclasses import replace
import json
import queue
import threading
import time
from typing import Any

# 2. 第三方库
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.intent.service import IntentService
from __001__rag.llm.factory import split_model_name_and_factory
from __001__rag.llm.service import LLMService
from __001__rag.models import Conversation, Knowledgebase
from __001__rag.utils.ids import get_uuid
from __005__conversation.utils.service import (
    _build_chat_messages,
    _decorate_answer,
    _do_retrieval,
    _format_chunks_for_prompt,
    _save_conversation,
    _truncate_by_token_budget,
    _truncate_messages_by_memory,
    chunks_format,
)
from __005__conversation.utils.step_tracker import StepDef, StepTracker


# =============================================================================
# SSE 事件构建器
# =============================================================================


def _sse_event(data: Any, code: int = 0, message: str = "") -> str:
    """构建单条 SSE 事件字符串。"""
    payload = {"code": code, "message": message, "data": data}
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _sse_error(error: str) -> str:
    """构建 SSE 错误事件字符串。"""
    return _sse_event({"answer": f"**ERROR**: {error}", "reference": []}, code=500)


def _sse_step(message: str) -> str:
    """构建 SSE 步骤提示事件。"""
    return _sse_event({"answer": message, "reference": [], "is_step_prompt": True})


# =============================================================================
# thinking extra 构建
# =============================================================================


def _build_thinking_extra(model_name: str, enable_thinking: bool) -> dict:
    """根据 LLM 工厂构建 enable_thinking 对应的 extra 参数。"""
    _, factory = split_model_name_and_factory(model_name)
    factory = (factory or "").lower()

    if factory == "ollama":
        return {"think": enable_thinking}
    if factory == "vllm":
        return {"extra_body": {"chat_template_kwargs": {"enable_thinking": enable_thinking}}}
    return {"extra_body": {"enable_thinking": enable_thinking}}


# =============================================================================
# kb_info 构建
# =============================================================================


def _build_kb_info(chunks: list[dict]) -> list[dict]:
    """从检索 chunks 构建 kb_info 列表。"""
    return [
        {
            "content": c.get("content_with_weight", ""),
            "similarity": c.get("similarity", c.get("_score")),
            "vector_similarity": c.get("vector_similarity"),
            "term_similarity": c.get("term_similarity"),
            "document_name": c.get("docnm_kwd", ""),
        }
        for c in chunks
    ]


# =============================================================================
# 统一流式生成器
# =============================================================================


def _stream_vlm_answer(
    *,
    question: str,
    pages: list[dict],
    chunks: list[dict],
    assistant_cfg,
    message_id: str,
    conv,
    include_kb_info: bool,
    doc_aggs: list,
    tracker: StepTracker,
):
    """有页图时走 VLM；hybrid 把文本块作为补充上下文。"""
    from __010__colpali.generate.responder import generate_response

    kb_ids = getattr(assistant_cfg, "kb_ids", None) or []
    kb = Knowledgebase.objects.filter(id=kb_ids[0]).first() if kb_ids else None
    extra = "\n\n".join(
        f"[{i+1}] {c.get('docnm_kwd') or ''}: {c.get('content_with_weight') or ''}"
        for i, c in enumerate(chunks[:6])
    )
    query = question
    if extra.strip():
        query = f"{question}\n\n补充文本依据：\n{extra}"
    images = [p.get("image") for p in pages if p.get("image")]
    text, used = generate_response(
        images,
        query,
        kb.id if kb else "default",
        vlm_id=getattr(kb, "vlm_id", None) if kb else None,
    )
    image_urls = []
    for img in used:
        rel = str(img).replace("\\", "/").lstrip("/")
        if rel.startswith("media/pages/"):
            image_urls.append("/" + rel)
        else:
            image_urls.append("/media/pages/" + rel)
    tracker.mark_done(0.0)
    yield _sse_step(tracker.render_html())
    event_data: dict[str, Any] = {
        "answer": text,
        "id": message_id,
        "images": image_urls,
        "reference": {
            "chunks": chunks_format({"chunks": chunks}) if chunks else [],
            "pages": pages,
            "doc_aggs": doc_aggs,
        },
    }
    if include_kb_info:
        event_data["kb_info"] = _build_kb_info(chunks)
    yield _sse_event(event_data)
    if conv:
        _save_conversation(conv, text, event_data["reference"], getattr(kb, "vlm_id", None) or "qwen-vl-plus", message_id)


def _stream_completion(
    messages: list[dict],
    assistant_cfg,
    *,
    model_name: str,
    temperature: float,
    top_p: float,
    extra: dict | None = None,
    top_k: int | None = None,
    similarity_threshold: float | None = None,
    vector_similarity_weight: float | None = None,
    system_prompt: str | None = None,
    think_prefix: bool = False,
    conv: Conversation | None = None,
    include_kb_info: bool = False,
    kb_ids: list[str] | None = None,
):
    """统一的 SSE 流式 completion 生成器。"""
    message_id = (messages[-1].get("id") if messages else None) or get_uuid()

    if kb_ids is not None:
        assistant_cfg = replace(assistant_cfg, kb_ids=list(kb_ids))

    question = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            question = msg.get("content", "")
            break

    logger.info("用户问题 question={}", question)

    # 覆盖检索参数
    if top_k is not None:
        assistant_cfg.top_k = top_k
    if similarity_threshold is not None:
        assistant_cfg.similarity_threshold = similarity_threshold
    if vector_similarity_weight is not None:
        assistant_cfg.vector_similarity_weight = vector_similarity_weight

    # 覆盖 system_prompt
    if system_prompt:
        assistant_cfg.system_prompt = system_prompt

    # ------ 步骤追踪 ------
    tracker = StepTracker([
        StepDef("正在初始化对话上下文...", min_duration=0.0),
        StepDef("正在识别用户意图...", min_duration=0.0, is_blocked=True),
        StepDef("正在检查对话类型...", min_duration=0.4),
        StepDef("正在检索...", min_duration=0.0, is_blocked=True),
        StepDef("开始生成回复...", min_duration=0.0, is_blocked=True),
    ])
    tracker.start()

    # ------ 意图识别 ------
    _intent_result: dict = {}
    _intent_error: Exception | None = None
    _intent_done = threading.Event()
    _intent_start = time.monotonic()

    def _intent_worker():
        nonlocal _intent_error
        try:
            _intent_result["data"] = IntentService.recognize(question)
        except Exception as e:
            _intent_error = e
        finally:
            _intent_done.set()

    intent_thread = threading.Thread(target=_intent_worker, daemon=True)
    intent_thread.start()

    # ------ 检索变量 ------
    _retrieval_result: dict = {}
    _retrieval_error: Exception | None = None
    _retrieval_done = threading.Event()
    _retrieval_start = 0.0
    _retrieval_started = False
    retrieval_thread: threading.Thread | None = None

    actual_question: str = question
    effective_kb_ids: list[str] | None = None

    # ------ 投机检索 ------
    _speculative_used = False
    _speculative_enabled = (
        not question.startswith("@")
        and bool(assistant_cfg.kb_ids)
        and getattr(settings, "ENABLE_SPECULATIVE_RETRIEVAL", True)
    )

    if _speculative_enabled:
        _speculative_used = True
        _retrieval_start = time.monotonic()
        _retrieval_started = True

        def _speculative_retrieval_worker():
            nonlocal _retrieval_error
            try:
                _retrieval_result["data"] = _do_retrieval(
                    assistant_cfg, question, kb_ids_override=assistant_cfg.kb_ids,
                )
            except Exception as e:
                _retrieval_error = e
            finally:
                _retrieval_done.set()

        retrieval_thread = threading.Thread(target=_speculative_retrieval_worker, daemon=True)
        retrieval_thread.start()
        logger.info("投机检索已启动 kb_ids={}", assistant_cfg.kb_ids)

    yield _sse_step(tracker.render_html())

    while not tracker.is_finished:
        tracker.tick()
        yield _sse_step(tracker.render_html())

        if (
            not tracker.is_finished
            and tracker.current_step_def is not None
            and tracker.current_step_def.is_blocked
        ):
            current_idx = tracker.step_index

            if current_idx == 1 and _intent_done.is_set():
                _intent_done.wait()
                intent_thread.join()
                intent_elapsed = time.monotonic() - _intent_start
                tracker.mark_done(intent_elapsed)
                yield _sse_step(tracker.render_html())

                if _intent_error:
                    logger.info("意图识别失败，使用 fallback error={}", _intent_error)

                intent_result = _intent_result.get("data")
                intent_kb_ids = intent_result.kb_ids if (intent_result and intent_result.kb_ids) else None
                actual_question = intent_result.actual_question if intent_result else question
                effective_kb_ids = intent_kb_ids or None

                # 判断投机检索结果是否可复用
                speculative_hit = False
                if _speculative_used:
                    if intent_kb_ids is None or set(intent_kb_ids) == set(assistant_cfg.kb_ids):
                        speculative_hit = True
                        logger.info("投机检索命中，跳过重新检索")
                    else:
                        logger.info(
                            "投机检索未命中 intent_kb_ids={} default_kb_ids={}，丢弃并重新检索",
                            intent_kb_ids, assistant_cfg.kb_ids,
                        )
                        # 等待投机检索完成后重置状态
                        _retrieval_done.wait()
                        if retrieval_thread:
                            retrieval_thread.join()
                        _retrieval_result = {}
                        _retrieval_error = None
                        _retrieval_done = threading.Event()
                        _retrieval_started = False
                        speculative_hit = False

                if not speculative_hit:
                    _retrieval_start = time.monotonic()
                    _retrieval_started = True

                    def _retrieval_worker():
                        nonlocal _retrieval_error
                        try:
                            _retrieval_result["data"] = _do_retrieval(
                                assistant_cfg, actual_question, kb_ids_override=effective_kb_ids,
                            )
                        except Exception as e:
                            _retrieval_error = e
                        finally:
                            _retrieval_done.set()

                    retrieval_thread = threading.Thread(target=_retrieval_worker, daemon=True)
                    retrieval_thread.start()
                continue

            if current_idx == 3:
                _retrieval_timeout = float(getattr(settings, "SSE_RETRIEVAL_TIMEOUT", 60.0))
                _retrieval_poll = float(getattr(settings, "SSE_POLL_INTERVAL", 0.5))
                while True:
                    if _retrieval_done.wait(timeout=_retrieval_poll):
                        retrieval_elapsed = time.monotonic() - _retrieval_start
                        tracker.mark_done(retrieval_elapsed)
                        yield _sse_step(tracker.render_html())
                        break
                    if time.monotonic() - _retrieval_start > _retrieval_timeout:
                        tracker.mark_done(time.monotonic() - _retrieval_start)
                        yield _sse_step(tracker.render_html())
                        yield _sse_error("检索超时，请重试")
                        return
                    yield _sse_step(tracker.render_html())
                if not tracker.is_finished:
                    break

        time.sleep(tracker.recommended_wait)

    if _retrieval_started and retrieval_thread:
        _retrieval_done.wait()
        retrieval_thread.join()

    if _retrieval_error:
        logger.exception("检索失败")
        yield _sse_error(str(_retrieval_error))
        return

    chunks, reference, doc_aggs = _retrieval_result["data"]
    pages = (reference or {}).get("pages") or [] if isinstance(reference, dict) else []

    if pages:
        yield from _stream_vlm_answer(
            question=actual_question,
            pages=pages,
            chunks=chunks,
            assistant_cfg=assistant_cfg,
            message_id=message_id,
            conv=conv,
            include_kb_info=include_kb_info,
            doc_aggs=doc_aggs,
            tracker=tracker,
        )
        return

    # ------ 构建 chat_messages ------
    _, knowledges = _format_chunks_for_prompt(chunks)
    truncated_messages = _truncate_messages_by_memory(messages, assistant_cfg.memory_rounds)
    chat_messages = _build_chat_messages(
        assistant_cfg.system_prompt,
        truncated_messages,
        chunks,
        user_prompt_template=assistant_cfg.user_prompt_template,
    )
    # 基于 token 预算自适应截断（清除 think 标签后）
    chat_messages = _truncate_by_token_budget(chat_messages, assistant_cfg.max_tokens, knowledges)

    # ------ 流式输出 LLM ------
    full_answer = ""
    chat_queue: queue.Queue = queue.Queue()

    def _chat_worker():
        try:
            accumulated = ""
            think_prefix_added = False
            prefix_decided = False
            for delta in LLMService.stream_chat(
                messages=chat_messages,
                model_name=model_name,
                temperature=temperature,
                top_p=top_p,
                extra=extra or {},
            ):
                if not prefix_decided:
                    prefix_decided = True
                    if think_prefix and not delta.lstrip().startswith("<think>"):
                        accumulated = "<think>\n"
                        think_prefix_added = True
                accumulated += delta
                chat_queue.put(accumulated)
            # 如果强制加了 <think> 前缀但模型内容里没有 </think>，补上关闭标签
            if think_prefix_added and "</think>" not in accumulated:
                accumulated += "\n</think>"
                chat_queue.put(accumulated)
            logger.info("LLM 完整输出 model={} content={}", model_name, accumulated)
            chat_queue.put(None)
        except Exception as e:
            logger.exception("LLM 流式调用失败")
            chat_queue.put(e)

    _llm_start = time.monotonic()
    t = threading.Thread(target=_chat_worker, daemon=True)
    t.start()

    # 等待 LLM 首 token（步骤 4 保持进行中状态，周期性渲染耗时）
    _llm_timeout = float(getattr(settings, "SSE_LLM_FIRST_TOKEN_TIMEOUT", 60.0))
    _llm_poll_interval = float(getattr(settings, "SSE_LLM_POLL_INTERVAL", 0.5))
    first_item = None
    while time.monotonic() - _llm_start < _llm_timeout:
        try:
            first_item = chat_queue.get(timeout=_llm_poll_interval)
            break
        except queue.Empty:
            yield _sse_step(tracker.render_html())

    if first_item is None and chat_queue.empty():
        tracker.mark_done(_llm_timeout)
        yield _sse_step(tracker.render_html())
        yield _sse_error("LLM 响应超时，请重试")
        return

    if isinstance(first_item, Exception):
        tracker.mark_done(0.0)
        yield _sse_step(tracker.render_html())
        yield _sse_error(str(first_item))
        return

    if first_item is None:
        tracker.mark_done(0.0)
        yield _sse_step(tracker.render_html())
        yield _sse_event(True)
        return

    # 首 token 到达，标记步骤 4 完成
    llm_elapsed = time.monotonic() - _llm_start
    tracker.mark_done(llm_elapsed)
    yield _sse_step(tracker.render_html())

    full_answer = first_item
    yield _sse_event({"answer": full_answer, "id": message_id})

    # 继续消费后续 token
    try:
        while True:
            item = chat_queue.get()
            if item is None:
                break
            if isinstance(item, Exception):
                yield _sse_error(str(item))
                return
            full_answer = item
            yield _sse_event({"answer": full_answer, "id": message_id})
    except Exception as e:
        logger.exception("LLM 流式读取异常")
        yield _sse_error(str(e))
        return

    if not full_answer:
        yield _sse_event(True)
        return

    # ------ 装饰答案 ------
    try:
        kbinfos = {"chunks": chunks, "doc_aggs": doc_aggs}
        knowledges_list = [c.get("content_with_weight", "") for c in chunks]
        decorated = _decorate_answer(full_answer, kbinfos, knowledges_list)
        final_content = decorated["answer"]
        decorated_ref = decorated["reference"]
        if not isinstance(decorated_ref, dict):
            decorated_ref = {"chunks": [], "doc_aggs": []}
        decorated_ref["message_id"] = message_id
        decorated_ref["chunks"] = chunks_format(decorated_ref)

        event_data: dict[str, Any] = {
            "answer": decorated["answer"],
            "reference": decorated_ref,
        }
        if include_kb_info:
            event_data["kb_info"] = _build_kb_info(chunks)

        yield _sse_event(event_data)

        if conv:
            _save_conversation(conv, final_content, decorated_ref, model_name, message_id)
    except Exception as e:
        logger.exception("装饰答案/保存会话失败")

    yield _sse_event(True)


# =============================================================================
# 公共生成器（薄包装）
# =============================================================================


def completion_stream_generator(
    conv: Conversation,
    messages: list[dict],
    assistant_cfg,
    *,
    kb_ids: list[str] | None = None,
    model_name: str | None = None,
):
    """SSE 流式 completion 生成器。"""
    effective_model = model_name or assistant_cfg.model_name or ""
    logger.info("会话模型 conv_id={} model_name={}", conv.id, effective_model)
    yield from _stream_completion(
        messages,
        assistant_cfg,
        model_name=effective_model,
        temperature=assistant_cfg.temperature,
        top_p=assistant_cfg.top_p,
        extra=assistant_cfg.extra_params,
        think_prefix=("deepseek:671b" in effective_model),
        conv=conv,
        kb_ids=kb_ids,
    )


def completion_with_model_stream_generator(
    messages: list[dict],
    assistant_cfg,
    *,
    model_name: str,
    temperature: float = 0.15,
    top_p: float = 0.35,
    enable_thinking: bool = False,
):
    """SSE 流式 completion 生成器（模型对比接口，不保存会话）。"""
    yield from _stream_completion(
        messages,
        assistant_cfg,
        model_name=model_name,
        temperature=temperature,
        top_p=top_p,
        extra=_build_thinking_extra(model_name, enable_thinking),
    )


def completion_with_all_stream_generator(
    messages: list[dict],
    assistant_cfg,
    *,
    system_prompt: str | None = None,
    model_name: str,
    temperature: float = 0.5,
    top_p: float = 0.9,
    enable_thinking: bool = False,
    top_k: int = 1024,
    similarity_threshold: float = 0.2,
    vector_similarity_weight: float = 0.3,
):
    """SSE 流式 completion 生成器（多参数对话接口，不保存会话）。"""
    yield from _stream_completion(
        messages,
        assistant_cfg,
        model_name=model_name,
        temperature=temperature,
        top_p=top_p,
        extra=_build_thinking_extra(model_name, enable_thinking),
        top_k=top_k,
        similarity_threshold=similarity_threshold,
        vector_similarity_weight=vector_similarity_weight,
        system_prompt=system_prompt,
        include_kb_info=True,
    )
