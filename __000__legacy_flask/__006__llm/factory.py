from __future__ import annotations

import os

from openai import OpenAI
import httpx

from __000__common.__002__log import get_logger
from __003__colpali.generate.model_loader import load_model
from __003__colpali.generate.responder import generate_response
from __006__llm.cache import cache_get, cache_set, embed_cache_key

logger = get_logger(__name__)

DASHSCOPE_DEFAULT_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


def _dashscope_client() -> OpenAI:
    api_key = os.getenv("DASHSCOPE_API_KEY")
    if not api_key:
        raise ValueError("DASHSCOPE_API_KEY 未配置")
    base_url = os.getenv("DASHSCOPE_BASE_URL", DASHSCOPE_DEFAULT_BASE_URL)
    use_proxy = os.getenv("DASHSCOPE_USE_PROXY", "").strip().lower() in {"1", "true", "yes"}
    http_client = httpx.Client(trust_env=use_proxy, timeout=60.0)
    return OpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


def embed_texts(texts: list[str], model: str = "text-embedding-v3") -> list[list[float]]:
    if not texts:
        return []
    try:
        client = _dashscope_client()
        vectors: list[list[float]] = []
        batch = 10
        for i in range(0, len(texts), batch):
            part = texts[i : i + batch]
            resp = client.embeddings.create(model=model, input=part)
            by_index = {item.index: item.embedding for item in resp.data}
            vectors.extend(by_index[j] for j in range(len(part)))
        return vectors
    except Exception as exc:
        logger.warning("Embedding 失败，回退关键词检索: %s", exc)
        return []


def embed_query(text: str, model: str = "text-embedding-v3") -> list[float] | None:
    key = embed_cache_key(model, text.strip())
    cached = cache_get(key)
    if cached is not None:
        return cached
    vectors = embed_texts([text], model=model)
    if not vectors:
        return None
    cache_set(key, vectors[0])
    return vectors[0]


def generate_chat(query: str, context: str, model: str | None = None, prompt: str | None = None) -> str:
    client = _dashscope_client()
    model_name = model or os.getenv("DASHSCOPE_CHAT_MODEL", "qwen-plus")
    content = prompt or (
        "你是企业知识库助手。只根据给定资料回答；找不到就明确说没有依据，不要编造。\n"
        f"资料：\n{context}\n\n问题：{query}"
    )
    resp = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": content}],
        max_tokens=1024,
    )
    return (resp.choices[0].message.content or "").strip()


def generate_chat_stream(prompt: str, model: str | None = None):
    client = _dashscope_client()
    model_name = model or os.getenv("DASHSCOPE_CHAT_MODEL", "qwen-plus")
    stream = client.chat.completions.create(
        model=model_name,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=1024,
        stream=True,
    )
    for chunk in stream:
        delta = ""
        try:
            delta = chunk.choices[0].delta.content or ""
        except Exception:
            delta = ""
        if delta:
            yield delta


def generate_vlm(
    image_paths: list[str],
    query: str,
    session_id: str,
    extra_context: str = "",
    resized_height: int = 280,
    resized_width: int = 280,
    model_choice: str = "qwen",
    vlm_id: str | None = None,
) -> tuple[str, list[str]]:
    if extra_context:
        query = f"{query}\n\n补充文本依据：\n{extra_context}"
    return generate_response(
        image_paths,
        query,
        session_id,
        resized_height=resized_height,
        resized_width=resized_width,
        model_choice=model_choice,
        vlm_id=vlm_id,
    )


def ensure_vlm_ready() -> None:
    load_model("qwen")
