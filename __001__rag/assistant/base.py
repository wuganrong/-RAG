"""助理配置基础抽象。"""

from __future__ import annotations

# 1. Python 标准库
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class AssistantConfig:
    """从 AssistantConfig + PromptConfig 解析后的归一化助理配置。

    模型设置从 AssistantConfig 表读取，提示词模板从 PromptConfig 表读取。
    """

    # 标识
    assistant_key: str
    assistant_name: str | None = None
    assistant_type: str = "conversation"

    # 模型参数
    model_name: str | None = None
    temperature: float = 0.1
    top_p: float | None = None
    max_tokens: int | None = None
    extra_params: dict[str, Any] = field(default_factory=dict)

    # 提示词（从 PromptConfig 关联解析）
    system_prompt: str | None = None
    user_prompt_template: str | None = None
    prompt_config_key: str | None = None

    # 检索参数
    retrieval_method: str | None = None
    similarity_threshold: float = 0.2
    vector_similarity_weight: float = 0.3
    top_n: int = 6
    rerank_id: str | None = None

    # 知识库关联
    kb_ids: list[str] = field(default_factory=list)

    # 对话控制
    memory_rounds: int = 5
    top_k: int = 1024
    prologue: str | None = None
