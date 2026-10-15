"""关键词提取器。

将 LLM 配置和提示词统一在构造时注入，不查询数据库。
"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.llm.base import ChatMessage
from __001__rag.llm.service import LLMService
from __001__rag.question_generate.utils import strip_thinking

from .utils import extract_path_keywords, parse_keyword_list


def _get_default_keyword_prompt() -> str:
    return getattr(settings, "KEYWORD_EXTRACTION_DEFAULT_PROMPT", "请从以下文本中提取{topn}个最重要的关键词，用逗号分隔。")


class KeywordExtractor:
    """关键词提取器。

    模型参数和提示词在构造时注入，不查询数据库。

    用法:
        extractor = KeywordExtractor(
            model_config={"model_name": "qwen2.5:14b@Ollama", "temperature": 0.2, ...},
            system_prompt="请从文本提取{topn}个关键词...",
        )
        keywords = extractor.extract(content, topn=20)
    """

    def __init__(
        self,
        model_config: dict[str, Any] | None = None,
        system_prompt: str | None = None,
    ) -> None:
        """初始化关键词提取器。

        Args:
            model_config: LLM 模型配置 {"model_name", "temperature", "top_p", "max_tokens", "extra_params"}
            system_prompt: 关键词提取提示词（支持 {topn} 占位符），为 None 时使用默认提示词
        """
        mc = model_config or {}
        self.model_name: str | None = mc.get("model_name")
        self.temperature: float = float(mc.get("temperature") if mc.get("temperature") is not None else getattr(settings, "KEYWORD_EXTRACTION_DEFAULT_TEMPERATURE", 0.1))
        self.top_p: float | None = mc.get("top_p")
        self.max_tokens: int = int(mc.get("max_tokens") if mc.get("max_tokens") is not None else getattr(settings, "KEYWORD_EXTRACTION_DEFAULT_MAX_TOKENS", 200))
        self.extra_params: dict[str, Any] = mc.get("extra_params") or {}
        self._system_prompt: str | None = system_prompt

    def extract(self, content: str, topn: int = 20) -> list[str]:
        """从文本内容中提取关键词。

        Args:
            content: 文本内容
            topn: 最多提取的关键词数量

        Returns:
            关键词列表；内容为空或 topn<=0 时返回空列表
        """
        if not content or topn <= 0:
            return []

        try:
            system_prompt = (self._system_prompt or _get_default_keyword_prompt()).replace("{topn}", str(topn))
            user_prompt = f"## 文本内容\n{content}"

            response = self._chat(system_prompt=system_prompt, user_prompt=user_prompt)
            text = strip_thinking(response.content if hasattr(response, "content") else str(response))

            if "**ERROR**" in text:
                logger.info("关键词提取 LLM 返回错误标记")
                return []

            keywords = parse_keyword_list(text)

            # 补充路径关键词（GB 标准特有）
            path_keywords = extract_path_keywords(content)
            if path_keywords:
                seen = set(keywords)
                for kw in path_keywords:
                    if kw not in seen:
                        keywords.append(kw)
                        seen.add(kw)

            logger.info("关键词提取完成，keyword_count={}, topn={}", len(keywords), topn)
            return keywords
        except Exception:
            logger.exception("关键词提取失败")
            return []

    def _chat(self, *, system_prompt: str, user_prompt: str) -> Any:
        """使用注入的模型配置调用 LLM。"""
        model_id = self.model_name or getattr(settings, "LLM_MODEL_ID", None)
        logger.info(
            "关键词提取 LLM 调用，model_id={}, temperature={}, max_tokens={}",
            model_id,
            self.temperature,
            self.max_tokens,
        )
        return LLMService.chat(
            messages=[
                ChatMessage(role="system", content=system_prompt),
                ChatMessage(role="user", content=user_prompt),
            ],
            model_name=model_id,
            temperature=self.temperature,
            top_p=self.top_p,
            max_tokens=self.max_tokens,
            extra=self.extra_params,
        )
