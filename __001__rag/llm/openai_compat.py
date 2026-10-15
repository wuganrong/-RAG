"""OpenAI 兼容接口的 LLM 实现。"""

from __future__ import annotations

# 1. Python 标准库
import json
from typing import Any, Iterable
from urllib.request import Request, urlopen

# 2. 第三方库
from django.conf import settings
from openai import (
    APIError as OpenAIAPIError,
    APITimeoutError as OpenAITimeoutError,
    AuthenticationError as OpenAIAuthError,
    OpenAI,
    PermissionDeniedError as OpenAIPermissionDeniedError,
    RateLimitError as OpenAIRateLimitError,
)
from urllib.error import HTTPError, URLError

# 3. 本地应用
from __001__rag.llm.base import (
    BaseChatModel,
    BaseEmbeddingModel,
    BaseRerankModel,
    ChatRequest,
    ChatResponse,
    ModelConfig,
)
from __001__rag.llm.exceptions import LLMAuthError, LLMRateLimitError, LLMResponseError, LLMTimeoutError
from __001__rag.llm.utils import derive_rerank_endpoint, get_usage_value, normalize_rerank_results

_UPSTREAM_DETAIL_MAX = 200


def _upstream_detail(exc: Exception) -> str:
    """提取上游返回的错误详情，便于直接定位（额度耗尽 / 无权限 / 参数非法等）。

    OpenAI SDK 的 PermissionDeniedError(403) 等会落进通用 APIError 分支，
    原始信息只存在于 exc.body / exc.message 里，不提取就只能看到笼统的"返回异常"。
    """
    body = getattr(exc, "body", None)
    detail = ""
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            detail = str(error.get("message") or error.get("code") or "")
        if not detail:
            detail = str(body.get("message") or "")
        if not detail:
            detail = str(body)
    if not detail:
        detail = str(getattr(exc, "message", "") or exc)
    detail = " ".join(detail.split())
    if len(detail) > _UPSTREAM_DETAIL_MAX:
        detail = detail[:_UPSTREAM_DETAIL_MAX] + "..."
    return detail



class OpenAICompatibleChatModel(BaseChatModel):
    """基于 OpenAI Chat Completions 协议的聊天模型。"""

    def __init__(self, config: ModelConfig):
        self.config = config
        timeout = float(getattr(settings, "OPENAI_API_TIMEOUT", 120))
        self.client = OpenAI(api_key=config.api_key, base_url=config.api_base, timeout=timeout)

    def chat(self, request: ChatRequest) -> ChatResponse:
        params = self._build_chat_params(request, stream=False)
        try:
            response = self.client.chat.completions.create(**params)
        except OpenAIAuthError as exc:
            raise LLMAuthError("Chat API 认证失败") from exc
        except OpenAIPermissionDeniedError as exc:
            raise LLMAuthError(f"Chat API 无权限或额度不足（{_upstream_detail(exc)}）") from exc
        except OpenAITimeoutError as exc:
            raise LLMTimeoutError("Chat API 调用超时") from exc
        except OpenAIRateLimitError as exc:
            raise LLMRateLimitError("Chat API 触发限流") from exc
        except OpenAIAPIError as exc:
            raise LLMResponseError(f"Chat API 返回异常（{_upstream_detail(exc)}）") from exc
        choice = response.choices[0] if response.choices else None
        content = ""
        if choice and choice.message:
            msg = choice.message
            msg_dict = msg.model_dump() if hasattr(msg, "model_dump") else vars(msg)
            reasoning_field = next(
                (f for f, v in msg_dict.items() if "reasoning" in f and v),
                None,
            )
            reasoning = msg_dict.get(reasoning_field) if reasoning_field else None
            if reasoning:
                content = f"<think>{reasoning}</think>"
            if choice.message.content:
                content += choice.message.content

        usage = getattr(response, "usage", None)
        prompt_tokens = get_usage_value(usage, "prompt_tokens")
        completion_tokens = get_usage_value(usage, "completion_tokens")
        total_tokens = get_usage_value(usage, "total_tokens")
        return ChatResponse(
            content=content,
            model=getattr(response, "model", None) or params["model"],
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            raw=response,
        )

    def stream_chat(self, request: ChatRequest) -> Iterable[str]:
        params = self._build_chat_params(request, stream=True)
        try:
            stream = self.client.chat.completions.create(**params)
        except OpenAIAuthError as exc:
            raise LLMAuthError("Chat Stream API 认证失败") from exc
        except OpenAIPermissionDeniedError as exc:
            raise LLMAuthError(f"Chat Stream API 无权限或额度不足（{_upstream_detail(exc)}）") from exc
        except OpenAITimeoutError as exc:
            raise LLMTimeoutError("Chat Stream API 调用超时") from exc
        except OpenAIRateLimitError as exc:
            raise LLMRateLimitError("Chat Stream API 触发限流") from exc
        except OpenAIAPIError as exc:
            raise LLMResponseError(f"Chat Stream API 返回异常（{_upstream_detail(exc)}）") from exc
        in_think = False
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            delta_dict = delta.model_dump() if hasattr(delta, "model_dump") else vars(delta)
            reasoning_field = next(
                (f for f, v in delta_dict.items() if "reasoning" in f and v),
                None,
            )
            reasoning = delta_dict.get(reasoning_field) if reasoning_field else None
            if reasoning:
                if not in_think:
                    yield "<think>"
                    in_think = True
                yield reasoning
            content = getattr(delta, "content", None)
            if content:
                if in_think:
                    yield "</think>"
                    in_think = False
                yield content
        if in_think:
            yield "</think>"

    def _build_chat_params(self, request: ChatRequest, stream: bool) -> dict[str, Any]:
        params: dict[str, Any] = {
            "model": request.model or self.config.model_name,
            "messages": [message.to_dict() for message in request.messages],
            "stream": stream,
        }
        if request.temperature is not None:
            params["temperature"] = request.temperature
        if request.top_p is not None:
            params["top_p"] = request.top_p
        if request.max_tokens is not None:
            params["max_tokens"] = request.max_tokens
        params.update(request.extra)
        return params


class OpenAICompatibleEmbeddingModel(BaseEmbeddingModel):
    """基于 OpenAI Embeddings 协议的向量模型。"""

    def __init__(self, config: ModelConfig):
        self.config = config
        timeout = float(getattr(settings, "OPENAI_API_TIMEOUT", 120))
        self.client = OpenAI(api_key=config.api_key, base_url=config.api_base, timeout=timeout)

    def encode(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            response = self.client.embeddings.create(model=self.config.model_name, input=texts)
        except OpenAIAuthError as exc:
            raise LLMAuthError("Embedding API 认证失败") from exc
        except OpenAIPermissionDeniedError as exc:
            raise LLMAuthError(f"Embedding API 无权限或额度不足（{_upstream_detail(exc)}）") from exc
        except OpenAITimeoutError as exc:
            raise LLMTimeoutError("Embedding API 调用超时") from exc
        except OpenAIRateLimitError as exc:
            raise LLMRateLimitError("Embedding API 触发限流") from exc
        except OpenAIAPIError as exc:
            raise LLMResponseError(f"Embedding API 返回异常（{_upstream_detail(exc)}）") from exc
        data = sorted(response.data, key=lambda item: item.index)
        embeddings = [list(item.embedding) for item in data]
        return embeddings


class OpenAICompatibleRerankModel(BaseRerankModel):
    """基于 OpenAI 兼容 JSON endpoint 的重排模型。DashScope 使用 compatible-api/v1/reranks。"""

    def __init__(self, config: ModelConfig):
        self.config = config
        self.endpoint = config.endpoint or derive_rerank_endpoint(config.api_base)

    def _rerank_payload(self, query: str, documents: list[str], topn: int | None, native: bool) -> dict[str, Any]:
        if native:
            payload: dict[str, Any] = {
                "model": self.config.model_name,
                "input": {"query": query, "documents": documents},
                "parameters": {"return_documents": False},
            }
            if topn is not None:
                payload["parameters"]["top_n"] = topn
            return payload
        payload = {
            "model": self.config.model_name,
            "query": query,
            "documents": documents,
        }
        if topn is not None:
            payload["top_n"] = topn
        return payload

    def _rerank_endpoints(self) -> list[str]:
        endpoints = [self.endpoint] if self.endpoint else []
        if "dashscope.aliyuncs.com" in (self.endpoint or "") or "dashscope.aliyuncs.com" in (self.config.api_base or ""):
            for extra in (
                "https://dashscope.aliyuncs.com/compatible-api/v1/reranks",
                "https://dashscope.aliyuncs.com/compatible-mode/v1/reranks",
                "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank",
            ):
                if extra not in endpoints:
                    endpoints.append(extra)
        return endpoints or [derive_rerank_endpoint(self.config.api_base)]

    def rerank(self, query: str, documents: list[str], topn: int | None = None) -> list[tuple[int, float]]:
        if not documents:
            return []

        _rerank_timeout = int(getattr(settings, "RERANK_REQUEST_TIMEOUT", 60))
        last_http_error: HTTPError | None = None
        response_payload: Any = None
        for index, endpoint in enumerate(self._rerank_endpoints()):
            native = "/services/rerank/" in (endpoint or "")
            request = Request(
                endpoint,
                data=json.dumps(self._rerank_payload(query, documents, topn, native)).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.config.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urlopen(request, timeout=_rerank_timeout) as response:
                    response_payload = json.loads(response.read().decode("utf-8"))
                break
            except HTTPError as exc:
                last_http_error = exc
                if exc.code == 404 and index < len(self._rerank_endpoints()) - 1:
                    continue
                if exc.code in (401, 403):
                    raise LLMAuthError("Rerank API 认证失败") from exc
                if exc.code == 429:
                    raise LLMRateLimitError("Rerank API 触发限流") from exc
                raise LLMResponseError(f"Rerank API HTTP 错误: {exc.code}") from exc
            except URLError as exc:
                if "timed out" in str(exc.reason):
                    raise LLMTimeoutError("Rerank API 调用超时") from exc
                raise LLMResponseError(f"Rerank API 网络错误: {exc.reason}") from exc
            except TimeoutError as exc:
                raise LLMTimeoutError("Rerank API 调用超时") from exc
        else:
            if last_http_error is not None:
                raise LLMResponseError(f"Rerank API HTTP 错误: {last_http_error.code}") from last_http_error
            raise LLMResponseError("Rerank API 无可用 endpoint")

        results = normalize_rerank_results(response_payload)
        final_results = results[:topn] if topn is not None else results
        return final_results
