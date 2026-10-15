"""助理配置业务调用门面。"""

from __future__ import annotations

# 3. 本地应用
from __001__rag.assistant.base import AssistantConfig
from __001__rag.assistant.factory import resolve_assistant_config
from __001__rag.cache.manager import CacheManager
from __001__rag.models import PromptConfig


class AssistantService:
    """对业务层暴露统一的助理配置获取入口。

    设计模式与 rag.llm.service.LLMService 对齐：
    - 静态方法，无需实例化
    - 内部委托给 factory 层做 DB 解析
    """

    @staticmethod
    def prompt_row_to_dict(row) -> dict:
        """将 PromptConfig 行转换为与 get_task_config 兼容的 dict。

        供需要直接查询 PromptConfig 表（如按 section_name 匹配）的调用方使用。
        """
        if row is None:
            return {}

        llm_setting = getattr(row, "llm_setting", None) or {}
        if not isinstance(llm_setting, dict):
            llm_setting = {}

        extra_params = getattr(row, "extra_params", None) or {}
        if not isinstance(extra_params, dict):
            extra_params = {}
        extra_params = extra_params.copy()

        max_tokens = getattr(row, "max_tokens", None)
        if max_tokens is None:
            max_tokens = llm_setting.get("max_tokens")
        for key, value in llm_setting.items():
            if key not in {"temperature", "top_p", "max_tokens"} and key not in extra_params:
                extra_params[key] = value

        model_name = getattr(row, "model_name", None)
        return {
            "system_prompt": (getattr(row, "system_prompt", None) or "").strip() or None,
            "user_prompt_template": (getattr(row, "user_prompt_template", None) or "").strip() or None,
            "model_name": (model_name or "").strip() or None if model_name else None,
            "temperature": llm_setting.get("temperature"),
            "top_p": llm_setting.get("top_p"),
            "max_tokens": max_tokens,
            "extra_params": extra_params,
        }

    @staticmethod
    def get_config(assistant_key: str) -> AssistantConfig:
        """按 assistant_key 获取归一化助理配置。

        Args:
            assistant_key: 助理唯一键（如 "chat"、"customer_service"）。

        Returns:
            归一化的 AssistantConfig dataclass。

        Raises:
            AssistantConfigError: 助理不存在或已禁用。
        """
        return resolve_assistant_config(assistant_key)

    @staticmethod
    def get_llm_settings(assistant_key: str) -> dict:
        """按 assistant_key 仅获取 LLM 调用所需的模型参数。

        返回的字典可直接用于 KeywordExtractor、QuestionGenerator 等组件。

        Args:
            assistant_key: 助理唯一键。

        Returns:
            dict with keys: model_name, temperature, top_p, max_tokens, extra_params.
        """
        config = resolve_assistant_config(assistant_key)
        return {
            "model_name": config.model_name,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "max_tokens": config.max_tokens,
            "extra_params": config.extra_params,
        }

    @staticmethod
    def get_task_config(assistant_key: str) -> dict:
        """按 assistant_key 获取后台任务所需的完整配置（提示词 + 模型设置）。

        返回格式统一，可直接用于 KeywordExtractor、QuestionGenerator 等组件。

        Args:
            assistant_key: 助理唯一键。

        Returns:
            dict with keys: model_name, temperature, top_p, max_tokens,
            extra_params, system_prompt, user_prompt_template.

        Raises:
            AssistantConfigError: 助理不存在或已禁用。
        """
        config = resolve_assistant_config(assistant_key)
        return {
            "model_name": config.model_name,
            "temperature": config.temperature,
            "top_p": config.top_p,
            "max_tokens": config.max_tokens,
            "extra_params": config.extra_params,
            "system_prompt": config.system_prompt,
            "user_prompt_template": config.user_prompt_template,
        }

    @staticmethod
    def invalidate_cache(assistant_key: str | None = None) -> None:
        """手动清除助理配置缓存。

        通常由 ORM 信号自动触发，此方法供管理后台或测试手动调用。

        Args:
            assistant_key: 指定清除某个助理；为 None 时清除全部助理缓存。
        """
        CacheManager.invalidate_assistant_config(assistant_key)
