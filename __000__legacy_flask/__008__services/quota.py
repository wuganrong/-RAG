from __future__ import annotations

from datetime import date

from __000__common.__003__orm.db import session_scope
from __000__common.__003__orm.ids import new_id
from __000__common.__003__orm.models import QuotaUsage, User
from __004__store.cache.redis_cache import get_redis


def _day() -> str:
    return date.today().isoformat()


def consume(user_id: str, kind: str, amount: int = 1) -> None:
    user = None
    with session_scope() as session:
        user = session.get(User, user_id)
        if user is None:
            return
        limit = user.daily_query_limit if kind == "queries" else user.daily_upload_limit
        redis = get_redis()
        key = f"quota:{user_id}:{_day()}:{kind}"
        used = 0
        if redis is not None:
            used = int(redis.incrby(key, amount))
            redis.expire(key, 36 * 3600)
        else:
            row = session.query(QuotaUsage).filter_by(user_id=user_id, day=_day()).first()
            if row is None:
                row = QuotaUsage(id=new_id(), user_id=user_id, day=_day(), queries=0, uploads=0)
                session.add(row)
            if kind == "queries":
                row.queries += amount
                used = row.queries
            else:
                row.uploads += amount
                used = row.uploads
        if used > limit:
            if redis is not None:
                redis.decrby(key, amount)
            elif kind == "queries":
                row.queries -= amount
            else:
                row.uploads -= amount
            raise ValueError(f"今日{('问答' if kind == 'queries' else '上传')}次数已达上限 {limit}")


def snapshot(user_id: str) -> dict:
    with session_scope() as session:
        user = session.get(User, user_id)
        row = session.query(QuotaUsage).filter_by(user_id=user_id, day=_day()).first()
        redis = get_redis()
        queries = int(redis.get(f"quota:{user_id}:{_day()}:queries") or 0) if redis else (row.queries if row else 0)
        uploads = int(redis.get(f"quota:{user_id}:{_day()}:uploads") or 0) if redis else (row.uploads if row else 0)
        return {
            "queries": queries,
            "uploads": uploads,
            "query_limit": user.daily_query_limit if user else 100,
            "upload_limit": user.daily_upload_limit if user else 50,
        }
