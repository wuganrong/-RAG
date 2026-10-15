"""助理配置解析与实例工厂。

按 assistant_key 从 DB 读取 AssistantConfig + PromptConfig，组装为归一化配置。
支持 Redis 缓存：首次从 DB 加载后写入缓存，后续请求直接命中。
"""

from __future__ import annotations

# 2. 第三方库
from django.db import DatabaseError
from loguru import logger

# 3. 本地应用
from __001__rag.assistant.base import AssistantConfig
from __001__rag.models import AssistantConfig as AssistantConfigModel
from __001__rag.models import PromptConfig


class AssistantConfigError(ValueError):
    """助理配置不可用。"""


def resolve_assistant_config(assistant_key: str) -> AssistantConfig:
    """按 assistant_key 解析助理配置（带 Redis 缓存）。

    首次从 DB 加载后写入缓存，后续请求直接命中缓存。
    配置变更时由 ORM 信号自动清除缓存，下次请求重建。

    Raises:
        AssistantConfigError: 助理不存在或已禁用。
    """
    if not assistant_key:
        raise AssistantConfigError("assistant_key 不能为空")

    # ① 尝试从 Redis 缓存获取
    from __001__rag.cache.manager import CacheManager
    cached = CacheManager.get_assistant_config(assistant_key)
    if cached is not None:
        logger.info("加载助理配置：缓存命中 assistant_key={}", assistant_key)
        return cached

    # ② 缓存未命中，从 DB 加载
    config = _resolve_from_db(assistant_key)
    logger.info("加载助理配置：缓存未命中，数据库加载 assistant_key={}", assistant_key)

    # ③ 写入 Redis 缓存
    CacheManager.set_assistant_config(assistant_key, config)

    return config


def resolve_assistant_config_nocache(assistant_key: str) -> AssistantConfig:
    """按 assistant_key 直接从 DB 解析助理配置，绕过缓存。

    供缓存预热和管理后台使用，确保读取最新数据。
    """
    if not assistant_key:
        raise AssistantConfigError("assistant_key 不能为空")
    return _resolve_from_db(assistant_key)


def _resolve_from_db(assistant_key: str) -> AssistantConfig:
    """从 DB 查询并组装 AssistantConfig（内部函数，无缓存逻辑）。"""
    try:
        row = AssistantConfigModel.objects.filter(
            assistant_key=assistant_key, status="1"
        ).first()
    except DatabaseError as exc:
        raise AssistantConfigError(f"查询助理配置失败: {exc}") from exc

    if row is None:
        raise AssistantConfigError(f"助理配置不存在或已禁用 assistant_key={assistant_key}")

    # 解析模型参数
    llm_setting = row.llm_setting if isinstance(row.llm_setting, dict) else {}
    extra_params = row.extra_params if isinstance(row.extra_params, dict) else {}

    # 解析关联提示词
    system_prompt = None
    user_prompt_template = None
    if row.prompt_config_key:
        try:
            pc = PromptConfig.objects.filter(
                config_key=row.prompt_config_key, status="1"
            ).first()
            if pc:
                system_prompt = pc.system_prompt or None
                user_prompt_template = pc.user_prompt_template or None
                logger.info(
                    "PromptConfig 已关联 assistant_key={} prompt_config_key={}",
                    assistant_key, row.prompt_config_key,
                )
            else:
                logger.info(
                    "助理关联的 PromptConfig 未找到 assistant_key={} prompt_config_key={}",
                    assistant_key, row.prompt_config_key,
                )
        except DatabaseError:
            logger.exception("查询 PromptConfig 失败 assistant_key={}", assistant_key)

    kb_ids = row.kb_ids if isinstance(row.kb_ids, list) else []

    return AssistantConfig(
        assistant_key=row.assistant_key,
        assistant_name=row.assistant_name,
        assistant_type=row.assistant_type,
        model_name=row.model_name or None,
        temperature=float(llm_setting.get("temperature", 0.1)),
        top_p=llm_setting.get("top_p"),
        extra_params=extra_params,
        system_prompt=system_prompt,
        user_prompt_template=user_prompt_template,
        prompt_config_key=row.prompt_config_key,
        retrieval_method=row.retrieval_method,
        similarity_threshold=float(row.similarity_threshold),
        vector_similarity_weight=float(row.vector_similarity_weight),
        top_n=int(row.top_n),
        rerank_id=row.rerank_id,
        kb_ids=kb_ids,
        memory_rounds=int(row.memory_rounds),
        top_k=int(row.top_k),
        prologue=row.prologue,
    )


def build_assistant_config(assistant_key: str) -> AssistantConfig:
    """resolve_assistant_config 的别名。"""
    return resolve_assistant_config(assistant_key)
