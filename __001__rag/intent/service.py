"""意图识别服务。

提供统一的意图识别入口，支持两条路径：
- @ 前缀：直接从 intention_type 表匹配
- 无前缀：通过 LLM 进行意图分类
"""

from __future__ import annotations

# 2. 第三方库
from django.conf import settings
from django.core.cache import cache
from loguru import logger

# 3. 本地应用
from __001__rag.assistant.service import AssistantService
from __001__rag.intent.base import IntentResult
from __001__rag.llm.base import ChatMessage
from __001__rag.llm.service import LLMService
from __001__rag.models import IntentionType
from __001__rag.utils.llm_response import extract_json_from_llm_response

_INTENT_RECOGNITION_ASSISTANT_KEY = "intent_recognition"
_INTENT_CONFIG_CACHE_KEY = "intent:config:intent_recognition"


def _get_intent_config() -> dict:
    """获取意图识别配置（带 Redis 缓存，TTL 5 分钟）。"""
    try:
        cached = cache.get(_INTENT_CONFIG_CACHE_KEY)
        if cached is not None:
            logger.info("加载意图识别配置：缓存命中")
            return cached
    except Exception:
        logger.info("[DEGRADE] 意图识别配置缓存读取失败")

    config = AssistantService.get_task_config(_INTENT_RECOGNITION_ASSISTANT_KEY)
    logger.info("加载意图识别配置：缓存未命中，数据库加载")

    try:
        cache.set(_INTENT_CONFIG_CACHE_KEY, config, timeout=settings.CONFIG_CACHE_TTL)
    except Exception:
        logger.info("[DEGRADE] 意图识别配置缓存写入失败")

    return config


def invalidate_intent_config_cache() -> None:
    """清除意图识别配置缓存（供管理后台配置变更时调用）。"""
    try:
        cache.delete(_INTENT_CONFIG_CACHE_KEY)
        logger.info("意图识别配置缓存已清除")
    except Exception:
        logger.info("[DEGRADE] 意图识别配置缓存清除失败")


def _build_main_category(intents) -> str:
    """构建 system prompt 中 {main_category} 占位符的内容。"""
    lines: list[str] = []
    for i, row in enumerate(intents, 1):
        name = row.intention or ""
        desc = row.intention_description or ""
        lines.append(f"{i}. **{name}**：{desc}")
    return "\n".join(lines)


def _match_intent_kb_ids(primary_intent: str) -> tuple[str | None, list[str]]:
    """将 LLM 输出的 primary_intent 匹配到 IntentionType 表。

    Returns:
        (matched_intent_name, kb_ids) — name 为 None 表示未匹配。
    """
    if not primary_intent:
        return None, []
    row = IntentionType.objects.filter(
        intention=primary_intent, status="1"
    ).first()
    if not row:
        return None, []
    kb_ids = row.kb_ids if isinstance(row.kb_ids, list) else []
    return row.intention, kb_ids


class IntentService:
    """意图识别服务静态门面。"""

    @staticmethod
    def recognize(question: str) -> IntentResult:
        """识别用户问题的意图，返回匹配的 kb_ids 和清理后的问题。

        Args:
            question: 用户输入的问题文本。

        Returns:
            IntentResult: 包含 kb_ids、intent_name、actual_question。
        """
        if not question or not question.strip():
            logger.info("意图识别：用户问题为空，跳过识别")
            return IntentResult(actual_question=question)

        # 路径 A：@ 前缀直接匹配
        if question.startswith("@"):
            return IntentService._recognize_by_prefix(question)

        # 路径 B：LLM 意图识别
        return IntentService._recognize_by_llm(question)

    @staticmethod
    def _recognize_by_prefix(question: str) -> IntentResult:
        """@ 前缀路径：切分空格，匹配意图名称。

        格式：@意图名称 实际问题内容
        """
        parts = question.split(" ", 1)
        prefix = parts[0]
        intent_name = prefix[1:]  # 去掉 @
        actual_question = parts[1] if len(parts) > 1 else ""

        if not intent_name:
            logger.info("意图识别：@ 后无有效意图名称，使用 fallback")
            return IntentResult(actual_question=actual_question or question)

        logger.info("意图识别：@ 前缀模式，意图名称={}", intent_name)

        row = IntentionType.objects.filter(
            intention=intent_name, status="1"
        ).first()

        if row and row.kb_ids:
            kb_ids = row.kb_ids if isinstance(row.kb_ids, list) else []
            logger.info(
                "意图识别：匹配成功 意图名称={} kb_ids={}",
                intent_name, kb_ids,
            )
            return IntentResult(
                kb_ids=kb_ids,
                intent_name=intent_name,
                actual_question=actual_question,
            )

        logger.info(
            "意图识别：未匹配到启用的意图 意图名称={}，使用 fallback",
            intent_name,
        )
        return IntentResult(actual_question=actual_question or question)

    @staticmethod
    def _recognize_by_llm(question: str) -> IntentResult:
        """LLM 意图识别路径：使用 intent_recognition assistant 调用 LLM 分类。"""
        try:
            logger.info("意图识别：LLM 模式，问题长度={}", len(question))

            # 1. 加载意图识别 assistant 配置
            task_config = _get_intent_config()
            system_prompt = task_config.get("system_prompt") or ""
            user_prompt_template = task_config.get("user_prompt_template") or ""
            model_name = task_config.get("model_name") or ""
            temperature = task_config.get("temperature")
            top_p = task_config.get("top_p")
            max_tokens = task_config.get("max_tokens")
            extra_params = task_config.get("extra_params") or {}

            logger.info(
                "意图识别：加载 assistant 配置 assistant_key={} model={} "
                "system_prompt_len={} user_tpl_len={}",
                _INTENT_RECOGNITION_ASSISTANT_KEY,
                model_name,
                len(system_prompt),
                len(user_prompt_template),
            )

            # 2. 获取启用的意图
            intents = list(IntentionType.objects.filter(status="1"))
            if not intents:
                logger.info("意图识别：没有启用的意图，使用 fallback")
                return IntentResult(actual_question=question)

            logger.info("意图识别：启用意图数量={}", len(intents))

            # 3. 构造 {main_category}
            main_category = _build_main_category(intents)

            # 4. 填充 prompt 占位符
            filled_system = system_prompt.replace("{main_category}", main_category)
            user_content = question
            if user_prompt_template and "{input}" in user_prompt_template:
                user_content = user_prompt_template.replace("{input}", question)

            # 5. 调用 LLM
            messages = [
                ChatMessage(role="system", content=filled_system),
                ChatMessage(role="user", content=user_content),
            ]

            response = LLMService.chat(
                messages=messages,
                model_name=model_name,
                temperature=temperature,
                top_p=top_p,
                max_tokens=max_tokens,
                extra=extra_params,
            )

            raw_output = response.content
            logger.info(
                "意图识别：LLM 返回 tokens={} raw_len={} raw_preview={}",
                response.total_tokens,
                len(raw_output),
                raw_output[:200] if raw_output else "",
            )

            # 6. 解析输出
            parsed = extract_json_from_llm_response(raw_output)
            if not parsed:
                logger.info("意图识别：LLM 输出解析失败，使用 fallback")
                return IntentResult(actual_question=question)

            primary_intent = parsed.get("primary_intent") or ""
            confidence = parsed.get("confidence")
            logger.info(
                "意图识别：LLM 识别结果 primary_intent={} confidence={}",
                primary_intent, confidence,
            )

            if not primary_intent:
                logger.info("意图识别：LLM 返回的 primary_intent 为空，使用 fallback")
                return IntentResult(actual_question=question)

            # 7. 匹配意图表获取 kb_ids
            matched_name, kb_ids = _match_intent_kb_ids(primary_intent)
            if not matched_name:
                logger.info(
                    "意图识别：primary_intent={} 未匹配到启用意图，使用 fallback",
                    primary_intent,
                )
                return IntentResult(actual_question=question)

            logger.info(
                "意图识别：匹配成功 intent={} kb_ids={}", matched_name, kb_ids,
            )
            return IntentResult(
                kb_ids=kb_ids,
                intent_name=matched_name,
                actual_question=question,
            )

        except Exception:
            logger.exception("意图识别：LLM 识别异常，使用 fallback")
            return IntentResult(actual_question=question)
