from __future__ import annotations

import hashlib
import time
from typing import Any

_TTL = 30 * 60
_store: dict[str, tuple[float, Any]] = {}


def cache_get(key: str):
    item = _store.get(key)
    if not item:
        return None
    expires, value = item
    if expires < time.time():
        _store.pop(key, None)
        return None
    return value


def cache_set(key: str, value, ttl: int = _TTL) -> None:
    _store[key] = (time.time() + ttl, value)


def embed_cache_key(model: str, text: str) -> str:
    digest = hashlib.md5(f"{model}:{text}".encode("utf-8")).hexdigest()
    return f"emb:{digest}"
