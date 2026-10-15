"""Independent MacBERT parent-child chunking adapter.

This module uses a lazy HuggingFace tokenizer when available,
and tests can inject a lightweight tokenizer object.
"""

from __future__ import annotations

# 1. Python 标准库
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# 2. 第三方库
from django.conf import settings

# 3. 本地应用
from __001__rag.nlp.utils import estimate_token_count
from __001__rag.utils import get_uuid

_SENTENCE_RE = re.compile(r"[^。！？.!?\n]+[。！？.!?]?")


@dataclass(slots=True)
class MacBERTChunk:
    """One child chunk produced by the MacBERT parent-child adapter."""

    content: str
    parent_group_id: str
    child_index: int
    token_num: int
    metadata: dict[str, Any]


class MacBERTChunker:
    """Parent-child chunker with optional MacBERT tokenizer based token counts."""

    def __init__(
        self,
        *,
        model_name: str | None = None,
        chunk_token_num: int | None = None,
        parent_group_size: int | None = None,
        tokenizer: Any | None = None,
        tokenizer_loader: Callable[[str], Any] | None = None,
    ) -> None:
        self.model_name = model_name or getattr(settings, "MACBERT_MODEL_NAME", "")
        self.chunk_token_num = int(chunk_token_num or getattr(settings, "MACBERT_CHUNK_TOKEN_NUM", 256) or 256)
        self.parent_group_size = int(parent_group_size or getattr(settings, "MACBERT_PARENT_GROUP_SIZE", 4) or 4)
        self._tokenizer = tokenizer
        self._tokenizer_loader = tokenizer_loader

    def chunk_text(self, text: str) -> list[MacBERTChunk]:
        """Chunk text into child chunks and group adjacent children by parent id."""
        sentences = self._sentences(text)
        if not sentences:
            return []

        child_texts: list[str] = []
        current: list[str] = []
        for sentence in sentences:
            candidate = "".join([*current, sentence]).strip()
            if current and self._count_tokens(candidate) > self.chunk_token_num:
                child_texts.append("".join(current).strip())
                current = [sentence]
            else:
                current.append(sentence)
        if current:
            child_texts.append("".join(current).strip())

        chunks: list[MacBERTChunk] = []
        parent_group_id = ""
        for idx, content in enumerate(child_texts):
            if idx % max(self.parent_group_size, 1) == 0:
                parent_group_id = get_uuid()
            token_num = self._count_tokens(content)
            chunks.append(
                MacBERTChunk(
                    content=content,
                    parent_group_id=parent_group_id,
                    child_index=idx,
                    token_num=token_num,
                    metadata={
                        "chunk_method": "macbert_parent_child",
                        "parent_group_id": parent_group_id,
                        "chunk_tokens": token_num,
                        "child_index": idx,
                    },
                )
            )
        return chunks

    def _count_tokens(self, text: str) -> int:
        tokenizer = self._get_tokenizer()
        if tokenizer is None:
            return estimate_token_count(text)
        try:
            encoded = tokenizer(text, add_special_tokens=False)
            input_ids = encoded.get("input_ids") if isinstance(encoded, dict) else encoded
            return len(input_ids or [])
        except Exception:
            return estimate_token_count(text)

    def _get_tokenizer(self) -> Any | None:
        if self._tokenizer is not None:
            return self._tokenizer
        if not self.model_name:
            return None
        try:
            loader = self._tokenizer_loader or _load_hf_tokenizer
            self._tokenizer = loader(self.model_name)
            return self._tokenizer
        except Exception:
            return None

    @staticmethod
    def _sentences(text: str) -> list[str]:
        return [match.group(0).strip() for match in _SENTENCE_RE.finditer(text or "") if match.group(0).strip()]


def _load_hf_tokenizer(model_name: str) -> Any:
    # 延迟加载重型 ML 依赖，避免 import 时拉取 transformers
    from transformers import AutoTokenizer

    return AutoTokenizer.from_pretrained(model_name)
