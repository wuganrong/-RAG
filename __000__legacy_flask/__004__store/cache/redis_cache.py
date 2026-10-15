from __future__ import annotations

from __000__common.__002__log import get_logger
from __000__common.__004__infra import REDIS_DB, REDIS_HOST, REDIS_PASSWORD, REDIS_PORT

logger = get_logger(__name__)

_client = None
_failed = False


def get_redis(retry: bool = False):
    global _client, _failed
    if retry:
        _failed = False
        _client = None
    if _failed:
        return None
    if _client is not None:
        return _client
    try:
        import redis

        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD or None,
            db=REDIS_DB,
            socket_timeout=2,
            socket_connect_timeout=2,
            decode_responses=True,
        )
        client.ping()
        _client = client
        logger.info("Redis ready %s:%s/%s", REDIS_HOST, REDIS_PORT, REDIS_DB)
        return _client
    except Exception as exc:
        _failed = True
        logger.warning("Redis unavailable, fallback local cache: %s", exc)
        return None


def health(retry: bool = False) -> dict:
    client = get_redis(retry=retry)
    return {"ok": client is not None, "host": f"{REDIS_HOST}:{REDIS_PORT}"}
