"""项目启动初始化：加载 SysDict + NLP 数据，并输出配置。"""

# 1. Python 标准库
import base64
import os
import threading
import time
from pathlib import Path

# 2. 第三方库
import marisa_trie
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.models import SysDict
from __001__rag.storage.redis_service import redis_service

_SYS_DICT_CACHE: dict = {}
_nlp_ready = threading.Event()
_sys_dict_ready = threading.Event()
_nlp_load_error = None
_loading_started = False
_loading_lock = threading.Lock()


def _nlp_cache_key(name: str, default: str) -> str:
    """从 settings 读取 NLP 缓存 key。"""
    return getattr(settings, name, default)


def _get_sys_dict_cache_key() -> str:
    return _nlp_cache_key("NLP_SYS_DICT_CACHE_KEY", "nlp:cache:sys_dict")


def _get_trie_cache_key() -> str:
    return _nlp_cache_key("NLP_TRIE_CACHE_KEY", "nlp:cache:trie")


_YF_RAG_BANNER = r"""
 __     ________      _____            _____
 \ \   / /  ____|    |  __ \     /\   / ____|
  \ \_/ /| |__       | |__) |   /  \ | |  __
   \   / |  __|      |  _  /   / /\ \| | |_ |
    | |  | |         | | \ \  / ____ \ |__| |
    |_|  |_|         |_|  \_\/_/    \_\_____|
"""

_SENSITIVE_KEYS = {"PASSWORD", "SECRET_KEY", "ACCESS_KEY", "SECRET"}


def _mask(key: str, value):
    """如果字段名含敏感关键词则替换为 ********"""
    if any(s in key.upper() for s in _SENSITIVE_KEYS):
        return "********"
    return value


_ENV_LABELS = {
    "local": "本地开发",
    "test": "测试站",
    "prod": "正式环境",
    "standalone": "独立部署",
}


def show_yf_rag_banner():
    """输出启动 Banner，包含环境信息。"""
    env = getattr(settings, "DJANGO_ENV", "local")
    env_label = _ENV_LABELS.get(env, env)
    debug = getattr(settings, "DEBUG", False)
    pid = os.getpid()

    banner = _YF_RAG_BANNER
    info = (
        f"\n  环境: {env} ({env_label})"
        f"\n  调试: {'开启' if debug else '关闭'}"
        f"\n  PID:  {pid}"
        f"\n  配置: .env{f'.{env}' if env else ''} + .env"
    )
    logger.info(banner + info)


def show_configs():
    """输出当前运行配置摘要。"""
    db = getattr(settings, "DATABASES", {}).get("default", {})
    env = getattr(settings, "DJANGO_ENV", "local")
    env_label = _ENV_LABELS.get(env, env)

    groups = {
        "环境": {
            "DJANGO_ENV": env,
            "环境标签": env_label,
            "DEBUG": getattr(settings, "DEBUG", False),
        },
        "数据库": {
            "ENGINE": db.get("ENGINE", ""),
            "HOST": db.get("HOST", ""),
            "PORT": db.get("PORT", ""),
            "NAME": db.get("NAME", ""),
            "USER": db.get("USER", ""),
            "CONN_MAX_AGE": db.get("CONN_MAX_AGE", ""),
            "MAX_CONNECTIONS": db.get("MAX_CONNECTIONS", ""),
        },
        "Redis": {
            "HOST": getattr(settings, "REDIS_HOST", ""),
            "PORT": getattr(settings, "REDIS_PORT", ""),
            "DB_BROKER": getattr(settings, "REDIS_DB_BROKER", ""),
            "DB_RESULT": getattr(settings, "REDIS_DB_RESULT", ""),
            "DB_CACHE": getattr(settings, "REDIS_DB_CACHE", ""),
        },
        "MinIO": {
            "ENDPOINT": getattr(settings, "MINIO_HOST", ""),
            "SECURE": getattr(settings, "MINIO_SECURE", False),
            "USER": getattr(settings, "MINIO_USER", ""),
        },
        "Elasticsearch": {
            "HOSTS": getattr(settings, "ES_HOSTS", ""),
            "USER": getattr(settings, "ES_USERNAME", ""),
            "REQUEST_TIMEOUT": getattr(settings, "ES_REQUEST_TIMEOUT", ""),
            "VERIFY_CERTS": getattr(settings, "ES_VERIFY_CERTS", False),
        },
        "LLM 模型": {
            "LLM": getattr(settings, "LLM_MODEL_ID", ""),
            "Embedding": getattr(settings, "EMBEDDING_MODEL_ID", ""),
            "Rerank": getattr(settings, "RERANK_MODEL_ID", ""),
            "API_TIMEOUT": getattr(settings, "OPENAI_API_TIMEOUT", ""),
            "CONFIG_CACHE_TTL": getattr(settings, "CONFIG_CACHE_TTL", ""),
        },
        "NLP / 分词": {
            "MACBERT_MODEL": getattr(settings, "MACBERT_MODEL_NAME", ""),
            "CHUNK_TOKEN_NUM": getattr(settings, "MACBERT_CHUNK_TOKEN_NUM", ""),
            "PARENT_GROUP_SIZE": getattr(settings, "MACBERT_PARENT_GROUP_SIZE", ""),
            "CACHE_TTL": getattr(settings, "NLP_CACHE_TTL", ""),
            "TRIE_CACHE_KEY": getattr(settings, "NLP_TRIE_CACHE_KEY", ""),
            "SPECULATIVE_RETRIEVAL": getattr(settings, "ENABLE_SPECULATIVE_RETRIEVAL", ""),
        },
        "Celery": {
            "CONCURRENCY": getattr(settings, "CELERY_WORKER_CONCURRENCY", ""),
            "PREFETCH": getattr(settings, "CELERY_WORKER_PREFETCH_MULTIPLIER", ""),
            "TASK_SOFT_LIMIT": getattr(settings, "CELERY_TASK_SOFT_TIME_LIMIT", ""),
            "TASK_TIME_LIMIT": getattr(settings, "CELERY_TASK_TIME_LIMIT", ""),
            "MAX_RETRIES": getattr(settings, "CELERY_TASK_MAX_RETRIES", ""),
            "RESULT_EXPIRES": getattr(settings, "CELERY_RESULT_EXPIRES", ""),
        },
        "OCR / 文档解析": {
            "OCRFlux": getattr(settings, "OCRFLUX_API_URL", ""),
            "MinerU": getattr(settings, "MINERU_FILE_PARSE_URL", ""),
            "MINERU_MAX_CONCURRENCY": getattr(settings, "MINERU_MAX_CONCURRENCY", ""),
            "MAX_CONCURRENT_CHUNK": getattr(settings, "MAX_CONCURRENT_CHUNK_BUILDERS", ""),
        },
        "检索": {
            "BACKEND": getattr(settings, "SEARCH_BACKEND", ""),
            "MINIMUM_SHOULD_MATCH": getattr(settings, "RETRIEVAL_MINIMUM_SHOULD_MATCH", ""),
        },
        "业务配置": {
            "LLM_TENANT_ID": getattr(settings, "LLM_TENANT_ID", ""),
            "CUSTOM_KB_ID": getattr(settings, "CUSTOM_KB_ID", ""),
            "CHUNK_LEGACY_COMPAT": getattr(settings, "CHUNK_LEGACY_COMPAT", ""),
            "REDIS_LOCK_TIMEOUT": getattr(settings, "REDIS_LOCK_TIMEOUT", ""),
        },
    }

    lines = [f"当前 yf-rag 运行配置 ({env_label}):"]
    for group_name, items in groups.items():
        lines.append(f"  [{group_name}]")
        for key, value in items.items():
            lines.append(f"    {key} = {_mask(key, value)}")

    logger.info("\n".join(lines))


def get_sys_dict(key: str, default=None) -> dict | None:
    """获取 SysDict 缓存条目；若缓存未就绪则等待后回退查库。"""
    if _sys_dict_ready.is_set():
        return _SYS_DICT_CACHE.get(key, default)

    ready_timeout = float(getattr(settings, "SYS_DICT_READY_TIMEOUT", 10.0))
    if _sys_dict_ready.wait(timeout=ready_timeout):
        return _SYS_DICT_CACHE.get(key, default)

    # 超时回退：直接查库
    try:
        row = SysDict.objects.filter(status="1", key=key).values("id", "parent_id", "key", "value", "remark").first()
        if row:
            return {
                "id": row["id"],
                "parent_id": row["parent_id"],
                "value": row["value"],
                "remark": row["remark"],
            }
    except Exception:
        logger.exception("get_sys_dict 回退查库失败 key={}", key)
    return default


# ------------------------------------------------------------------
# Trie 管理器（mmap 加载 + Redis 缓存 + DB 兜底）
# ------------------------------------------------------------------

class TrieManager:
    """marisa_trie.BytesTrie 的三级加载管理：本地 mmap 文件 → Redis 缓存 → DB 构建。"""

    TRIE_DIR = Path(getattr(settings, "BASE_DIR", ".")) / ".trie_cache"
    TRIE_FILE = TRIE_DIR / "dict.marisa"

    @classmethod
    def load(cls, data) -> marisa_trie.BytesTrie:
        """加载顺序：本地文件 → Redis 缓存 → 从 NLPData 获取（DB 已构建）。"""
        # 1. 本地文件
        if cls.TRIE_FILE.exists():
            try:
                trie = marisa_trie.BytesTrie()
                trie.load(str(cls.TRIE_FILE))
                logger.info("marisa-trie 本地文件加载成功，词条 {} 条", len(trie))
                return trie
            except Exception:
                logger.exception("marisa-trie 本地文件加载失败，尝试下一级缓存")

        # 2. Redis 缓存
        trie = cls._load_from_redis()
        if trie is not None:
            return trie

        # 3. NLPData 中已构建的 trie（来自 DB）
        if data.dict_trie_entries is not None:
            cls._persist(data.dict_trie_entries)
            return data.dict_trie_entries

        logger.info("marisa-trie 无可用数据源，返回空 trie")
        return marisa_trie.BytesTrie()

    @classmethod
    def _load_from_redis(cls) -> marisa_trie.BytesTrie | None:
        """Redis base64 bytes → frombytes 直接加载（无需临时文件）。"""
        try:
            trie_key = _get_trie_cache_key()
            raw = redis_service.get(trie_key)
            if raw:
                trie_bytes = base64.b64decode(raw)
                trie = marisa_trie.BytesTrie()
                trie.frombytes(trie_bytes)
                # 补写本地文件，下次直接命中本地缓存
                try:
                    cls.TRIE_DIR.mkdir(parents=True, exist_ok=True)
                    cls.TRIE_FILE.write_bytes(trie_bytes)
                except Exception:
                    logger.exception("marisa-trie 本地文件补写失败")
                logger.info("marisa-trie 从 Redis 缓存加载成功，词条 {} 条", len(trie))
                return trie
        except Exception:
            try:
                redis_service.delete(_get_trie_cache_key())
                logger.info("marisa-trie Redis 缓存已失效，已删除")
            except Exception:
                logger.exception("marima-trie Redis 缓存删除失败")
            logger.exception("marisa-trie Redis 缓存加载失败")
        return None

    @classmethod
    def _persist(cls, trie: marisa_trie.BytesTrie) -> None:
        """持久化到本地文件 + Redis 缓存。"""
        try:
            trie_bytes = trie.tobytes()
            # 本地文件
            cls.TRIE_DIR.mkdir(parents=True, exist_ok=True)
            cls.TRIE_FILE.write_bytes(trie_bytes)
            # Redis 缓存
            ttl = getattr(settings, "NLP_CACHE_TTL", 86400)
            redis_service.set(
                _get_trie_cache_key(),
                base64.b64encode(trie_bytes).decode("ascii"),
                ex=ttl,
            )
            logger.info("marisa-trie 已持久化至本地文件 + Redis ({}KB, TTL={}s)",
                        len(trie_bytes) // 1024, ttl)
        except Exception:
            logger.exception("marisa-trie 持久化失败")


# ------------------------------------------------------------------
# 字典加载
# ------------------------------------------------------------------

def load_dicts():
    """同步加载 SysDict + NLP 数据。

    Gunicorn --preload 场景：master 进程中同步完成加载，fork 后 worker 直接继承内存状态。
    若使用后台线程，fork 时守护线程不会存活到子进程，导致 _nlp_ready 永远无法 set。
    """
    global _loading_started
    with _loading_lock:
        if _loading_started:
            return
        _loading_started = True

    logger.info("开始加载字典数据（同步模式）...")
    _load_all()


def _load_all():
    """SysDict → NLP 数据 → trie → 单例注入。"""
    t0 = time.monotonic()

    t_sys = time.monotonic()
    _load_sys_dict_inner()
    t_sys_elapsed = time.monotonic() - t_sys

    t_nlp = time.monotonic()
    _load_nlp_data()
    t_nlp_elapsed = time.monotonic() - t_nlp

    logger.info(
        "数据加载完成，总耗时 {:.3f}s (SysDict: {:.3f}s | NLP+Trie+单例: {:.3f}s)",
        time.monotonic() - t0, t_sys_elapsed, t_nlp_elapsed,
    )

    # Gunicorn --preload 模式下，master 加载完成后会 fork 出 worker。
    # 关闭 master 中创建的数据库连接，避免 fork 后多 worker 共享同一 socket。
    # 各 worker 在首次请求时会按需创建自己的连接。
    try:
        from django.db import connections
        connections.close_all()
        logger.info("已关闭 master 进程数据库连接（fork 安全）")
    except Exception:
        logger.exception("master 进程数据库连接关闭失败")


def _load_sys_dict_inner():
    """SysDict 加载：优先 Redis 缓存，回退数据库查询。"""
    global _SYS_DICT_CACHE
    t0 = time.monotonic()
    try:
        data = _load_sys_dict_from_redis()
        if data is not None:
            _SYS_DICT_CACHE = data
            logger.info("SysDict 缓存命中 (Redis)，共 {} 条，耗时 {:.3f}s", len(data), time.monotonic() - t0)
            return

        records = SysDict.objects.filter(status="1").values("id", "parent_id", "key", "value", "remark")
        cache: dict = {}
        for row in records:
            key = row.get("key") or row["id"]
            cache[key] = {
                "id": row["id"],
                "parent_id": row["parent_id"],
                "value": row["value"],
                "remark": row["remark"],
            }
        _SYS_DICT_CACHE = cache
        _save_sys_dict_to_redis(cache)
        logger.info("SysDict 从数据库加载完成，共 {} 条，耗时 {:.3f}s", len(cache), time.monotonic() - t0)
    except Exception as exc:
        logger.info("SysDict 加载跳过: {}", exc)
    finally:
        _sys_dict_ready.set()


def _load_sys_dict_from_redis() -> dict | None:
    """从 Redis 加载 SysDict 缓存。"""
    try:
        from __001__rag.nlp.data import _deserialize

        raw = redis_service.get(_get_sys_dict_cache_key())
        if raw:
            return _deserialize(raw)
    except Exception as e:
        logger.info("SysDict Redis 读取失败: {}，回退到数据库", e)
    return None


def _save_sys_dict_to_redis(cache: dict) -> None:
    """将 SysDict 缓存存入 Redis。"""
    try:
        from __001__rag.nlp.data import _serialize

        ttl = getattr(settings, "NLP_CACHE_TTL", 86400)
        redis_service.set(_get_sys_dict_cache_key(), _serialize(cache), ex=ttl)
    except Exception as e:
        logger.info("SysDict Redis 缓存写入失败: {}", e)


def _load_nlp_data():
    """加载 nltk 数据 → NLPData → TrieManager 加载 trie → 注入单例。"""
    global _nlp_load_error
    t0 = time.monotonic()
    try:
        # 检查 nltk 数据包，缺失时提示命令而非自动下载
        import nltk

        for pkg in ("punkt", "wordnet"):
            try:
                sub = f"tokenizers/{pkg}" if pkg == "punkt" else f"corpora/{pkg}"
                found = nltk.data.find(sub)
                logger.info("nltk 数据包已就绪: {} → {}", pkg, found)
            except LookupError:
                logger.info(
                    "nltk 数据包 {} 未找到，请运行: python -m nltk.downloader {}", pkg, pkg
                )

        from __001__rag.nlp.data import NLPData
        from __001__rag.nlp.tokenizer import tokenizer as nlp_tokenizer

        data = NLPData.load()

        # TrieManager 三级加载：本地文件 → Redis → DB
        trie = TrieManager.load(data)
        if trie is None or len(trie) == 0:
            # 所有缓存 miss，从 DB 强制构建
            logger.info("marisa-trie 所有缓存未命中，从数据库构建...")
            NLPData._load_tag(data, "dict")
            trie = data.dict_trie_entries
            if trie is not None:
                TrieManager._persist(trie)
        nlp_tokenizer.set_trie(trie)

        # 延迟导入 NLP 单例模块，避免 startup ↔ search ↔ query 循环依赖
        import __001__rag.nlp.query as q_mod
        import __001__rag.nlp.synonym as syn_mod
        import __001__rag.nlp.term_weight as tw_mod

        tw_mod.dealer = tw_mod.Dealer(data)
        syn_mod.dealer = syn_mod.Dealer(data)
        q_mod.queryer = q_mod.FulltextQueryer(tw=tw_mod.dealer, syn=syn_mod.dealer)

        logger.info("NLP 单例初始化完成 (marisa-trie)，总耗时 {:.3f}s", time.monotonic() - t0)
    except Exception as e:
        _nlp_load_error = e
        logger.exception("NLP 加载失败")
    finally:
        _nlp_ready.set()


def wait_nlp_ready(timeout: float | None = None) -> bool:
    """等待后台 NLP 数据加载完成，返回 True 表示已就绪。"""
    _timeout = timeout if timeout is not None else float(getattr(settings, "NLP_READY_TIMEOUT", 60.0))
    return _nlp_ready.wait(_timeout)


def clear_nlp_cache():
    """清除 Redis 中的 NLP 缓存及本地 trie 文件，下次启动将重新从数据库加载。"""
    keys = [
        getattr(settings, "NLP_DATA_CACHE_KEY", "nlp:cache:data"),
        _get_sys_dict_cache_key(),
        _get_trie_cache_key(),
    ]
    for key in keys:
        redis_service.delete(key)
    # 清除本地 trie 文件
    try:
        if TrieManager.TRIE_FILE.exists():
            TrieManager.TRIE_FILE.unlink()
            logger.info("本地 marisa-trie 文件已删除: {}", TrieManager.TRIE_FILE)
    except Exception:
        logger.exception("本地 marisa-trie 文件删除失败")
    logger.info("NLP 缓存已清除 (Redis + 本地文件)")
