"""ORM 信号配置 — 模型变更时自动清除对应 Redis 缓存。

通过 ``connect_cache_signals()`` 在 ``RagConfig.ready()`` 中调用一次，
为关键模型注册 ``post_save`` / ``post_delete`` 处理器。
"""

from __future__ import annotations

# 2. 第三方库
from django.db.models.signals import post_delete, post_save
from loguru import logger


def _on_assistant_config_changed(sender, instance, **kwargs):
    """AssistantConfig 保存或删除 → 清除该助理的缓存并重新预热。"""
    from __001__rag.cache.manager import CacheManager

    assistant_key = getattr(instance, "assistant_key", None)
    if assistant_key:
        CacheManager.invalidate_assistant_config(assistant_key)
        CacheManager.prewarm_assistant_config(assistant_key)


def _on_prompt_config_changed(sender, instance, **kwargs):
    """PromptConfig 保存或删除 → 清除提示词缓存 + 级联清除所有助理缓存 + 重新预热。

    级联原因：``resolve_assistant_config`` 将提示词内容嵌入
    AssistantConfig dataclass 后缓存，因此任何 PromptConfig 变更
    都会导致已缓存的助理配置中的 system_prompt / user_prompt_template 过期。
    """
    from __001__rag.cache.manager import CacheManager

    config_key = getattr(instance, "config_key", None)

    # 1. 清除该提示词自身的缓存（含级联清除全部助理缓存）
    CacheManager.invalidate_prompt(config_key)

    # 2. 如果变更的是 citation 提示词，额外清除专用缓存键
    if config_key == "citation":
        CacheManager.invalidate_citation_prompt()

    # 3. 兼容现有 GB 分块进程内缓存
    try:
        from __001__rag.chunk.utils.pdf_llm import clear_gb_chunk_config_cache, is_gb_chunk_related_key
        if is_gb_chunk_related_key(config_key):
            clear_gb_chunk_config_cache()
    except Exception:
        pass

    # 4. 重新预热全部助理配置（含嵌入的提示词）+ citation
    try:
        CacheManager._prewarm_assistant_configs()
        CacheManager._prewarm_citation_prompt()
    except Exception:
        logger.info("PromptConfig 变更后助理配置重新预热失败")

    logger.info("PromptConfig 变更触发缓存级联清除并重新预热 config_key={}", config_key)


def _on_llm_changed(sender, instance, **kwargs):
    """LLM 或 LLMFactories 保存或删除 → 清除全部 LLM 配置缓存并重新预热。"""
    try:
        from __001__rag.llm.factory import invalidate_llm_config_cache
        invalidate_llm_config_cache()
    except Exception:
        logger.info("LLM 缓存清除失败")

    try:
        from __001__rag.cache.manager import CacheManager
        CacheManager._prewarm_llm_configs()
    except Exception:
        logger.info("LLM 配置缓存重新预热失败")


def _on_intention_type_changed(sender, instance, **kwargs):
    """IntentionType 保存或删除 → 清除意图识别配置缓存并重新预热。"""
    try:
        from __001__rag.intent.service import invalidate_intent_config_cache
        invalidate_intent_config_cache()
    except Exception:
        logger.info("意图识别缓存清除失败")

    try:
        from __001__rag.cache.manager import CacheManager
        CacheManager.prewarm_intent_config()
    except Exception:
        logger.info("意图识别配置缓存重新预热失败")


def connect_cache_signals() -> None:
    """连接所有缓存失效信号（在 AppConfig.ready 中调用一次）。"""
    from __001__rag.models import (
        AssistantConfig,
        IntentionType,
        LLM,
        LLMFactories,
        PromptConfig,
    )

    # AssistantConfig
    post_save.connect(_on_assistant_config_changed, sender=AssistantConfig)
    post_delete.connect(_on_assistant_config_changed, sender=AssistantConfig)

    # PromptConfig（级联清除助理缓存）
    post_save.connect(_on_prompt_config_changed, sender=PromptConfig)
    post_delete.connect(_on_prompt_config_changed, sender=PromptConfig)

    # LLM + LLMFactories
    post_save.connect(_on_llm_changed, sender=LLM)
    post_delete.connect(_on_llm_changed, sender=LLM)
    post_save.connect(_on_llm_changed, sender=LLMFactories)
    post_delete.connect(_on_llm_changed, sender=LLMFactories)

    # IntentionType
    post_save.connect(_on_intention_type_changed, sender=IntentionType)
    post_delete.connect(_on_intention_type_changed, sender=IntentionType)

    logger.info("缓存失效信号已连接 models=AssistantConfig, PromptConfig, LLM, LLMFactories, IntentionType")
