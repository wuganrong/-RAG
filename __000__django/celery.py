"""Celery 应用配置。

使用方式：
    celery -A __000__django worker --pool=eventlet --loglevel=info
    celery -A __000__django worker --pool=solo -Q vision --loglevel=info
"""

from __future__ import annotations

# 1. Python 标准库
import os

# 2. 第三方库
from celery import Celery
from celery.signals import task_prerun
from loguru import logger

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "__000__django.settings")

app = Celery("yf-rag")

app.config_from_object("django.conf:settings", namespace="CELERY")

app.autodiscover_tasks()


@task_prerun.connect
def _set_task_trace(task_id, task=None, **kwargs):
    """将 Celery task_id 注入 trace_id 上下文，使日志可追溯。"""
    from __001__rag.utils.context import set_trace_id

    set_trace_id(task_id)
    logger.info("Celery 任务开始 task_id={} task={}", task_id, task.name if task else "?")
