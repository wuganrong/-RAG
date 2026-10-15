"""问题生成模块。

提供 QuestionGenerator 类（纯逻辑）和 create_question_generator 辅助函数（从 DB 获取配置）。
"""

from __future__ import annotations

# 2. 第三方库
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.assistant import AssistantService
from __001__rag.models import PromptConfig

from .generator import QuestionGenerator

__all__ = ["QuestionGenerator", "create_question_generator"]


def create_question_generator(assistant_key: str = "question_generate") -> QuestionGenerator:
    """从数据库配置创建问题生成器。

    读取 assistant_config 获取模型参数和主提示词，
    读取 prompt_config 获取评估提示词和问题类型指令提示词。

    Args:
        assistant_key: 助理配置键，默认 "question_generate"

    Returns:
        配置好的 QuestionGenerator 实例
    """
    # 1. 获取模型参数和问题生成提示词
    task_config = AssistantService.get_task_config(assistant_key)
    model_config = {
        "model_name": task_config.get("model_name"),
        "temperature": task_config.get("temperature"),
        "top_p": task_config.get("top_p"),
        "max_tokens": task_config.get("max_tokens"),
        "extra_params": task_config.get("extra_params") or {},
    }

    # 2. 获取评估提示词
    prompts: dict[str, str] = {}
    prompts["question_generate_system_prompt"] = task_config.get("system_prompt") or ""

    try:
        assess_config = AssistantService.get_task_config("assess_snippet_complexity")
        prompts["assess_system_prompt"] = assess_config.get("system_prompt") or ""
    except Exception:
        prompts["assess_system_prompt"] = ""

    # 3. 获取问题类型指令提示词（仅存在于 prompt_config）
    instruction_keys = {
        "overview_instruction": "question_overview_instruction",
        "detail_instruction": "question_detail_instruction",
        "mixed_instruction": "question_mixed_instruction",
    }
    for prompt_key, config_key in instruction_keys.items():
        prompts[prompt_key] = _get_prompt_text(config_key) or ""

    embedding_model_name = getattr(settings, "EMBEDDING_MODEL_ID", None)
    return QuestionGenerator(
        model_config=model_config,
        prompts=prompts,
        embedding_model_name=embedding_model_name,
    )


def _get_prompt_text(config_key: str) -> str | None:
    """从 PromptConfig 表读取 system_prompt。"""
    try:
        row = PromptConfig.objects.filter(config_key=config_key, status="1").first()
    except Exception:
        return None
    return (row.system_prompt or "").strip() or None if row else None
