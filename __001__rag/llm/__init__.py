"""__001__rag.llm - LLM call abstractions."""

from __future__ import annotations

# 3. 本地应用
from __001__rag.llm.base import (
    BaseChatModel,
    BaseEmbeddingModel,
    BaseRerankModel,
    ChatMessage,
    ChatRequest,
    ChatResponse,
    ModelConfig,
)
from __001__rag.llm.exceptions import LLMConfigError
from __001__rag.llm.factory import (
    build_chat_model,
    build_embedding_model,
    build_rerank_model,
    resolve_model_config,
    split_model_name_and_factory,
)
from __001__rag.llm.openai_compat import (
    OpenAICompatibleChatModel,
    OpenAICompatibleEmbeddingModel,
    OpenAICompatibleRerankModel,
)
from __001__rag.llm.service import LLMService

__all__ = [
    "BaseChatModel",
    "BaseEmbeddingModel",
    "BaseRerankModel",
    "ChatMessage",
    "ChatRequest",
    "ChatResponse",
    "ModelConfig",
    "OpenAICompatibleChatModel",
    "OpenAICompatibleEmbeddingModel",
    "OpenAICompatibleRerankModel",
    "LLMConfigError",
    "build_chat_model",
    "build_embedding_model",
    "build_rerank_model",
    "resolve_model_config",
    "split_model_name_and_factory",
    "LLMService",
]
