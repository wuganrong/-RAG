"""对话相关工具函数与类。"""

from __future__ import annotations

# 1. Python 标准库
import importlib
import json
import re
import threading
import time
from copy import deepcopy
from typing import Any

# 2. 第三方库
import tiktoken
from django.conf import settings
from loguru import logger

_tiktoken_encoding = tiktoken.get_encoding("cl100k_base")

# 3. 本地应用
from __001__rag.chunk.utils.documents import build_query_embedding
from __001__rag.llm.base import ChatMessage
from __001__rag.llm.service import LLMService
from __001__rag.models import Conversation, Knowledgebase, PromptConfig, RetrievalMethod
from __001__rag.retrieval.hybrid import HybridRetriever
from __001__rag.retrieval.utils.query_enhance import _enhance_query
from __001__rag.utils import format_datetime


def chunks_format(reference: dict) -> list[dict]:
    """格式化 reference 中的 chunks 列表为标准响应格式。"""

    def _get_value(d: dict, k1: str, k2: str) -> Any:
        return d.get(k1, d.get(k2))

    return [
        {
            "id": _get_value(chunk, "chunk_id", "id"),
            "content": _get_value(chunk, "content", "content_with_weight"),
            "document_id": _get_value(chunk, "doc_id", "document_id"),
            "document_name": _get_value(chunk, "docnm_kwd", "document_name"),
            "dataset_id": _get_value(chunk, "kb_id", "dataset_id"),
            "image_id": _get_value(chunk, "image_id", "img_id"),
            "positions": _get_value(chunk, "positions", "position_int"),
            "url": chunk.get("url"),
            "similarity": chunk.get("similarity", chunk.get("_score")),
            "vector_similarity": chunk.get("vector_similarity"),
            "term_similarity": chunk.get("term_similarity"),
        }
        for chunk in reference.get("chunks", [])
    ]


def conversation_to_dict(conv: Conversation) -> dict[str, Any]:
    """将 Conversation 模型实例序列化为 API 响应字典。"""
    message = conv.message
    if isinstance(message, str):
        try:
            message = json.loads(message)
        except (json.JSONDecodeError, TypeError):
            message = []

    reference = conv.reference
    if isinstance(reference, str):
        try:
            reference = json.loads(reference)
        except (json.JSONDecodeError, TypeError):
            reference = []

    return {
        "id": conv.id,
        "name": conv.name,
        "model": conv.model,
        "message": message,
        "reference": reference,
        "user_id": conv.user_id,
        "tenant_id": getattr(conv, "tenant_id", "default") or "default",
        "create_date": format_datetime(conv.create_date),
        "update_date": format_datetime(conv.update_date),
    }


def _get_citation_prompt() -> str:
    """从缓存或 PromptConfig 表获取引用提示词（config_key='citation'）。

    优先从 Redis 缓存读取，未命中时查 DB 并回填缓存。
    """
    from __001__rag.cache.manager import CacheManager

    # ① 尝试缓存
    cached = CacheManager.get_citation_prompt()
    if cached is not None:
        logger.info("加载引用提示词：缓存命中 len={}", len(cached))
        return cached

    # ② DB 查询
    try:
        config = PromptConfig.objects.filter(config_key="citation", status="1").first()
        if config and config.system_prompt:
            CacheManager.set_citation_prompt(config.system_prompt)
            logger.info("加载引用提示词：缓存未命中，数据库加载 len={}", len(config.system_prompt))
            return config.system_prompt
    except Exception:
        logger.exception("获取 citation 提示词失败")
    return ""


def count_tokens(text: str) -> int:
    """使用 cl100k_base 编码计算文本 token 数。"""
    if not text:
        return 0
    return len(_tiktoken_encoding.encode(text))


def _format_chunks_for_prompt(chunks: list[dict]) -> tuple[str, list[str]]:
    """将检索到的 chunks 格式化为 LLM prompt 用的知识文本。

    Returns:
        (knowledge_text, knowledge_list): 拼接后的知识文本和各条知识片段列表
    """
    knowledges: list[str] = []
    for i, ck in enumerate(chunks):
        docnm = ck.get("docnm_kwd", "")
        content = ck.get("content_with_weight", "")
        txt = f"\nDocument: {docnm} \n"
        txt += f"ID: {i}"
        txt += "\n└── Content:" + content + "\n"
        knowledges.append(txt)
    return "\n".join(knowledges), knowledges


# 引用格式正则
_CITATION_PATTERNS: list[re.Pattern] = [
    re.compile(r"\(\s*ID\s*[: ]*\s*(\d+)\s*\)"),      # (ID: 12)
    re.compile(r"（\s*ID\s*[: ]*\s*(\d+)\s*）"),       # （ID: 12）
    re.compile(r"\[\s*ID\s*[: ]*\s*(\d+)\s*\]"),       # [ID: 12]
    re.compile(r"【\s*ID\s*[: ]*\s*(\d+)\s*】"),        # 【ID: 12】
    re.compile(r"ref\s*(\d+)", flags=re.IGNORECASE),    # ref12、REF 12
]

_THINK_BLOCK_PATTERN = re.compile(r"<think\b[^>]*>.*?</think>", flags=re.DOTALL | re.IGNORECASE)


def _decorate_answer(
    answer: str,
    kbinfos: dict | None,
    knowledges: list[str],
    *,
    quote: bool = True,
) -> dict:
    """对 LLM 生成的回复进行后处理：分离 think、转换引用格式、构建 reference。

    Args:
        answer: LLM 生成的完整回复文本。
        kbinfos: 检索结果，包含 chunks 和 doc_aggs。
        knowledges: 格式化后的知识文本列表。
        quote: 是否启用引用处理。

    Returns:
        {"answer": 处理后的回复, "reference": 引用信息, "prompt": 知识文本}
    """
    refs: dict = {}
    think = ""
    prompt = "\n".join(knowledges) if knowledges else ""

    try:
        # 1. 分离 <think> 思考内容
        ans_parts = answer.split("</think>")
        if len(ans_parts) == 2:
            think = ans_parts[0] + "</think>"
            answer = ans_parts[1]

        idx: set[int] = set()

        logger.info(
            "格式化引用块信息：开始处理 knowledges={} chunks={} quote={}",
            len(knowledges), len(kbinfos.get("chunks", [])) if kbinfos else 0, quote,
        )

        if knowledges and kbinfos and quote:
            # 2. 去除残留的 ##i$$ / ##j$$ 标记
            answer = re.sub(r"##[ij]\$\$", "", answer, flags=re.DOTALL)

            chunks = kbinfos.get("chunks", [])
            max_idx = len(chunks)

            def _safe_add(i: int) -> bool:
                if 0 <= i < max_idx:
                    idx.add(i)
                    return True
                return False

            # 3. 检测 ##数字$$ 格式并转换为 [ID:数字]
            for match in re.finditer(r"##([0-9]+)\$\$", answer):
                i = int(match.group(1))
                _safe_add(i)
                answer = answer.replace(match.group(0), f"[ID:{i}]")

            # 4. 检测 [ID:n] 格式
            for match in re.finditer(r"\[ID:(\d+)]", answer):
                _safe_add(int(match.group(1)))

            # 5. 修复其他各种错误引用格式
            for pattern in _CITATION_PATTERNS:
                for match in pattern.finditer(answer):
                    try:
                        i = int(match.group(1))
                    except (ValueError, IndexError):
                        continue
                    if _safe_add(i):
                        answer = answer.replace(match.group(0), f"[ID:{i}]")

            # 6. 返回全部 chunks，doc_aggs 对应全部 chunks
            all_chunks = list(chunks) if chunks else []

            # 从全部 chunks 重新构建 doc_aggs
            cited_doc_aggs = _build_doc_aggs_from_chunks(all_chunks)

            # 7. 构建 reference（去除 vector 字段）
            refs = deepcopy(kbinfos) if kbinfos else {}
            refs["chunks"] = all_chunks
            refs["doc_aggs"] = cited_doc_aggs
            for c in refs.get("chunks", []):
                c.pop("vector", None)
                c.pop("embedding", None)
                c.pop("q_{}_vec".format(len(c.get("vector", []))), None)

    except Exception:
        logger.exception("格式化引用块信息：处理失败")
        refs = {}

    if not isinstance(refs, dict):
        refs = {}
    logger.info(
        "格式化引用块信息：完成 chunks={} doc_aggs={} citations={}",
        len(refs.get("chunks", [])), len(refs.get("doc_aggs", [])), len(idx),
    )
    return {"answer": think + answer, "reference": refs, "prompt": prompt}


_KNOWLEDGE_HEADER = "\n\n### Knowledge Base:\n"


def _build_chat_messages(
    system_prompt: str | None,
    messages: list[dict],
    chunks: list[dict],
    *,
    user_prompt_template: str | None = None,
) -> list:
    """构建发送给 LLM 的完整 messages 列表。

    将检索到的 chunks 格式化为知识文本，追加到 system prompt 末尾，
    用 user_prompt_template 包裹最后一条 user 消息（填充 {input}），
    并追加引用提示词（citation prompt），然后组装 [system] + history 格式的消息列表。
    """
    knowledge_text, _ = _format_chunks_for_prompt(chunks)
    citation_prompt = _get_citation_prompt()
    result: list[ChatMessage] = []

    system_content = system_prompt or ""
    # 替换 {knowledge} 占位符为空，知识统一追加到末尾
    system_content = system_content.replace("{knowledge}", "")
    if knowledge_text:
        system_content += _KNOWLEDGE_HEADER + knowledge_text
        logger.info("构建 system prompt：注入知识库上下文 chunks={} knowledge_len={}", len(chunks), len(knowledge_text))

    if citation_prompt:
        system_content += "\n\n" + citation_prompt

    if system_content:
        result.append(ChatMessage(role="system", content=system_content))

    for i, msg in enumerate(messages):
        role = msg.get("role", "")
        if role == "system":
            continue
        if role == "assistant" and not result:
            continue
        content = msg.get("content", "")

        # 剥离历史 assistant 回复中的 think 标签，防止上下文膨胀
        if role == "assistant":
            content = _THINK_BLOCK_PATTERN.sub("", content)

        # 对最后一条 user 消息应用 user_prompt_template
        is_last = (i == len(messages) - 1)
        if is_last and role == "user" and user_prompt_template and "{input}" in user_prompt_template:
            content = user_prompt_template.replace("{input}", content)
            logger.info("构建用户 prompt：应用模板 original_len={} template_len={}", len(msg.get("content", "")), len(content))

        result.append(ChatMessage(role=role, content=content))

    return result


def _truncate_by_token_budget(
    chat_messages: list,
    token_budget: int | None,
    knowledges: list[str] | None = None,
) -> list:
    """根据 token 预算自适应截断 chat_messages，调整消息以适应令牌限制。

    在清除 think 标签后，使用 tiktoken cl100k_base 编码计算 token 数，
    按优先级保留消息并截断：

    保留优先级（从高到低）：
    1. system prompt 基础部分（系统提示词 + 引用提示词）— 不可削减
    2. 最后一条 user 消息 — 不可削减
    3. 知识片段（knowledge chunks）— 从最相关的开始保留
    4. 历史消息 — 从最旧的开始逐条移除

    Args:
        chat_messages: 完整的 ChatMessage 列表（system + history + user）。
        token_budget: 总 token 预算（prompt + completion），None 或 <= 0 表示不截断。
        knowledges: 各条知识片段的独立文本列表，用于精细截断知识内容。

    Returns:
        截断后的 ChatMessage 列表。
    """
    if not token_budget or token_budget <= 0:
        logger.info("token 截断：未配置预算，跳过")
        return chat_messages
    if not chat_messages:
        return chat_messages

    # 分离 system / history / last user
    system_msg = None
    history = []
    user_msg = None
    for i, msg in enumerate(chat_messages):
        if i == 0 and msg.role == "system":
            system_msg = msg
        elif i == len(chat_messages) - 1 and msg.role == "user":
            user_msg = msg
        else:
            history.append(msg)

    # 计算 system 基础 token（不含知识）
    system_content = system_msg.content if system_msg else ""
    system_base = system_content
    _has_knowledge = knowledges and _KNOWLEDGE_HEADER in system_content
    if _has_knowledge:
        system_base = system_content.split(_KNOWLEDGE_HEADER)[0]

    system_base_tokens = count_tokens(system_base)
    knowledge_tokens = [count_tokens(k) for k in (knowledges or [])]

    # 计算 user token
    user_tokens = count_tokens(user_msg.content) if user_msg else 0

    # 计算 history token
    history_tokens = [(msg, count_tokens(msg.content)) for msg in history]

    # 当前总 token
    original_history_count = len(history_tokens)
    total = system_base_tokens + sum(knowledge_tokens) + user_tokens + sum(t for _, t in history_tokens)
    original_total = total

    if total <= token_budget:
        logger.info("token 截断：未超出预算（{} / {}），跳过", total, token_budget)
        return chat_messages

    # 如果 system_base + user 已超限，记录警告
    if system_base_tokens + user_tokens >= token_budget:
        logger.info(
            "token 截断：系统提示词和用户问题已占 {} tokens，超出预算 {}，无法保留完整上下文",
            system_base_tokens + user_tokens, token_budget,
        )

    # 阶段 1：从最旧的历史开始移除
    while history_tokens and total > token_budget:
        _, t = history_tokens.pop(0)
        total -= t

    # 阶段 2：如果仍然超限，从末尾移除知识片段（最相关的在前面）
    original_knowledge_count = len(knowledges or [])
    remaining_knowledges = list(knowledges) if knowledges else []
    while remaining_knowledges and total > token_budget:
        remaining_knowledges.pop()
        total -= knowledge_tokens[len(remaining_knowledges)]

    # 重建 system message
    if system_msg and _has_knowledge:
        if remaining_knowledges:
            new_system_content = system_base + _KNOWLEDGE_HEADER + "".join(remaining_knowledges)
        else:
            new_system_content = system_base
        new_system_msg = ChatMessage(role="system", content=new_system_content)
    else:
        new_system_msg = system_msg

    result = []
    if new_system_msg:
        result.append(new_system_msg)
    result.extend(msg for msg, _ in history_tokens)
    if user_msg:
        result.append(user_msg)

    history_removed = original_history_count - len(history_tokens)
    knowledge_removed = original_knowledge_count - len(remaining_knowledges)
    actions = []
    if history_removed:
        actions.append(f"移除 {history_removed} 条历史消息")
    if knowledge_removed:
        actions.append(f"移除 {knowledge_removed} 条知识片段")
    logger.info(
        "token 截断：原始 {} tokens 超出预算 {}，{}，截断后 {} tokens",
        original_total, token_budget, "、".join(actions) if actions else "无需裁剪", total,
    )

    return result


def _build_doc_aggs_from_chunks(chunks: list[dict]) -> list[dict]:
    """从检索 chunks 汇总 doc_id/doc_name，供前端引用文档列表展示。"""
    agg: dict[str, dict] = {}
    for chunk in chunks:
        doc_id = chunk.get("doc_id") or ""
        if not doc_id:
            continue
        doc_name = chunk.get("docnm_kwd") or chunk.get("document_name") or doc_id
        if doc_id not in agg:
            agg[doc_id] = {"doc_id": doc_id, "doc_name": doc_name, "count": 0}
        agg[doc_id]["count"] += 1
    return list(agg.values())


def _format_retrieval_reference(search_result, doc_aggs) -> dict:
    """将检索结果格式化为 reference 字典。"""
    chunks = []
    for chunk in search_result.chunks:
        # similarity: 优先使用显式字段，回退到 ES _score
        similarity = chunk.get("similarity")
        if similarity is None:
            similarity = chunk.get("_score")
        chunks.append({
            "chunk_id": chunk.get("id", ""),
            "content_with_weight": chunk.get("content_with_weight", ""),
            "doc_id": chunk.get("doc_id", ""),
            "docnm_kwd": chunk.get("docnm_kwd", ""),
            "kb_id": chunk.get("kb_id", ""),
            "image_id": chunk.get("img_id", ""),
            "positions": chunk.get("position_int", []),
            "similarity": similarity,
            "vector_similarity": chunk.get("vector_similarity"),
            "term_similarity": chunk.get("term_similarity"),
        })
    return {"chunks": chunks, "doc_aggs": doc_aggs}


_retriever_cache: dict[str, object] = {}
_retriever_cache_lock = threading.Lock()


def _get_retriever(retrieval_method: str | None) -> object:
    """根据检索方法标识获取检索器实例（带内存缓存），默认使用混合检索。"""
    method_name = retrieval_method or "hybrid"

    # 查内存缓存
    with _retriever_cache_lock:
        cached = _retriever_cache.get(method_name)
        if cached is not None:
            logger.info("加载检索器：缓存命中 method={}", method_name)
            return cached

    # 缓存未命中，从 DB 加载
    retriever = None
    try:
        row = RetrievalMethod.objects.filter(method=method_name, status="1").first()
        if row:
            module_path, class_name = row.method_class.rsplit(".", 1)
            module = importlib.import_module(module_path)
            retriever_cls = getattr(module, class_name)
            retriever = retriever_cls()
            logger.info("加载检索器：缓存未命中，数据库加载 method={} class={}", method_name, row.method_class)
    except Exception:
        logger.exception("加载检索器失败 method={}，回退到默认混合检索", method_name)

    if retriever is None:
        retriever = HybridRetriever()

    with _retriever_cache_lock:
        _retriever_cache[method_name] = retriever
    return retriever


def _log_retrieval_chunks(chunks: list[dict]) -> None:
    """打印检索结果摘要。"""
    if not chunks:
        logger.info("检索结果为空，未找到匹配的切片")
        return

    scores = [c.get("similarity") or c.get("_score") or 0 for c in chunks]
    logger.info(
        "检索到切片 total={} score_min={:.4f} score_max={:.4f}",
        len(chunks), min(scores), max(scores),
    )


def _apply_rerank(
    chunks: list[dict], question: str, assistant_cfg, top_n: int,
) -> list[dict]:
    """对检索到的 chunks 使用重排序模型进行重排序。

    若 assistant 未配置 rerank_id 则直接返回原 chunks。
    """
    if not chunks or not assistant_cfg.rerank_id:
        return chunks

    try:
        documents = [c.get("content_with_weight", "") for c in chunks]
        logger.info("重排序开始 rerank_id={} doc_count={} top_n={}", assistant_cfg.rerank_id, len(documents), top_n)
        reranked = LLMService.rerank(
            query=question,
            documents=documents,
            model_name=assistant_cfg.rerank_id,
            topn=top_n,
        )
        # reranked: list[(original_index, score)], 按 score 降序
        # 将 reranker 分数回写到 similarity，保证下游排序和展示一致
        reordered = []
        for idx, score in reranked:
            if idx < len(chunks):
                chunk = dict(chunks[idx])
                chunk["similarity"] = score
                reordered.append(chunk)
        logger.info(
            "重排序完成 rerank_id={} before={} after={} top1_score={}",
            assistant_cfg.rerank_id, len(chunks), len(reordered),
            reranked[0][1] if reranked else 0,
        )
        return reordered
    except Exception:
        logger.exception("重排序失败，使用原始排序")
        return chunks


def _truncate_messages_by_memory(messages: list[dict], memory_rounds: int) -> list[dict]:
    """根据 memory_rounds 截断历史消息，仅保留最近 N 轮对话。

    一轮 = 一组 user + assistant 对。保留最近的 memory_rounds 轮。
    """
    if memory_rounds <= 0 or not messages:
        return messages

    # 从末尾向前收集轮次
    rounds = 0
    keep_from = 0
    has_user = False
    for i in range(len(messages) - 1, -1, -1):
        role = messages[i].get("role", "")
        if role == "user":
            has_user = True
        elif role == "assistant" and has_user:
            rounds += 1
            has_user = False
            if rounds >= memory_rounds:
                keep_from = max(0, i - 1)
                break

    if keep_from > 0:
        logger.info("memory_rounds={} 截断消息 before={} after={}", memory_rounds, len(messages), len(messages) - keep_from)
    return messages[keep_from:]


# =============================================================================
# 检索可观测性工具函数
# =============================================================================

def _compute_cosine_similarity(a: list[float], b: list[float]) -> float:
    """计算两个向量的余弦相似度。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _enrich_chunks_with_scores(chunks, query_embedding, vt_weight):
    """为每条 chunk 本地计算 vsim 和反推 tsim，原地修改 chunk dict。"""
    if not query_embedding:
        return
    vec_field = f"q_{len(query_embedding)}_vec"
    for chunk in chunks:
        vec = chunk.pop(vec_field, None)
        if vec and isinstance(vec, list):
            vsim = _compute_cosine_similarity(query_embedding, vec)
            chunk["vector_similarity"] = round(vsim, 4)
            sim = float(chunk.get("similarity") or chunk.get("_score") or 0)
            if vt_weight < 1.0:
                tsim = (sim - vsim * vt_weight) / (1 - vt_weight)
                chunk["term_similarity"] = round(max(0.0, min(1.0, tsim)), 4)
            else:
                chunk["term_similarity"] = 0.0


def _log_chunk_details(chunks, original_ids=None, rerank_model=None):
    """统一输出 chunk 详情，整个阶段拼为一个字符串、单次 logger.info 输出，避免日志割裂。"""
    if not chunks:
        return

    is_rerank = original_ids is not None
    sep = f"========== Rerank({rerank_model}) ==========" if is_rerank else "==================== Search ===================="
    end_sep = "======================= END ======================="
    output_lines = [sep, ""]

    for i, chunk in enumerate(chunks):
        doc_path = chunk.get("docnm_kwd") or chunk.get("doc_name") or "未知文档"
        content = chunk.get("content_with_weight", "")
        content_preview = content[:150].replace("\n", " ") + ("..." if len(content) > 150 else "")

        if is_rerank:
            old_idx = original_ids.index(chunk.get("id")) if chunk.get("id") in original_ids else -1
            score = float(chunk.get("similarity") or chunk.get("_score") or 0)
            score_line = f"score={score} | old_pos={old_idx} → new_pos={i}"
        else:
            sim = float(chunk.get("similarity") or chunk.get("_score") or 0)
            vsim = float(chunk.get("vector_similarity") or 0)
            tsim = float(chunk.get("term_similarity") or 0)
            score_line = f"sim={sim} | vsim={vsim} | tsim={tsim}"

        output_lines.extend([
            f"Document: {doc_path}",
            f"ID: {i}",
            f"├── {score_line}",
            f"└── Content: {content_preview}",
            "",
        ])

    output_lines.append(end_sep)
    logger.info("\n{}", "\n".join(output_lines))


def _do_retrieval(
    assistant_cfg,
    question: str,
    kb_ids_override: list[str] | None = None,
    rag_mode_override: str | None = None,
):
    """执行知识库检索，返回 (chunks, reference_dict, doc_aggs)。"""
    kb_ids = kb_ids_override if kb_ids_override is not None else assistant_cfg.kb_ids
    kb = Knowledgebase.objects.filter(id=kb_ids[0]).first() if kb_ids else None
    rag_mode = (rag_mode_override or getattr(kb, "rag_mode", None) or "text") if kb else "text"
    if rag_mode not in {"text", "vision", "hybrid"}:
        rag_mode = "text"

    chunks: list = []
    doc_aggs: list = []
    pages: list = []

    if rag_mode in {"text", "hybrid"} and kb_ids:
        enhanced_question, text_match_expr = _enhance_query(question)
        logger.info("检索阶段开始 kb_ids={} retrieval_method={} rag_mode={}", kb_ids, assistant_cfg.retrieval_method, rag_mode)
        embedding_model_name = None
        if kb and kb.embd_id:
            embedding_model_name = kb.embd_id
        embedding = build_query_embedding(enhanced_question, model_name=embedding_model_name)
        retriever = _get_retriever(assistant_cfg.retrieval_method)
        from __001__rag.search.constants import CHUNK_SELECT_FIELDS_WITH_KB
        select_fields = list(CHUNK_SELECT_FIELDS_WITH_KB)
        if embedding:
            vec_field = f"q_{len(embedding)}_vec"
            if vec_field not in select_fields:
                select_fields.append(vec_field)
        search_result = retriever.retrieve(
            kb_ids=kb_ids,
            question=enhanced_question,
            embedding=embedding,
            page=1,
            size=assistant_cfg.top_n * 2,
            top_k=assistant_cfg.top_k,
            similarity_threshold=assistant_cfg.similarity_threshold,
            vector_similarity_weight=assistant_cfg.vector_similarity_weight,
            text_match_expr=text_match_expr,
            select_fields=select_fields,
        )
        chunks = search_result.chunks
        aggs = search_result.aggregations.get("docnm_kwd", [])
        if isinstance(aggs, list):
            doc_aggs = [{"doc_name": name, "count": count} for name, count in aggs]
        elif isinstance(aggs, dict):
            doc_aggs = aggs.get("buckets", [])
        _enrich_chunks_with_scores(chunks, embedding, assistant_cfg.vector_similarity_weight)
        if chunks and assistant_cfg.rerank_id:
            chunks = _apply_rerank(chunks, question, assistant_cfg, assistant_cfg.top_n)
        chunks = chunks[:assistant_cfg.top_n]
        chunks.sort(key=lambda c: c.get("similarity") or c.get("_score") or 0, reverse=True)
        doc_aggs_from_chunks = _build_doc_aggs_from_chunks(chunks)
        if doc_aggs_from_chunks:
            doc_aggs = doc_aggs_from_chunks

    if rag_mode in {"vision", "hybrid"} and kb is not None:
        pages = _retrieve_vision_pages(kb, question)

    if rag_mode == "vision":
        chunks = []

    reference = _format_retrieval_reference(
        type("Result", (), {"chunks": chunks, "aggregations": {}})(),
        doc_aggs,
    )
    if isinstance(reference, dict):
        reference["pages"] = pages
    return chunks, reference, doc_aggs


def _retrieve_vision_pages(kb: Knowledgebase, question: str) -> list[dict]:
    from __010__colpali.index.vision_index import get_vision_model
    from __010__colpali.paths import BYALDI_DIR
    from __010__colpali.retrieve.retriever import retrieve_documents

    rag = get_vision_model(kb.id, BYALDI_DIR)
    if rag is None:
        return []
    k = int(getattr(kb, "page_top_n", None) or 3)
    pages = retrieve_documents(rag, question, kb.id, k=k)
    for page in pages:
        page["kind"] = "page"
        rel = page.get("image") or ""
        page["url"] = f"/media/pages/{rel}".replace("\\", "/")
        if page.get("doc_name") and not page.get("document_id"):
            page["document_id"] = page.get("doc_name")
    return pages


def _save_conversation(
    conv: Conversation,
    final_content: str,
    decorated_ref: dict,
    model_name: str,
    message_id: str,
) -> None:
    """保存 assistant 回复与引用到 Conversation 记录。"""
    if not conv.message:
        conv.message = []
    if isinstance(conv.message, str):
        conv.message = json.loads(conv.message)
    conv.message.append({
        "role": "assistant",
        "content": final_content,
        "created_at": time.time(),
        "id": message_id,
    })
    if not conv.reference:
        conv.reference = []
    if isinstance(conv.reference, str):
        conv.reference = json.loads(conv.reference)
    conv.reference.append(decorated_ref)
    conv.message = json.dumps(conv.message, ensure_ascii=False)
    conv.reference = json.dumps(conv.reference, ensure_ascii=False)
    conv.model = model_name
    conv.save()
    logger.info(
        "会话保存成功 conv_id={} model={} answer_len={} ref_chunks={}",
        conv.id, model_name, len(final_content), len(decorated_ref.get("chunks", [])),
    )
