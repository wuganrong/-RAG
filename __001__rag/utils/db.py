"""Django ORM 相关通用工具。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.db.models import F, Value
from django.db.models.functions import Coalesce, Concat


def check_duplicate_name(model: Any, exclude_id: str | None = None, **filters: Any) -> bool:
    """检查模型中是否存在重复名称记录。

    Args:
        model: Django Model 类。
        exclude_id: 更新时排除自身的主键，新建时传 None。
        **filters: 过滤条件，通常包含 name 和 status 等字段。

    Returns:
        True 表示已存在重名记录，False 表示无重名。
    """
    qs = model.objects.filter(**filters)
    if exclude_id is not None:
        qs = qs.exclude(id=exclude_id)
    return qs.exists()


def append_progress_msg_expr(msg: str):
    """生成向 progress_msg 字段追加消息的 Django ORM 表达式。

    返回 Concat(Coalesce(F("progress_msg"), Value("")), Value(msg))
    可在 update() 中直接使用。
    """
    return Concat(Coalesce(F("progress_msg"), Value("")), Value(msg))
