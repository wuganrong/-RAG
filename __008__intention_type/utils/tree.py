"""意图类型树形结构工具函数。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from loguru import logger

# 3. 本地应用
from __001__rag.models import IntentionType


def _intention_node_to_dict(it: Any) -> dict[str, Any]:
    """将 IntentionType 实例转为 Element UI Tree 节点字典（仅 id/label/status/children）。"""
    return {
        "id": it.id,
        "label": it.intention or "",
        "status": it.status,
        "children": [],
    }


def build_intention_tree(queryset: Any | None = None, status: str = "") -> list[dict[str, Any]]:
    """将意图类型 QuerySet 构建为 Element UI Tree 所需的树形结构。

    Args:
        queryset: IntentionType 查询集，传 None 时自动查询全部。
        status: 可选状态过滤，如 "1" 仅返回有效节点；空字符串表示不过滤。

    Returns:
        根节点列表，每个节点含 children 嵌套子节点。
    """
    if queryset is None:
        queryset = IntentionType.objects.all()

    if status:
        queryset = queryset.filter(status=status)

    queryset = queryset.order_by("depth", "create_date")
    all_nodes = list(queryset)
    logger.info("构建意图树：共加载 {} 条节点", len(all_nodes))

    node_map: dict[int, dict[str, Any]] = {}
    for it in all_nodes:
        node_map[it.id] = _intention_node_to_dict(it)

    roots: list[dict[str, Any]] = []
    for it in all_nodes:
        node = node_map[it.id]
        parent_id = it.parent_id
        if parent_id and parent_id in node_map:
            node_map[parent_id]["children"].append(node)
        else:
            roots.append(node)

    logger.info("意图树构建完成：根节点数量 {}", len(roots))
    return roots


def calc_depth_and_path(parent_id: int | None, intention: str) -> tuple[int, str]:
    """根据父节点 ID 与意图名称计算当前节点的层级深度和路径。

    Args:
        parent_id: 父节点 ID，根节点传 None 或空字符串。
        intention: 当前节点的意图名称。

    Returns:
        (depth, path) 元组。
    """
    if not parent_id:
        return 0, f"/{intention}"

    try:
        parent = IntentionType.objects.get(id=parent_id)
        depth = parent.depth + 1
        parent_path = parent.path or f"/{parent.intention}"
        path = f"{parent_path}/{intention}"
        return depth, path
    except IntentionType.DoesNotExist:
        logger.info("父节点不存在 parent_id={}，将作为根节点处理", parent_id)
        return 0, f"/{intention}"
