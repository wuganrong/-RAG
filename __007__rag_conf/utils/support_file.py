"""支持文件管理接口辅助函数。"""

from __future__ import annotations

# 1. Python 标准库
from typing import Any

# 2. 第三方库
from django.db.models import Q

# 3. 本地应用
from __001__rag.models import ChunkMethod, FileTypeMapping
from __001__rag.utils import format_datetime


def normalize_file_type(ft: str) -> str:
    """标准化文件类型：去空格、去前缀点、转小写。"""
    return ft.strip().lstrip(".").lower()


def serialize_mapping(row: dict[str, Any]) -> dict[str, Any]:
    """将 ORM values 行转为可 JSON 序列化的映射字典。"""
    return {
        "id": row["id"],
        "file_type": row["file_type"],
        "parser_id": row["parser_id"],
        "status": row.get("status") or "1",
        "create_date": format_datetime(row.get("create_date")),
        "update_date": format_datetime(row.get("update_date")),
    }


def serialize_method(row: dict[str, Any]) -> dict[str, Any]:
    """将 ORM values 行转为可 JSON 序列化的方法字典。"""
    return {
        "method": row["method"],
        "method_type": row["method_type"],
        "display_name": row.get("display_name") or "",
        "method_class": row.get("method_class") or "",
        "status": row.get("status") or "1",
        "create_date": format_datetime(row.get("create_date")),
        "update_date": format_datetime(row.get("update_date")),
    }


def get_mapping_by_id(mapping_id: str) -> dict[str, Any] | None:
    """通过 id 获取单条映射记录。"""
    rows = list(
        FileTypeMapping.objects.filter(id=mapping_id).values(
            "id", "file_type", "parser_id", "status", "create_date", "update_date"
        )
    )
    return serialize_mapping(rows[0]) if rows else None


def get_method_obj(method: str, method_type: str = "") -> dict[str, Any] | None:
    """获取单条方法记录。"""
    qs = ChunkMethod.objects.filter(method=method)
    if method_type:
        qs = qs.filter(method_type=method_type)
    rows = list(
        qs.values("method", "method_type", "display_name", "method_class",
                   "status", "create_date", "update_date")
    )
    return serialize_method(rows[0]) if rows else None


def filter_mappings(keywords: str, status: str):
    """共享的映射过滤查询，返回 QuerySet。

    支持按 status 精确过滤，按 keywords 模糊匹配
    file_type / parser_id / parser 的 display_name / method_class。
    """
    qs = FileTypeMapping.objects.all()

    if status:
        qs = qs.filter(status=status)

    if keywords:
        # 查找关联 parser 的 display_name / method_class
        parser_methods = ChunkMethod.objects.filter(
            method_type="parser"
        ).filter(
            Q(display_name__icontains=keywords) | Q(method_class__icontains=keywords)
        ).values_list("method", flat=True)

        qs = qs.filter(
            Q(file_type__icontains=keywords)
            | Q(parser_id__icontains=keywords)
            | Q(parser_id__in=parser_methods)
        )

    return qs.order_by("-create_date")


def get_file_types_by_parser(parser_id: str) -> list[str]:
    """查询指定解析方法支持的启用状态文件类型列表。

    Args:
        parser_id: 解析方法标识（如 naive、mineru）

    Returns:
        去重的文件扩展名列表，如 ["pdf", "docx", "md"]
    """
    rows = list(
        FileTypeMapping.objects.filter(
            parser_id=parser_id, status="1"
        ).values_list("file_type", flat=True).distinct()
    )
    return rows


def get_parsers_by_file_type(file_type: str) -> list[dict[str, str]]:
    """查询指定文件类型可用的启用状态解析方法列表。

    从 FileTypeMapping 获取 parser_id 列表，再从 ChunkMethod 获取 display_name。

    Args:
        file_type: 文件类型（如 pdf、docx）

    Returns:
        解析方法列表，每项含 method 和 display_name，
        如 [{"method": "naive", "display_name": "General"}]
    """
    parser_ids = list(
        FileTypeMapping.objects.filter(
            file_type=file_type, status="1"
        ).values_list("parser_id", flat=True).distinct()
    )
    if not parser_ids:
        return []

    methods = list(
        ChunkMethod.objects.filter(
            method__in=parser_ids, method_type="parser"
        ).values("method", "display_name")
    )
    return [
        {"method": m["method"], "display_name": m.get("display_name") or m["method"]}
        for m in methods
    ]
