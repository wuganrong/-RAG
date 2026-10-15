"""统一缓存管理器。

封装 django.core.cache（django-redis）操作，提供按业务域的缓存读写与失效方法。
所有操作对 Redis 故障静默降级，不影响正常业务流程。
"""

from __future__ import annotations

# 2. 第三方库
from django.conf import settings
from django.core.cache import cache
from loguru import logger

# 3. 本地应用
from __001__rag.llm.factory import invalidate_llm_config_cache, resolve_model_config
from __001__rag.models import AssistantConfig as AssistantConfigModel
from __001__rag.models import LLM as LLMModel
from __001__rag.models import PromptConfig


class CacheManager:
    """统一缓存管理器。

    缓存键约定：
    - ``assistant:config:{assistant_key}`` — 助理配置（含嵌入的提示词）
    - ``prompt:{config_key}``             — 独立提示词缓存
    - ``prompt:citation``                 — 引用提示词专用键

    设计原则：
    - 所有 Redis 操作 try/except 包裹，故障时降级为 DB 直查
    - 使用 django.core.cache（django-redis），与 LLM 配置缓存共享后端
    """

    # ── 缓存键前缀 ──
    ASSISTANT_CONFIG_PREFIX = "assistant:config:"
    PROMPT_PREFIX = "prompt:"
    CITATION_PROMPT_KEY = "prompt:citation"

    # ────────────────────────── 底层操作 ──────────────────────────

    @staticmethod
    def get(key: str):
        """读缓存，失败静默返回 None。"""
        try:
            return cache.get(key)
        except Exception:
            logger.info("缓存读取失败 key={}", key)
            return None

    @staticmethod
    def set(key: str, value, timeout: int | None = None) -> None:
        """写缓存，失败静默。"""
        try:
            cache.set(key, value, timeout=timeout)
        except Exception:
            logger.info("缓存写入失败 key={}", key)

    @staticmethod
    def delete(key: str) -> None:
        """删除单个缓存键，失败静默。"""
        try:
            cache.delete(key)
        except Exception:
            logger.info("缓存删除失败 key={}", key)

    @staticmethod
    def delete_pattern(pattern: str) -> None:
        """按模式批量删除缓存（django-redis SCAN），失败静默。"""
        try:
            cache.delete_pattern(pattern)
        except Exception:
            logger.info("缓存模式删除失败 pattern={}", pattern)

    # ────────────────────── 助理配置缓存 ──────────────────────────

    @classmethod
    def get_assistant_config(cls, assistant_key: str):
        """读取助理配置缓存，返回 AssistantConfig dataclass 或 None。"""
        return cls.get(f"{cls.ASSISTANT_CONFIG_PREFIX}{assistant_key}")

    @classmethod
    def set_assistant_config(cls, assistant_key: str, config, timeout: int | None = None) -> None:
        """写入助理配置缓存。"""
        cls.set(
            f"{cls.ASSISTANT_CONFIG_PREFIX}{assistant_key}",
            config,
            timeout=timeout if timeout is not None else settings.CONFIG_CACHE_TTL,
        )

    @classmethod
    def invalidate_assistant_config(cls, assistant_key: str | None = None) -> None:
        """清除助理配置缓存。

        Args:
            assistant_key: 指定清除某个助理；为 None 时清除全部助理缓存。
        """
        if assistant_key:
            cls.delete(f"{cls.ASSISTANT_CONFIG_PREFIX}{assistant_key}")
            logger.info("助理配置缓存已清除 assistant_key={}", assistant_key)
        else:
            cls.delete_pattern(f"{cls.ASSISTANT_CONFIG_PREFIX}*")
            logger.info("全部助理配置缓存已清除")

    # ────────────────────── 提示词缓存 ──────────────────────────

    @classmethod
    def get_prompt(cls, config_key: str):
        """读取提示词缓存，返回 dict 或 None。"""
        return cls.get(f"{cls.PROMPT_PREFIX}{config_key}")

    @classmethod
    def set_prompt(cls, config_key: str, prompt_dict: dict, timeout: int | None = None) -> None:
        """写入提示词缓存。"""
        cls.set(
            f"{cls.PROMPT_PREFIX}{config_key}",
            prompt_dict,
            timeout=timeout if timeout is not None else settings.CONFIG_CACHE_TTL,
        )

    @classmethod
    def invalidate_prompt(cls, config_key: str | None = None) -> None:
        """清除提示词缓存。

        Args:
            config_key: 指定清除某个提示词；为 None 时清除全部提示词缓存。

        注意：提示词嵌入在助理配置缓存对象中，因此同时清除全部助理缓存。
        """
        if config_key:
            cls.delete(f"{cls.PROMPT_PREFIX}{config_key}")
            logger.info("提示词缓存已清除 config_key={}", config_key)
        else:
            cls.delete_pattern(f"{cls.PROMPT_PREFIX}*")
            logger.info("全部提示词缓存已清除")

        # 提示词变更 → 助理配置缓存中的 system_prompt / user_prompt_template 过期
        cls.invalidate_assistant_config()

    # ──────────────────── 引用提示词缓存 ──────────────────────────

    @classmethod
    def get_citation_prompt(cls):
        """读取引用提示词缓存，返回 str 或 None。"""
        return cls.get(cls.CITATION_PROMPT_KEY)

    @classmethod
    def set_citation_prompt(cls, text: str, timeout: int | None = None) -> None:
        """写入引用提示词缓存。"""
        cls.set(cls.CITATION_PROMPT_KEY, text, timeout=timeout if timeout is not None else settings.CONFIG_CACHE_TTL)

    @classmethod
    def invalidate_citation_prompt(cls) -> None:
        """清除引用提示词缓存。"""
        cls.delete(cls.CITATION_PROMPT_KEY)
        logger.info("引用提示词缓存已清除")

    # ────────────────────── 全量失效 ──────────────────────────

    @classmethod
    def invalidate_all_related(cls) -> None:
        """清除所有助理 + 提示词 + LLM + 意图缓存并重新预热（全量刷新用）。"""
        cls.invalidate_prompt()  # 含助理缓存级联清除
        cls.invalidate_citation_prompt()

        try:
            invalidate_llm_config_cache()
        except Exception:
            logger.info("LLM 配置缓存清除失败")

        try:
            # 延迟导入：rag.intent.service → rag.assistant.service → rag.cache.manager（循环依赖）
            from __001__rag.intent.service import invalidate_intent_config_cache
            invalidate_intent_config_cache()
        except Exception:
            logger.info("意图识别配置缓存清除失败")

        logger.info("全部关联缓存已清除，开始重新预热")

        # 清除后统一预热
        cls.prewarm_all()

    # ────────────────────── 按需预热（信号回调） ──────────────────

    @classmethod
    def prewarm_assistant_config(cls, assistant_key: str) -> None:
        """预热单个助理配置（供 ORM 信号回调使用）。"""
        # 延迟导入：rag.assistant.factory → rag.assistant.__init__ → rag.assistant.service → rag.cache.manager（循环依赖）
        from __001__rag.assistant.factory import resolve_assistant_config_nocache

        try:
            config = resolve_assistant_config_nocache(assistant_key)
            cls.set_assistant_config(assistant_key, config)
            logger.info("助理配置缓存已重新预热 assistant_key={}", assistant_key)
        except Exception:
            logger.info("助理配置缓存预热跳过（配置不存在或已禁用） assistant_key={}", assistant_key)

    @classmethod
    def prewarm_intent_config(cls) -> None:
        """预热意图识别配置（供 ORM 信号回调使用）。"""
        try:
            # 延迟导入：rag.intent.service → rag.assistant.service → rag.cache.manager（循环依赖）
            from __001__rag.intent.service import _get_intent_config

            _get_intent_config()
            logger.info("意图识别配置缓存已重新预热")
        except Exception:
            logger.info("意图识别配置缓存预热失败")

    # ────────────────────── 启动预热 ──────────────────────────

    @classmethod
    def prewarm_all(cls) -> None:
        """启动时批量预热缓存。

        在 ``load_dicts()`` 之后调用，需要 DB 连接就绪。
        预热失败不阻塞启动，首次请求时按需从 DB 加载并缓存。
        """
        try:
            cls._prewarm_assistant_configs()
        except Exception:
            logger.info("助理配置缓存预热失败，将在首次请求时按需加载")

        try:
            cls._prewarm_citation_prompt()
        except Exception:
            logger.info("引用提示词缓存预热失败")

        try:
            cls._prewarm_llm_configs()
        except Exception:
            logger.info("LLM 配置缓存预热失败，将在首次请求时按需加载")

        try:
            cls._prewarm_intent_config()
        except Exception:
            logger.info("意图识别配置缓存预热失败，将在首次请求时按需加载")

    @classmethod
    def _prewarm_assistant_configs(cls) -> None:
        """预热所有启用的助理配置。"""
        # 延迟导入：rag.assistant.factory → rag.assistant.__init__ → rag.assistant.service → rag.cache.manager（循环依赖）
        from __001__rag.assistant.factory import resolve_assistant_config_nocache

        configs = AssistantConfigModel.objects.filter(status="1")
        count = 0
        for row in configs:
            try:
                config = resolve_assistant_config_nocache(row.assistant_key)
                cls.set_assistant_config(row.assistant_key, config)
                count += 1
            except Exception:
                pass
        logger.info("预热助理配置缓存完成 count={}", count)

    @classmethod
    def _prewarm_citation_prompt(cls) -> None:
        """预热引用提示词缓存。"""
        citation = PromptConfig.objects.filter(config_key="citation", status="1").first()
        if citation and citation.system_prompt:
            cls.set_citation_prompt(citation.system_prompt)
            logger.info("预热引用提示词缓存完成")

    @classmethod
    def _prewarm_llm_configs(cls) -> None:
        """预热所有启用的 LLM 模型配置缓存。

        两轮覆盖：
        1. 遍历 LLM 表，按 llm_name + 支持的 model_type 预热
        2. 遍历助理配置的 model_name，覆盖 model@factory 格式
        """
        _MODEL_TYPES = ("chat", "embedding", "rerank")
        count = 0

        # 第一轮：从 LLM 表直接预热
        llm_rows = LLMModel.objects.filter(status="1")
        for row in llm_rows:
            for mt in _MODEL_TYPES:
                if mt in (row.model_type or ""):
                    try:
                        resolve_model_config(row.llm_name, mt)
                        count += 1
                    except Exception:
                        pass

        # 第二轮：从助理配置的 model_name 预热（覆盖 model@factory 格式）
        assistant_rows = AssistantConfigModel.objects.filter(status="1").exclude(
            model_name__isnull=True
        ).exclude(model_name="")
        for row in assistant_rows:
            for mt in _MODEL_TYPES:
                try:
                    resolve_model_config(row.model_name, mt)
                except Exception:
                    pass

        logger.info("预热 LLM 配置缓存完成 count={}", count)

    @classmethod
    def _prewarm_intent_config(cls) -> None:
        """预热意图识别配置缓存。

        调用 _get_intent_config() 触发缓存填充；
        助理配置已在前一步预热，不会穿透到 DB。
        """
        # 延迟导入：rag.intent.service → rag.assistant.service → rag.cache.manager（循环依赖）
        from __001__rag.intent.service import _get_intent_config

        _get_intent_config()
        logger.info("预热意图识别配置缓存完成")
