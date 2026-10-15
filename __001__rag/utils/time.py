"""时间处理工具函数。"""

from __future__ import annotations

# 1. Python 标准库
import datetime as _dt
from typing import Any
from zoneinfo import ZoneInfo

# 2. 第三方库
import pytz

_SHANGHAI_ZONEINFO = ZoneInfo("Asia/Shanghai")
_SHANGHAI_PYTZ = pytz.timezone("Asia/Shanghai")


def now_shanghai() -> _dt.datetime:
    """返回当前 Asia/Shanghai 时区时间（timezone-aware，由 pytz 提供时区）。

    与 Django `USE_TZ=True` 配合：写入 ORM 时 Django 会统一换算为 UTC 存入 MySQL；
    读回为 UTC 时刻正确的 aware datetime。请勿再把入库后的 naive UTC 数字当成「上海墙钟」解析。
    """
    return _dt.datetime.now(tz=_SHANGHAI_PYTZ)


def to_ms_timestamp(dt: Any) -> int | None:
    """将 DateTimeField 值转换为毫秒级 Unix 时间戳，None 时返回 None。

    Django `USE_TZ=True` 时，从 ORM 读出的一般为 **带 tz 的 UTC**（或当前时区），
    应直接使用 ``timestamp()``，与数据库中存储的 UTC 瞬时一致。

    兼容历史数据：若为 **naive**，仍按项目旧约定视作 Asia/Shanghai 墙钟时间再转时间戳。
    """
    if dt is None:
        return None
    if not isinstance(dt, _dt.datetime):
        return None
    if dt.tzinfo is not None:
        return int(dt.timestamp() * 1000)
    naive_dt = dt.replace(tzinfo=None)
    shanghai_dt = naive_dt.replace(tzinfo=_SHANGHAI_ZONEINFO)
    return int(shanghai_dt.timestamp() * 1000)


def format_datetime(dt: Any, fmt: str = "%Y-%m-%d %H:%M:%S") -> str | None:
    """将 datetime 格式化为本地时间字符串，None 时返回 None。

    Django `USE_TZ=True` 时，ORM 读出的是 aware datetime（UTC 或当前时区），
    会先转换为本地时间再格式化。

    Args:
        dt: datetime 对象，None 或非 datetime 返回 None
        fmt: strftime 格式字符串，默认 ``YYYY-MM-DD HH:mm:ss``

    Returns:
        格式化后的时间字符串，或 None
    """
    if dt is None:
        return None
    if not isinstance(dt, _dt.datetime):
        return None
    if dt.tzinfo is not None:
        from django.utils import timezone as _tz
        dt = _tz.localtime(dt)
    return dt.strftime(fmt)
