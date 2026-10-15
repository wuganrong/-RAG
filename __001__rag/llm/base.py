"""大模型调用基础抽象。"""

from __future__ import annotations

# 1. Python 标准库
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Iterable, Literal

ChatRole = Literal["system", "user", "assistant", "tool"]
ModelType = Literal["chat", "embedding", "rerank"]


@dataclass(slots=True)
class ChatMessage:
    """OpenAI 兼容的聊天消息。"""

    role: ChatRole
    content: str
    name: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为可传给 OpenAI 兼容接口的字典。"""
        data: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name:
            data["name"] = self.name
        data.update(self.extra)
        return data


@dataclass(slots=True)
class ChatRequest:
    """聊天请求参数。"""

    messages: list[ChatMessage]
    model: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    stream: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ChatResponse:
    """聊天响应结果。"""

    content: str
    model: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    raw: Any | None = None


@dataclass(slots=True)
class ModelConfig:
    """模型实例化所需的最小配置。"""

    model_name: str
    model_type: ModelType
    api_base: str
    api_key: str
    factory: str | None = None
    endpoint: str | None = None


class BaseChatModel(ABC):
    """聊天模型端口，屏蔽不同大模型厂商的 SDK 差异。"""

    @abstractmethod
    def chat(self, request: ChatRequest) -> ChatResponse:
        """同步生成完整回复。"""
        raise NotImplementedError

    @abstractmethod
    def stream_chat(self, request: ChatRequest) -> Iterable[str]:
        """流式生成回复片段。"""
        raise NotImplementedError


class BaseEmbeddingModel(ABC):
    """向量模型端口。"""

    @abstractmethod
    def encode(self, texts: list[str]) -> list[list[float]]:
        """将文本批量编码为向量。"""
        raise NotImplementedError


class BaseRerankModel(ABC):
    """重排模型端口。"""

    @abstractmethod
    def rerank(self, query: str, documents: list[str], topn: int | None = None) -> list[tuple[int, float]]:
        """返回文档原始下标与相关性分数。"""
        raise NotImplementedError
