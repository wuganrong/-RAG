"""重试工具。"""

from __future__ import annotations

# 1. Python 标准库
import time
from typing import Callable

# 2. 第三方库
from django.conf import settings
from loguru import logger


def retry_call(
    fn: Callable,
    *args,
    op_name: str = "",
    reconnect_fn: Callable[[], None] | None = None,
    on_retry: Callable[[], None] | None = None,
    max_retries_setting: str = "MINIO_PUT_MAX_RETRIES",
    sleep_setting: str = "MINIO_RETRY_SLEEP_SECONDS",
    default_retries: int = 3,
    default_sleep: int = 1,
    on_failure: str = "raise",
) -> object | None:
    """带重连的重试调用。

    Args:
        fn: 要重试的无参可调用对象
        op_name: 操作名称，用于日志标识（默认取 fn.__name__）
        reconnect_fn: 重连回调
        on_retry: 每次重试前额外执行的回调（如 file_obj.seek(0)）
        max_retries_setting: 最大重试次数的 settings key
        sleep_setting: 重试间隔秒数的 settings key
        default_retries: 默认最大重试次数
        default_sleep: 默认重试间隔秒数
        on_failure: "raise" 抛出原始异常，"none" 返回 None
    """
    op_name = op_name or getattr(fn, "__name__", "unknown")
    max_retries = getattr(settings, max_retries_setting, default_retries)
    sleep_sec = getattr(settings, sleep_setting, default_sleep)
    last_exc: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except Exception as exc:
            last_exc = exc
            if attempt < max_retries:
                logger.info("{} 第 {}/{} 次尝试失败，准备重试 err={}", op_name, attempt, max_retries, exc)
            if on_retry:
                on_retry()
            if reconnect_fn:
                try:
                    reconnect_fn()
                except Exception:
                    logger.exception("[RETRY] 重连回调执行失败")
            time.sleep(sleep_sec)
    # 重试耗尽
    if on_failure == "none":
        logger.exception("{} 重试 {} 次后仍然失败", op_name, max_retries)
        return None
    logger.exception("{} 重试 {} 次后仍然失败", op_name, max_retries)
    raise last_exc or RuntimeError("重试耗尽")
