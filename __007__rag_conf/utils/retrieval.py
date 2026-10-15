"""检索方法配置接口辅助函数。"""

from __future__ import annotations

# 2. 第三方库
from loguru import logger

# 3. 本地应用
from __001__rag.models import RetrievalMethod


def list_retrieval_methods() -> list[dict[str, str]]:
    """查询所有启用状态的检索方法，按创建时间升序返回 label/value 格式列表。

    Returns:
        list: 每项格式为 {"label": display_name, "value": method}
    """
    methods = (
        RetrievalMethod.objects.filter(status="1")
        .values("method", "display_name")
        .order_by("create_date")
    )
    items = [
        {"label": item["display_name"] or "", "value": item["method"]}
        for item in methods
    ]
    logger.info("查询检索方法列表成功，共 {} 条", len(items))
    return items
