"""
Django settings for yf_rag project.
"""

from __future__ import annotations

import os
import sys

from pathlib import Path
from loguru import logger

BASE_DIR = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# 环境变量加载（python-dotenv）
#
# 加载优先级（高到低）：
#   1. OS 环境变量（shell export / docker-compose environment）
#   2. .env.{DJANGO_ENV}  —— 环境专属配置（local/test/prod）
#
# DJANGO_ENV 取值：
#   local     — 本地开发（默认）
#   test      — 测试站
#   prod      — 正式环境
#
# 注意：基础设施（MySQL/Redis/MinIO/ES）的连接信息在 test/prod 环境中
#       由 Docker Compose 的 environment 段注入，不包含在 env 文件中。
# ---------------------------------------------------------------------------
import dotenv

_env_dir = BASE_DIR
DJANGO_ENV = os.environ.get("DJANGO_ENV", "local")

# 加载环境专属配置 .env.{DJANGO_ENV}（不覆盖已有的 OS 环境变量）
_env_file = _env_dir / f".env.{DJANGO_ENV}"
if _env_file.exists():
    dotenv.load_dotenv(_env_file, override=False)


SECRET_KEY = os.environ.get(
    "DJANGO_SECRET_KEY",
    "django-insecure-m_6$y9za*76cpooy8x%r&0-g8r%c2etqsgk7keo%&849%5vaeq",
)

DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("true", "1", "yes")

ALLOWED_HOSTS = ["*"]

# Application definition

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django_comment_migrate",
    # 第三方插件
    "rest_framework",
    "corsheaders",
    "django_filters",
    "drf_spectacular",
    # 业务 App（编号包；AppConfig.label 仍用原名）
    "__001__rag",
    "__002__kb",
    "__006__llm",
    "__003__document",
    "__005__conversation",
    "__004__chunker",
    "__007__rag_conf",
    "__008__intention_type",
    "__009__ner_dict",
]

REST_FRAMEWORK = {
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "EXCEPTION_HANDLER": "__001__rag.utils.exception_handler.custom_exception_handler",
}

SPECTACULAR_SETTINGS = {
    "TITLE": "YF Vision RAG API",
    "DESCRIPTION": "Django + Celery 文本检索与 ColPali 页图多模态",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
}

MIDDLEWARE = [
    "__000__django.middleware.RequestLoggingMiddleware",
    "__000__django.middleware.TenantAuthContextMiddleware",
    "corsheaders.middleware.CorsMiddleware",
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "__000__django.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "__011__frontend"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "__000__django.wsgi.application"

# Database - MySQL（教室局域网）。教室网不通时：set DB_ENGINE=sqlite
_db_engine = os.environ.get("DB_ENGINE", "mysql").lower()
if _db_engine in {"sqlite", "sqlite3"}:
    _sqlite_path = BASE_DIR / "data" / "yf_vision_rag.sqlite3"
    _sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": str(_sqlite_path),
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.mysql",
            "NAME": os.environ.get("DB_NAME", "yf_vision_rag"),
            "USER": os.environ.get("DB_USER", "root"),
            "PASSWORD": os.environ.get("DB_PASSWORD", "infini_rag_flow_5050!"),
            "HOST": os.environ.get("DB_HOST", "192.168.0.21"),
            "PORT": os.environ.get("DB_PORT", "5455"),
            "OPTIONS": {
                "charset": "utf8mb4",
            },
            "CONN_MAX_AGE": int(os.environ.get("DB_CONN_MAX_AGE", "30")),
            "MAX_CONNECTIONS": int(os.environ.get("DB_MAX_CONNECTIONS", "100")),
        }
    }

DCM_COMMENT_KEY = 'verbose_name'  # 注释字段，默认是help_text
DCM_TABLE_COMMENT_KEY = 'verbose_name'  # 表注释字段
DCM_COMMENT_APP = ["rag"]

# Internationalization

LANGUAGE_CODE = "zh-hans"

TIME_ZONE = "Asia/Shanghai"

USE_I18N = True

USE_TZ = False

# Static files

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "__011__frontend"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "data"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# CORS - 允许所有来源、所有请求头、所有方法

CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOW_CREDENTIALS = True
CORS_ALLOW_ALL_HEADERS = True
CORS_ALLOW_METHODS = [
    "DELETE",
    "GET",
    "OPTIONS",
    "PATCH",
    "POST",
    "PUT",
]

# Redis

REDIS_HOST = os.environ.get("REDIS_HOST", "192.168.0.21")
REDIS_PORT = int(os.environ.get("REDIS_PORT", "6378"))
REDIS_PASSWORD = os.environ.get("REDIS_PASSWORD", "infini_rag_flow")

# Redis DB 分配：3=broker，4=result backend，2=NLP缓存
REDIS_DB_BROKER = int(os.environ.get("REDIS_DB_BROKER", "3"))
REDIS_DB_RESULT = int(os.environ.get("REDIS_DB_RESULT", "4"))
REDIS_DB_CACHE = int(os.environ.get("REDIS_DB_CACHE", "2"))


def _redis_url(db: int) -> str:
    return f"redis://:{REDIS_PASSWORD}@{REDIS_HOST}:{REDIS_PORT}/{db}"


# Django Cache（django-redis）

if os.environ.get("CACHE_BACKEND", "redis").lower() == "locmem":
    CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "yf-vision-rag",
        }
    }
else:
    CACHES = {
        "default": {
            "BACKEND": "django_redis.cache.RedisCache",
            "LOCATION": _redis_url(REDIS_DB_CACHE),
            "OPTIONS": {
                "CLIENT_CLASS": "django_redis.client.DefaultClient",
                "SOCKET_CONNECT_TIMEOUT": 2,
                "SOCKET_TIMEOUT": 2,
            },
            "TIMEOUT": 300,
            "KEY_PREFIX": "yf-rag",
        }
    }

# 业务配置缓存 TTL（秒）；0 表示不过期（None 在 django-redis 中表示永不过期）
_raw_config_cache_ttl = int(os.environ.get("CONFIG_CACHE_TTL", "300"))
CONFIG_CACHE_TTL = None if _raw_config_cache_ttl == 0 else _raw_config_cache_ttl

# 投机检索开关
ENABLE_SPECULATIVE_RETRIEVAL = os.environ.get("ENABLE_SPECULATIVE_RETRIEVAL", "true").lower() == "true"

# Celery

CELERY_BROKER_URL = _redis_url(REDIS_DB_BROKER)
CELERY_RESULT_BACKEND = _redis_url(REDIS_DB_RESULT)

CELERY_ACCEPT_CONTENT = ["json"]
CELERY_TASK_SERIALIZER = "json"
CELERY_RESULT_SERIALIZER = "json"
CELERY_TIMEZONE = "Asia/Shanghai"
CELERY_ENABLE_UTC = False

# 结果过期时间（秒）
CELERY_RESULT_EXPIRES = int(os.environ.get("CELERY_RESULT_EXPIRES", str(60 * 60 * 24)))

# Worker 并发数（None = CPU 核数）
CELERY_WORKER_CONCURRENCY = int(os.environ.get("CELERY_WORKER_CONCURRENCY", "8"))

# 每个 Worker 每次预取的任务数
CELERY_WORKER_PREFETCH_MULTIPLIER = int(os.environ.get("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))

# 单个任务执行超时（秒）
CELERY_TASK_SOFT_TIME_LIMIT = int(os.environ.get("CELERY_TASK_SOFT_TIME_LIMIT", str(60 * 100)))
CELERY_TASK_TIME_LIMIT = int(os.environ.get("CELERY_TASK_TIME_LIMIT", str(60 * 150)))

# 任务重试策略
CELERY_TASK_MAX_RETRIES = int(os.environ.get("CELERY_TASK_MAX_RETRIES", "3"))
CELERY_TASK_DEFAULT_RETRY_DELAY = int(os.environ.get("CELERY_TASK_DEFAULT_RETRY_DELAY", "5"))

CELERY_TASK_DEFAULT_QUEUE = "default"

# 显式注册 rag.task 子模块中的任务（autodiscover_tasks 仅发现 app 根目录的 tasks.py）
CELERY_IMPORTS = [
    "__001__rag.task.aggregate",
    "__001__rag.task.process_chunk",
]
if os.environ.get("ENABLE_VISION_WORKER", "False").lower() in ("true", "1", "yes"):
    CELERY_IMPORTS.append("__010__colpali.tasks")
CELERY_IMPORTS = tuple(CELERY_IMPORTS)

# 多任务队列定义
CELERY_TASK_QUEUES = {
    "default": {"exchange": "default", "routing_key": "default"},
    "vision": {"exchange": "vision", "routing_key": "vision"},
}

# 任务路由：按模块自动分发到对应队列
CELERY_TASK_ROUTES = {
    "__001__rag.task.aggregate.*": {"queue": "default"},
    "__001__rag.task.process_chunk.*": {"queue": "default"},
    "__001__rag.tasks.*": {"queue": "default"},
    "__010__colpali.tasks.*": {"queue": "vision"},
}

# MinIO

MINIO_USER = os.environ.get("MINIO_USER", "rag_flow")
MINIO_PASSWORD = os.environ.get("MINIO_PASSWORD", "infini_rag_flow")
MINIO_HOST = f"{os.environ.get('MINIO_HOST', '192.168.0.21')}:{os.environ.get('MINIO_PORT', '9000')}"

# Elasticsearch

ES_HOST = os.environ.get("ES_HOST", "192.168.0.21")
ES_PORT = os.environ.get("ES_PORT", "9200")
ES_HOSTS = os.environ.get("ES_HOSTS", f"http://{ES_HOST}:{ES_PORT}")
ES_USERNAME = os.environ.get("ES_USERNAME", "elastic")
ES_PASSWORD = os.environ.get("ES_PASSWORD", "infini_rag_flow")

# RAG 业务配置

LLM_TENANT_ID = os.environ.get("LLM_TENANT_ID", "440ec01618cc11f09d480242ac170006")
CUSTOM_KB_ID = os.environ.get("CUSTOM_KB_ID", "550ec01618cc11f09d480242ac170006")

# OCR / 文档解析

OCRFLUX_API_URL = os.environ.get("OCRFLUX_API_URL", "http://192.168.0.21:8000/pdf-to-markdown-base64")
MINERU_FILE_PARSE_URL = os.environ.get("MINERU_FILE_PARSE_URL", "http://192.168.0.34:40050/file_parse")
MINERU_MAX_CONCURRENCY = int(os.environ.get("MINERU_MAX_CONCURRENCY", "1"))
PDF_LLM_SECTIONS_OUTPUT_DIR = os.environ.get("PDF_LLM_SECTIONS_OUTPUT_DIR", "/ragflow/logs/out")
MAX_CONCURRENT_CHUNK_BUILDERS = int(os.environ.get("MAX_CONCURRENT_CHUNK_BUILDERS", "2"))

LLM_MODEL_ID = os.environ.get("LLM_MODEL_ID", "deepseek:671b@VLLM")
EMBEDDING_MODEL_ID = os.environ.get("EMBEDDING_MODEL_ID", "bge-m3@VLLM2")
RERANK_MODEL_ID = os.environ.get("RERANK_MODEL_ID", "bge-reranker-v2-m3___VLLM@VLLM3")

# MacBERT 父子分块

MACBERT_MODEL_NAME = os.environ.get("MACBERT_MODEL_NAME", "D:\\model\\chinese-macbert-base")
MACBERT_CHUNK_TOKEN_NUM = int(os.environ.get("MACBERT_CHUNK_TOKEN_NUM", "256"))
MACBERT_PARENT_GROUP_SIZE = int(os.environ.get("MACBERT_PARENT_GROUP_SIZE", "4"))

# Chunk 旧版兼容
# True 时，list_document_chunks 查询时使用固定的旧版索引名（ragflow_<LLM_TENANT_ID>）
# False 时，按 kb_id 动态生成索引名（ragflow_<kb_id>）
CHUNK_LEGACY_COMPAT = os.environ.get("CHUNK_LEGACY_COMPAT", "True").lower() in ("true", "1", "yes")
CHUNK_LEGACY_INDEX = f"ragflow_{LLM_TENANT_ID}"

# NLP Redis 缓存过期时间（秒），到期后 Redis 自动清理，下次启动从数据库重新加载
NLP_CACHE_TTL = int(os.environ.get("NLP_CACHE_TTL", "86400"))  # 默认 24 小时

# NLP Redis 缓存 Key

NLP_DATA_CACHE_KEY = "nlp:cache:data"
NLP_SYS_DICT_CACHE_KEY = "nlp:cache:sys_dict"
NLP_TRIE_CACHE_KEY = "nlp:cache:trie"

# NLP 启动等待超时（秒）

SYS_DICT_READY_TIMEOUT = float(os.environ.get("SYS_DICT_READY_TIMEOUT", "10.0"))
NLP_READY_TIMEOUT = float(os.environ.get("NLP_READY_TIMEOUT", "60.0"))
NLP_TOKENIZER_READY_TIMEOUT = float(os.environ.get("NLP_TOKENIZER_READY_TIMEOUT", "30.0"))

# Redis 分布式锁默认参数

REDIS_LOCK_TIMEOUT = int(os.environ.get("REDIS_LOCK_TIMEOUT", "10"))          # 锁过期时间（秒），防止死锁
REDIS_LOCK_BLOCKING_TIMEOUT = float(os.environ.get("REDIS_LOCK_BLOCKING_TIMEOUT", "1.0"))  # 等待获取锁的最长时间（秒）
REDIS_HEALTH_CHECK_TTL = int(os.environ.get("REDIS_HEALTH_CHECK_TTL", "3"))       # 健康检查临时 key 过期时间（秒）

# Elasticsearch 检索参数

ES_REQUEST_TIMEOUT = int(os.environ.get("ES_REQUEST_TIMEOUT", "600"))         # 普通请求超时（秒）
ES_BULK_REQUEST_TIMEOUT = int(os.environ.get("ES_BULK_REQUEST_TIMEOUT", "60"))     # 批量写入请求超时（秒）
ES_VERIFY_CERTS = os.environ.get("ES_VERIFY_CERTS", "False").lower() in ("true", "1", "yes")  # 是否验证 TLS 证书（生产环境建议 True）
ES_ATTEMPT_COUNT = int(os.environ.get("ES_ATTEMPT_COUNT", "2"))             # 索引存在检查 / 检索失败重试次数
ES_RETRY_SLEEP_SECONDS = int(os.environ.get("ES_RETRY_SLEEP_SECONDS", "1"))       # 重试间隔（秒）
ES_AGGREGATION_MAX_SIZE = int(os.environ.get("ES_AGGREGATION_MAX_SIZE", "1000"))   # terms 聚合最大桶数（防止 OOM）

# MinIO 连接与重试参数

MINIO_SECURE = os.environ.get("MINIO_SECURE", "False").lower() in ("true", "1", "yes")  # 是否使用 HTTPS
MINIO_DEFAULT_BUCKET_NAME = os.environ.get("MINIO_DEFAULT_BUCKET_NAME", "kb-default")   # 归一化后为空时使用的默认 bucket 名
MINIO_HEALTH_CHECK_BUCKET = os.environ.get("MINIO_HEALTH_CHECK_BUCKET", "txtxtxtxt1")   # 健康检查专用 bucket
MINIO_HEALTH_CHECK_OBJECT = os.environ.get("MINIO_HEALTH_CHECK_OBJECT", "txtxtxtxt1")   # 健康检查专用对象名
MINIO_PUT_MAX_RETRIES = int(os.environ.get("MINIO_PUT_MAX_RETRIES", "3"))        # put / upload 最大重试次数
MINIO_PRESIGN_MAX_RETRIES = int(os.environ.get("MINIO_PRESIGN_MAX_RETRIES", "10"))   # 预签名 URL 最大重试次数
MINIO_RETRY_SLEEP_SECONDS = int(os.environ.get("MINIO_RETRY_SLEEP_SECONDS", "1"))    # 重试间隔（秒）

# OCRFlux 解析参数

OCRFLUX_REQUEST_TIMEOUT = int(os.environ.get("OCRFLUX_REQUEST_TIMEOUT", "300"))              # 单次 API 请求超时（秒）
OCRFLUX_MAX_RETRIES = int(os.environ.get("OCRFLUX_MAX_RETRIES", "3"))                    # 最大重试次数
OCRFLUX_MAX_PAGE_RETRIES = int(os.environ.get("OCRFLUX_MAX_PAGE_RETRIES", "3"))              # 单页解析最大重试次数
OCRFLUX_TARGET_LONGEST_IMAGE_DIM = int(os.environ.get("OCRFLUX_TARGET_LONGEST_IMAGE_DIM", "1024"))   # 图片最长边尺寸（像素）
OCRFLUX_USER_AGENT = os.environ.get("OCRFLUX_USER_AGENT", "YF-RAG-OCRFlux-Client/1.0")

# MinerU 解析参数

MINERU_REQUEST_TIMEOUT = int(os.environ.get("MINERU_REQUEST_TIMEOUT", "1200"))              # 单次 API 请求超时（秒）
MINERU_MAX_RETRIES = int(os.environ.get("MINERU_MAX_RETRIES", "3"))                     # 最大重试次数
MINERU_RETRY_BACKOFF_BASE = int(os.environ.get("MINERU_RETRY_BACKOFF_BASE", "2"))             # 指数退避基数（秒），实际等待 = base ** attempt
MINERU_PARSE_BACKEND = os.environ.get("MINERU_PARSE_BACKEND", "vlm-auto-engine")  # 解析后端
MINERU_RETURN_IMAGES = os.environ.get("MINERU_RETURN_IMAGES", "True").lower() in ("true", "1", "yes")  # 是否返回图片
MINERU_USER_AGENT = os.environ.get("MINERU_USER_AGENT", "YF-RAG-MinerU-Client/1.0")
MINERU_IMAGES_BUCKET = os.environ.get("MINERU_IMAGES_BUCKET", "mineru")           # MinerU 图片存储 bucket
MINERU_MAX_SECTION_CHARS = int(os.environ.get("MINERU_MAX_SECTION_CHARS", "20000"))  # 单章节最大字符数（MinerU 专属覆盖值）；None 时回退到 PDF_LLM_MAX_SECTION_CHARS

# PDF-LLM 分块参数

PDF_LLM_MAX_SECTION_CHARS = int(os.environ.get("PDF_LLM_MAX_SECTION_CHARS", "20000"))        # 单章节最大字符数，超出时按段落拆分
PDF_LLM_DEFAULT_TEMPERATURE = float(os.environ.get("PDF_LLM_DEFAULT_TEMPERATURE", "0.2"))        # LLM 分块默认温度

# 检索参数

RETRIEVAL_MINIMUM_SHOULD_MATCH = float(os.environ.get("RETRIEVAL_MINIMUM_SHOULD_MATCH", "0.3"))     # 全文检索 minimum_should_match
SEARCH_BACKEND = os.environ.get("SEARCH_BACKEND", "elasticsearch")          # 检索后端类型

# 关键词提取默认参数

KEYWORD_EXTRACTION_DEFAULT_PROMPT = os.environ.get("KEYWORD_EXTRACTION_DEFAULT_PROMPT", "请从以下文本中提取{topn}个最重要的关键词，用逗号分隔。")
KEYWORD_EXTRACTION_DEFAULT_TEMPERATURE = float(os.environ.get("KEYWORD_EXTRACTION_DEFAULT_TEMPERATURE", "0.1"))
KEYWORD_EXTRACTION_DEFAULT_MAX_TOKENS = int(os.environ.get("KEYWORD_EXTRACTION_DEFAULT_MAX_TOKENS", "200"))

# 问题生成默认参数

QUESTION_GEN_MAX_QUESTIONS = int(os.environ.get("QUESTION_GEN_MAX_QUESTIONS", "5"))           # 单片段最多生成问题数
QUESTION_GEN_SIMILARITY_THRESHOLD = float(os.environ.get("QUESTION_GEN_SIMILARITY_THRESHOLD", "0.55"))  # 跨层去重向量相似度阈值
QUESTION_GEN_MAX_RETRY = int(os.environ.get("QUESTION_GEN_MAX_RETRY", "3"))               # 每层问题最大重试轮数
QUESTION_GEN_DEDUP_THRESHOLD = float(os.environ.get("QUESTION_GEN_DEDUP_THRESHOLD", "0.85"))      # 同层去重向量相似度阈值
QUESTION_GEN_DEFAULT_TEMPERATURE = float(os.environ.get("QUESTION_GEN_DEFAULT_TEMPERATURE", "0.1"))   # LLM 调用默认温度
QUESTION_GEN_ASSESS_MAX_TOKENS = int(os.environ.get("QUESTION_GEN_ASSESS_MAX_TOKENS", "300"))     # 复杂度评估最大 token 数
QUESTION_GEN_GENERATE_MAX_TOKENS = int(os.environ.get("QUESTION_GEN_GENERATE_MAX_TOKENS", "500"))   # 问题生成最大 token 数

# LLM / 网络请求超时
OPENAI_API_TIMEOUT = int(os.environ.get("OPENAI_API_TIMEOUT", "60"))                 # LLM HTTP 请求超时（秒）
RERANK_REQUEST_TIMEOUT = int(os.environ.get("RERANK_REQUEST_TIMEOUT", "60"))             # Rerank HTTP 请求超时（秒）

# DashScope / OpenAI-compatible endpoint.
# API Key 只从系统环境变量读取；.env.local 中不要写真实密钥。
DASHSCOPE_API_KEY = os.environ.get("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = os.environ.get("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
DASHSCOPE_CHAT_MODEL = os.environ.get("DASHSCOPE_CHAT_MODEL", "qwen-plus")
DASHSCOPE_VL_MODEL = os.environ.get("DASHSCOPE_VL_MODEL", "qwen-vl-plus")

# SSE 流式响应超时
SSE_RETRIEVAL_TIMEOUT = float(os.environ.get("SSE_RETRIEVAL_TIMEOUT", "60.0"))           # 检索阶段最大等待时间（秒）
SSE_POLL_INTERVAL = float(os.environ.get("SSE_POLL_INTERVAL", "0.5"))                  # 检索线程轮询间隔（秒）
SSE_LLM_FIRST_TOKEN_TIMEOUT = float(os.environ.get("SSE_LLM_FIRST_TOKEN_TIMEOUT", "60.0"))  # LLM 首 token 最大等待时间（秒）
SSE_LLM_POLL_INTERVAL = float(os.environ.get("SSE_LLM_POLL_INTERVAL", "0.5"))           # LLM 流式队列轮询间隔（秒）

# Elasticsearch 索引 Mapping
ES_NUMBER_OF_SHARDS = int(os.environ.get("ES_NUMBER_OF_SHARDS", "2"))               # 索引主分片数量
ES_NUMBER_OF_REPLICAS = int(os.environ.get("ES_NUMBER_OF_REPLICAS", "0"))            # 索引副本数量
ES_REFRESH_INTERVAL = os.environ.get("ES_REFRESH_INTERVAL", "1000ms")                # 索引刷新间隔

# OCRFlux 退避
OCRFLUX_RETRY_BACKOFF_BASE = int(os.environ.get("OCRFLUX_RETRY_BACKOFF_BASE", "2"))  # 指数退避基数（秒），实际等待 = base ** attempt

# ---------------------------------------------------------------------------
# Loguru 日志配置
# ---------------------------------------------------------------------------

LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# 日志格式：时间 | 级别 | trace_id | 模块:函数:行号 | 消息
from __001__rag.utils.context import get_trace_id  # noqa: E402

LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "<magenta>{extra[trace_id]}</magenta> | "
    "<cyan>{module}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
    "<level>{message}</level>"
)

# 移除默认 handler（避免重复输出）
logger.remove()

# 全局 patcher：自动注入 trace_id 到每条日志记录
logger.configure(patcher=lambda record: record["extra"].update(trace_id=get_trace_id()))

# 控制台输出（开发调试用）
logger.add(sys.stderr, format=LOG_FORMAT, level="DEBUG")

# 文件输出：按天轮转，保留 30 天
logger.add(
    str(LOG_DIR / "yf-rag_{time:YYYY-MM-DD}.log"),
    format=LOG_FORMAT,
    level="INFO",
    rotation="00:00",          # 每天午夜轮转
    retention="30 days",       # 自动保留最近 30 天
    encoding="utf-8",
    enqueue=True,              # 线程/进程安全
)
