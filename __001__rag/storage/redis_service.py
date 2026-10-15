"""Redis 存储服务 — 直接封装 redis.Redis，提供键值/集合/有序集合/分布式锁。"""

from __future__ import annotations

# 1. Python 标准库
import time
import uuid
from typing import Any

# 2. 第三方库
import redis
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.utils.redis import redis_json_dumps, redis_json_loads

# 哨兵值：区分 "调用方未提供 default" 和 "default=None"
_SENTINEL = object()


class RedisService:
    """Redis 通用存储服务，直接封装 redis.Redis 客户端。"""

    LUA_DELETE_IF_EQUAL = """
        local val = redis.call('get', KEYS[1])
        if val and val == ARGV[1] then
            return redis.call('del', KEYS[1])
        end
        return 0
    """

    _WRITE_METHODS = frozenset({
        "set", "delete", "sadd", "srem", "zadd", "zrem",
        "setex", "setnx", "incr", "decr", "lpush", "rpush",
        "expire", "persist",
    })

    def __init__(self):
        self._client: redis.Redis | None = None
        self._delete_if_equal_script = None

    @property
    def client(self) -> redis.Redis:
        if self._client is None:
            self._client = self._open()
            self._register_scripts()
        return self._client

    def _open(self) -> redis.Redis:
        return redis.Redis(
            host=getattr(settings, "REDIS_HOST", "192.168.0.21"),
            port=int(getattr(settings, "REDIS_PORT", 6378)),
            db=int(getattr(settings, "REDIS_DB_CACHE", 2)),
            password=getattr(settings, "REDIS_PASSWORD", None) or None,
            decode_responses=True,
        )

    def _register_scripts(self):
        register = getattr(self._client, "register_script", None)
        if callable(register):
            self._delete_if_equal_script = register(self.LUA_DELETE_IF_EQUAL)

    def _reopen(self):
        self._client = self._open()
        self._register_scripts()

    def _call(self, method: str, *args, default=_SENTINEL, critical: bool = False, **kwargs):
        """执行 Redis 命令。

        Args:
            method: Redis 命令名
            default: 失败时返回的默认值（未提供时返回 None）
            critical: True 时失败后抛出异常（分布式锁等关键操作），
                      False 时静默降级返回 default
        """
        try:
            return getattr(self.client, method)(*args, **kwargs)
        except Exception:
            if critical:
                logger.exception("Redis {} 严重故障", method)
                raise
            logger.exception("Redis {} 失败，返回默认值", method)
            self._reopen()
            return None if default is _SENTINEL else default

    # -- 基础 KV --

    def get(self, key: str) -> str | None:
        return self._call("get", key)

    def set(self, key: str, value: str, ex: int | None = None, nx: bool = False, *, critical: bool = False) -> bool:
        return bool(self._call("set", key, value, ex=ex, nx=nx, default=False, critical=critical))

    def delete(self, key: str) -> bool:
        return bool(self._call("delete", key, default=False))

    def exists(self, key: str) -> bool:
        return bool(self._call("exists", key, default=False))

    def set_nx(self, key: str, value: str, ex: int | None = None, *, critical: bool = False) -> bool:
        return self.set(key, value, ex=ex, nx=True, critical=critical)

    # -- JSON KV --

    def get_json(self, key: str, default=None):
        raw = self.get(key)
        return redis_json_loads(raw, default=default)

    def set_json(self, key: str, value, ex: int | None = None) -> bool:
        return self.set(key, redis_json_dumps(value), ex=ex)

    # -- 集合 --

    def sadd(self, key: str, member: str) -> bool:
        return bool(self._call("sadd", key, member, default=False))

    def srem(self, key: str, member: str) -> bool:
        return bool(self._call("srem", key, member, default=False))

    def smembers(self, key: str) -> set[str]:
        return self._call("smembers", key, default=set()) or set()

    # -- 有序集合 --

    def zadd(self, key: str, member: str, score: float) -> bool:
        return bool(self._call("zadd", key, {member: score}, default=False))

    def zcount(self, key: str, min_score: float, max_score: float) -> int:
        return int(self._call("zcount", key, min_score, max_score, default=0) or 0)

    def zpopmin(self, key: str, count: int = 1) -> list[tuple[str, float]]:
        return self._call("zpopmin", key, count, default=[]) or []

    def zrangebyscore(self, key: str, min_score: float, max_score: float) -> list[str]:
        return self._call("zrangebyscore", key, min_score, max_score, default=[]) or []

    # -- 分布式锁 --

    def lock(
        self,
        key: str,
        value: str | None = None,
        timeout: int | None = None,
        blocking_timeout: float | None = None,
    ) -> "RedisDistributedLock":
        _timeout = timeout if timeout is not None else int(getattr(settings, "REDIS_LOCK_TIMEOUT", 10))
        _blocking = blocking_timeout if blocking_timeout is not None else float(getattr(settings, "REDIS_LOCK_BLOCKING_TIMEOUT", 1.0))
        return RedisDistributedLock(
            storage=self,
            key=key,
            value=value or str(uuid.uuid4()),
            timeout=_timeout,
            blocking_timeout=_blocking,
        )

    # -- 工具 --

    def delete_if_equal(self, key: str, expected_value: str) -> bool:
        try:
            if self._delete_if_equal_script is not None:
                return bool(self._delete_if_equal_script(keys=[key], args=[expected_value]))
            if self.client.get(key) == expected_value:
                self.client.delete(key)
                return True
            return False
        except Exception:
            logger.exception("Redis delete_if_equal 失败 key={}", key)
            self._reopen()
            return False

    def health(self) -> bool:
        self.client.ping()
        key = "redis_health_check"
        value = "ok"
        ttl = int(getattr(settings, "REDIS_HEALTH_CHECK_TTL", 3))
        self.client.set(key, value, ex=ttl)
        return self.client.get(key) == value

    def is_alive(self) -> bool:
        try:
            return bool(self.client.ping())
        except Exception:
            logger.exception("Redis 连接不可用")
            return False


class RedisDistributedLock:
    """基于 Redis SET NX 的轻量分布式锁。"""

    def __init__(
        self,
        storage: RedisService,
        key: str,
        value: str,
        timeout: int = 10,
        blocking_timeout: float | None = 1.0,
    ) -> None:
        # timeout / blocking_timeout 由调用方（RedisService.lock）从 settings 注入
        self.storage = storage
        self.key = key
        self.value = value
        self.timeout = timeout
        self.blocking_timeout = blocking_timeout
        self.acquired = False

    def acquire(self) -> bool:
        start = time.monotonic()
        while True:
            self.acquired = self.storage.set_nx(self.key, self.value, ex=self.timeout, critical=True)
            if self.acquired:
                return True
            if self.blocking_timeout is None:
                time.sleep(0.1)
                continue
            if self.blocking_timeout <= 0 or time.monotonic() - start >= self.blocking_timeout:
                return False
            time.sleep(0.1)

    def release(self) -> bool:
        released = self.storage.delete_if_equal(self.key, self.value)
        if released:
            self.acquired = False
        return released

    def __enter__(self) -> "RedisDistributedLock":
        if not self.acquire():
            raise TimeoutError(f"Redis 锁获取超时: {self.key}")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()


redis_service = RedisService()
