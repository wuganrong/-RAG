"""关键词提取模块。

提供 KeywordExtractor 类（纯逻辑）和 create_keyword_extractor 辅助函数（从 DB 获取配置）。
"""

from __future__ import annotations

# 2. 第三方库
from loguru import logger

# 3. 本地应用
from __001__rag.assistant import AssistantService

from .extractor import KeywordExtractor

__all__ = ["KeywordExtractor", "create_keyword_extractor"]


def create_keyword_extractor(assistant_key: str = "keyword_extraction") -> KeywordExtractor:
    """从数据库配置创建关键词提取器。

    读取 assistant_config 获取模型参数和提示词。

    Args:
        assistant_key: 助理配置键，默认 "keyword_extraction"

    Returns:
        配置好的 KeywordExtractor 实例
    """
    task_config = AssistantService.get_task_config(assistant_key)
    model_config = {
        "model_name": task_config.get("model_name"),
        "temperature": task_config.get("temperature"),
        "top_p": task_config.get("top_p"),
        "max_tokens": task_config.get("max_tokens"),
        "extra_params": task_config.get("extra_params") or {},
    }
    return KeywordExtractor(
        model_config=model_config,
        system_prompt=task_config.get("system_prompt") or None,
    )
