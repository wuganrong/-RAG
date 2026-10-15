"""Django AppConfig for the rag app."""

# 1. Python 标准库
import os
import sys

# 2. 第三方库
from django.apps import AppConfig
from loguru import logger


class RagConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "__001__rag"
    label = "rag"

    def ready(self):
        # sys.argv 在某些子进程中可能为 None
        if not sys.argv:
            return

        # runserver 自动重载会启动父子两个进程，仅在子进程加载字典
        # 父进程无 RUN_MAIN 环境变量，子进程有 RUN_MAIN="true"
        is_runserver = "runserver" in " ".join(sys.argv)
        if is_runserver and os.environ.get("RUN_MAIN") != "true":
            return

        argv_str = " ".join(sys.argv)
        is_celery_worker = "celery" in argv_str and "worker" in argv_str
        is_gunicorn = "gunicorn" in argv_str

        if not (is_runserver or is_celery_worker or is_gunicorn):
            return

        # 连接缓存失效信号（在 load_dicts 之前，确保信号就绪）
        from __001__rag.cache.signals import connect_cache_signals
        connect_cache_signals()

        from __001__rag.startup import load_dicts, show_yf_rag_banner, show_configs

        try:
            show_yf_rag_banner()
            show_configs()
            load_dicts()
            from __001__rag.cache.manager import CacheManager
            CacheManager.prewarm_all()
        except Exception:
            logger.exception("启动预热失败，服务仍继续（检查 Redis / 词典）")
