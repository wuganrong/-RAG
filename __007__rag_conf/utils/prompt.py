"""提示词配置接口辅助函数。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from loguru import logger

# 3. 本地应用
from __001__rag.models import PromptConfig


def list_prompt_configs() -> list[dict[str, str]]:
    """查询所有启用状态的提示词配置，按创建时间升序返回 label/value 格式列表。

    Returns:
        list: 每项格式为 {"label": section_name, "value": config_key}
    """
    configs = (
        PromptConfig.objects.filter(status="1")
        .values("config_key", "section_name")
        .order_by("create_date")
    )
    return [
        {"label": item["section_name"] or "", "value": item["config_key"]}
        for item in configs
    ]


def get_prompt_detail(config_key: str) -> dict[str, str] | None:
    """根据 config_key 获取启用状态的提示词详情。

    Args:
        config_key: 提示词模板唯一键

    Returns:
        包含 config_key、section_name、system_prompt、user_prompt_template 的字典；
        不存在或未启用时返回 None
    """
    try:
        prompt = PromptConfig.objects.get(config_key=config_key, status="1")
    except PromptConfig.DoesNotExist:
        logger.info("提示词模板不存在或未启用 config_key={}", config_key)
        return None

    return {
        "config_key": prompt.config_key,
        "section_name": prompt.section_name or "",
        "system_prompt": prompt.system_prompt or "",
        "user_prompt_template": prompt.user_prompt_template or "",
    }


def get_prompt_detail_by_id(prompt_id: int) -> dict[str, Any] | None:
    """根据主键获取提示词详情（不限启用状态，供管理端编辑）。"""
    try:
        prompt = PromptConfig.objects.get(id=prompt_id)
    except PromptConfig.DoesNotExist:
        logger.info("提示词模板不存在 prompt_id={}", prompt_id)
        return None

    return {
        "id": prompt.id,
        "config_key": prompt.config_key,
        "section_name": prompt.section_name or "",
        "system_prompt": prompt.system_prompt or "",
        "user_prompt_template": prompt.user_prompt_template or "",
        "status": prompt.status or "1",
    }
