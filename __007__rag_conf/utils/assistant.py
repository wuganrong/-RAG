"""助理配置接口辅助函数。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from loguru import logger

# 3. 本地应用
from __001__rag.models import AssistantConfig, Knowledgebase, PromptConfig


def get_valid_kb_names(kb_ids: list[str]) -> tuple[list[str], list[str]]:
    """根据知识库 ID 列表批量获取有效知识库名称，保持入参顺序。"""
    if not kb_ids:
        return [], []

    kbs = Knowledgebase.objects.filter(id__in=kb_ids, status="1").only("id", "name")
    kb_name_map = {kb.id: kb.name or "" for kb in kbs}

    valid_ids: list[str] = []
    valid_names: list[str] = []
    for kb_id in kb_ids:
        if kb_id not in kb_name_map:
            continue
        valid_ids.append(kb_id)
        valid_names.append(kb_name_map[kb_id])

    return valid_ids, valid_names


def _empty_prompt_config(prompt_config_key: str) -> dict[str, Any]:
    """返回空提示词模板响应。"""
    return {
        "prompt_config_key": prompt_config_key,
        "config_key": prompt_config_key,
        "section_name": "",
        "system_prompt": "",
        "user_prompt_template": "",
        "status": "",
    }


def prompt_config_to_dict(prompt_config: PromptConfig) -> dict[str, Any]:
    """将提示词模板转换为响应字典。"""
    return {
        "prompt_config_key": prompt_config.config_key,
        "config_key": prompt_config.config_key,
        "section_name": prompt_config.section_name or "",
        "system_prompt": prompt_config.system_prompt or "",
        "user_prompt_template": prompt_config.user_prompt_template or "",
        "status": prompt_config.status,
    }


def resolve_prompt_config(prompt_config_key: str) -> dict[str, Any]:
    """获取提示词模板响应字段。"""
    try:
        prompt_config = PromptConfig.objects.get(config_key=prompt_config_key, status="1")
    except PromptConfig.DoesNotExist:
        logger.info("助理配置关联的提示词模板不存在 prompt_config_key={}", prompt_config_key)
        return _empty_prompt_config(prompt_config_key)

    return prompt_config_to_dict(prompt_config)


def build_assistant_config_response(
    config: AssistantConfig,
    *,
    kb_name_map: dict[str, str] | None = None,
    prompt_config_map: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """组装助理配置接口响应，按助理设置、提示引擎、模型设置分组。"""
    kb_ids = config.kb_ids if isinstance(config.kb_ids, list) else []
    if kb_name_map is None:
        valid_kb_ids, kb_names = get_valid_kb_names(kb_ids)
    else:
        valid_kb_ids = [kb_id for kb_id in kb_ids if kb_id in kb_name_map]
        kb_names = [kb_name_map[kb_id] for kb_id in valid_kb_ids]

    prompt_engine = (
        prompt_config_map.get(config.prompt_config_key)
        if prompt_config_map is not None
        else resolve_prompt_config(config.prompt_config_key)
    )
    if prompt_engine is None:
        logger.info("助理配置关联的提示词模板不存在 prompt_config_key={}", config.prompt_config_key)
        prompt_engine = _empty_prompt_config(config.prompt_config_key)

    return {
        "assistant_setting": {
            "id": config.id,
            "assistant_name": config.assistant_name,
            "assistant_key": config.assistant_key,
            "assistant_type": config.assistant_type,
            "status": config.status,
            "prologue": config.prologue or "",
            "retrieval_method": config.retrieval_method or "",
            "similarity_threshold": config.similarity_threshold,
            "vector_similarity_weight": config.vector_similarity_weight,
            "top_n": config.top_n,
            "rerank_id": config.rerank_id or "",
            "kb_ids": valid_kb_ids,
            "kb_names": kb_names,
            "memory_rounds": config.memory_rounds,
            "top_k": config.top_k,
        },
        "prompt_engine": prompt_engine,
        "model_setting": {
            "model_name": config.model_name or "",
            "llm_setting": config.llm_setting if isinstance(config.llm_setting, dict) else {},
            "max_tokens": config.max_tokens,
            "extra_params": config.extra_params if isinstance(config.extra_params, dict) else {},
        },
    }
