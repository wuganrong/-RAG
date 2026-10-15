"""请求/任务上下文管理 — 提供 trace_id 贯穿日志链路。"""

from __future__ import annotations

# 1. Python 标准库
import contextvars
import uuid

# trace_id 上下文变量：HTTP 请求由中间件注入，Celery 任务由信号注入
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")


def get_trace_id() -> str:
    """获取当前协程/线程的 trace_id。"""
    return trace_id_var.get()


def set_trace_id(tid: str | None = None) -> str:
    """设置当前协程/线程的 trace_id，返回实际生效的值。"""
    tid = tid or uuid.uuid4().hex[:16]
    trace_id_var.set(tid)
    return tid
