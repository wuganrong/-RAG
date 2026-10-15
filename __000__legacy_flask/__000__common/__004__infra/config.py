from __future__ import annotations

import os


def _env(name: str, default: str = "") -> str:
    return (os.getenv(name) or default).strip()


# Reuse the already-running yf-rag Docker Desktop / LAN stack. Do not create new containers.
REDIS_HOST = _env("REDIS_HOST", "192.168.0.21")
REDIS_PORT = int(_env("REDIS_PORT", "6378") or "6378")
REDIS_PASSWORD = _env("REDIS_PASSWORD", "infini_rag_flow")
REDIS_DB = int(_env("REDIS_DB", "2") or "2")

MINIO_HOST = _env("MINIO_HOST", "192.168.0.21")
MINIO_PORT = _env("MINIO_PORT", "9000")
MINIO_USER = _env("MINIO_USER", "rag_flow")
MINIO_PASSWORD = _env("MINIO_PASSWORD", "infini_rag_flow")
MINIO_BUCKET = _env("MINIO_DEFAULT_BUCKET_NAME", "kb-default")
MINIO_SECURE = _env("MINIO_SECURE", "false").lower() in {"1", "true", "yes"}

ES_HOSTS = _env("ES_HOSTS", "http://192.168.0.21:9200")
ES_USERNAME = _env("ES_USERNAME", "elastic")
ES_PASSWORD = _env("ES_PASSWORD", "infini_rag_flow")
ES_INDEX_PREFIX = _env("ES_INDEX_PREFIX", "vision_kb_")


def redis_url(db: int | None = None) -> str:
    database = REDIS_DB if db is None else db
    if REDIS_PASSWORD:
        return f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{database}"
    return f"redis://{REDIS_HOST}:{REDIS_PORT}/{database}"


def minio_endpoint() -> str:
    return f"{MINIO_HOST}:{MINIO_PORT}"
