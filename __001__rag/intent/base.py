"""意图识别结果数据结构。"""

from __future__ import annotations

# 1. Python 标准库
from dataclasses import dataclass, field


@dataclass(slots=True)
class IntentResult:
    """意图识别结果。

    Attributes:
        kb_ids: 匹配到的知识库 ID 列表，空列表表示未匹配到。
        intent_name: 匹配到的意图名称，None 表示未匹配到。
        actual_question: 去除 @ 前缀后的实际问题内容。
    """

    kb_ids: list[str] = field(default_factory=list)
    intent_name: str | None = None
    actual_question: str = ""
