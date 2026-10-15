"""LLM 模型配置解析与实例工厂。"""

from __future__ import annotations

# 2. 第三方库
from django.conf import settings
from django.core.cache import cache
from django.db import DatabaseError
from loguru import logger

# 3. 本地应用
from __001__rag.llm.base import BaseChatModel, BaseEmbeddingModel, BaseRerankModel, ModelConfig, ModelType
from __001__rag.llm.exceptions import LLMConfigError
from __001__rag.llm.openai_compat import (
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
    OpenAICompatibleRerankModel,
)
from __001__rag.llm.utils import derive_rerank_endpoint, normalize_api_base
from __001__rag.models import LLM as LLMModel
from __001__rag.models import LLMFactories
from __001__rag.utils.secrets import reveal_secret

_LLM_CONFIG_CACHE_KEY_PREFIX = "llm:config:"


def split_model_name_and_factory(model_name: str | None) -> tuple[str | None, str | None]:
    """解析 `model@factory` 格式的模型名。"""
    if not model_name:
        return None, None

    model_name = model_name.strip()
    if "@" not in model_name:
        return model_name, None

    model, factory = model_name.rsplit("@", 1)
    model = model.strip() or None
    factory = factory.strip() or None
    return model, factory


def resolve_model_config(model_name: str | None, model_type: ModelType) -> ModelConfig:
    """按 DB 优先、settings 回退的规则解析模型配置（带 Redis 缓存）。"""
    cache_key = f"{_LLM_CONFIG_CACHE_KEY_PREFIX}{model_name or ''}:{model_type}"

    # 尝试从 Redis 缓存获取
    try:
        cached = cache.get(cache_key)
        if cached is not None:
            logger.info("加载 LLM 配置：缓存命中 model={} type={}", model_name, model_type)
            return cached
    except Exception:
        logger.info("[DEGRADE] LLM 配置缓存读取失败 cache_key={}", cache_key)

    # 缓存未命中，走原有 DB 查询逻辑
    requested_model = model_name or _default_model_name(model_type)
    db_config = _resolve_from_db(requested_model, model_type)
    if db_config is not None:
        config = db_config
        logger.info("加载 LLM 配置：缓存未命中，数据库加载 model={} type={}", model_name, model_type)
    else:
        config = _resolve_from_settings(requested_model, model_type)
        logger.info("加载 LLM 配置：缓存未命中，数据库未找到，settings 兜底 model={} type={}", model_name, model_type)

    # 写入 Redis 缓存
    try:
        cache.set(cache_key, config, timeout=settings.CONFIG_CACHE_TTL)
    except Exception:
        logger.info("[DEGRADE] LLM 配置缓存写入失败 cache_key={}", cache_key)

    return config


def invalidate_llm_config_cache() -> None:
    """清除所有 LLM 配置缓存（供管理后台配置变更时调用）。"""
    try:
        # django-redis 支持 delete_pattern 清除前缀匹配的键
        cache.delete_pattern(f"{_LLM_CONFIG_CACHE_KEY_PREFIX}*")
        logger.info("LLM 配置缓存已清除")
    except Exception:
        logger.info("[DEGRADE] LLM 配置缓存清除失败")


def build_chat_model(model_name: str | None = None) -> BaseChatModel:
    """初始化聊天模型。"""
    return OpenAICompatibleChatModel(resolve_model_config(model_name, "chat"))


def build_embedding_model(model_name: str | None = None) -> BaseEmbeddingModel:
    """初始化向量模型。"""
    return OpenAICompatibleEmbeddingModel(resolve_model_config(model_name, "embedding"))


def build_rerank_model(model_name: str | None = None) -> BaseRerankModel:
    """初始化重排模型。"""
    return OpenAICompatibleRerankModel(resolve_model_config(model_name, "rerank"))


def _resolve_from_db(model_name: str | None, model_type: ModelType) -> ModelConfig | None:
    name, factory = split_model_name_and_factory(model_name)
    try:
        llm_query = LLMModel.objects.filter(status="1", model_type__icontains=model_type)
        if name:
            llm_query = llm_query.filter(llm_name=name)
        if factory:
            llm_query = llm_query.filter(fid=factory)

        llm = llm_query.order_by("fid", "llm_name").first()
        if not llm:
            return None

        factory_config = LLMFactories.objects.filter(status="1", name=llm.fid).first()
    except DatabaseError:
        logger.exception("[DEGRADE] LLM 配置数据库查询失败 model_type={} name={}", model_type, name)
        return None

    fallback_api_base, fallback_api_key = _fallback_endpoint_credentials()
    api_base = getattr(factory_config, "api_base", None) or fallback_api_base
    api_key = reveal_secret(getattr(factory_config, "api_key", None)) or fallback_api_key
    return _build_config(
        model_name=llm.llm_name,
        model_type=model_type,
        api_base=api_base,
        api_key=api_key,
        factory=llm.fid,
    )


def _resolve_from_settings(model_name: str | None, model_type: ModelType) -> ModelConfig:
    name, factory = split_model_name_and_factory(model_name or _default_model_name(model_type))
    api_base, api_key = _fallback_endpoint_credentials()
    return _build_config(
        model_name=name,
        model_type=model_type,
        api_base=api_base,
        api_key=api_key,
        factory=factory,
    )


def _build_config(
    *,
    model_name: str | None,
    model_type: ModelType,
    api_base: str | None,
    api_key: str | None,
    factory: str | None = None,
) -> ModelConfig:
    if not model_name:
        raise LLMConfigError(f"{model_type} 模型名称不能为空")
    if not api_base:
        raise LLMConfigError(f"{model_type} 模型 api_base 不能为空")

    normalized_api_base = normalize_api_base(api_base)
    endpoint = derive_rerank_endpoint(normalized_api_base) if model_type == "rerank" else normalized_api_base
    return ModelConfig(
        model_name=model_name,
        model_type=model_type,
        api_base=normalized_api_base,
        api_key=api_key,
        factory=factory,
        endpoint=endpoint,
    )


def _default_model_name(model_type: ModelType) -> str | None:
    if model_type == "chat":
        return getattr(settings, "LLM_MODEL_ID", None) or getattr(settings, "EXTRACT_LLM_MODEL", None)
    if model_type == "embedding":
        return getattr(settings, "EMBEDDING_MODEL_ID", None)
    if model_type == "rerank":
        return getattr(settings, "RERANK_MODEL_ID", None)
    return None


def _fallback_endpoint_credentials() -> tuple[str | None, str | None]:
    api_base = (
        getattr(settings, "EXTRACT_LLM_URL", None)
        or getattr(settings, "DASHSCOPE_BASE_URL", None)
    )
    api_key = (
        getattr(settings, "EXTRACT_LLM_KEY", None)
        or getattr(settings, "DASHSCOPE_API_KEY", None)
    )
    return api_base, api_key
