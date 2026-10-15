"""关键词提取相关的纯工具函数。"""

from __future__ import annotations

# 1. Python 标准库
import re

# 3. 本地应用
from __001__rag.question_generate.utils import clean_list_item, dedupe_nonempty


def parse_keyword_list(text: str) -> list[str]:
    """解析 LLM 返回的关键词列表并保持顺序去重。"""
    parts = re.split(r"[,，\n;；]", text or "")
    return dedupe_nonempty(clean_list_item(part) for part in parts)


def extract_path_keywords(content: str) -> list[str]:
    """提取 GB 路径层级关键词（兼容 ragflow 风格）。"""
    if not content:
        return []
    first_line = str(content).splitlines()[0].strip() if str(content).strip() else ""
    if not first_line.startswith("GB") or ">" not in first_line:
        return []
    return [part.strip() for part in re.split(r"\s*>\s*", first_line) if part.strip()]
