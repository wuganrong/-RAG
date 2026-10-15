"""检索表达式与数据结构。"""

from __future__ import annotations

# 1. Python 标准库
from dataclasses import dataclass, field
from typing import Any, Literal

Vector = list[float] | list[int]
DistanceType = Literal["cosine", "dot_product", "l2"]
FusionMethod = Literal["weighted_sum", "rrf"]


@dataclass(slots=True)
class SparseVector:
    """稀疏向量表达。"""

    indices: list[int]
    values: list[float] | list[int] | None = None

    def __post_init__(self) -> None:
        if self.values is not None and len(self.indices) != len(self.values):
            raise ValueError("SparseVector.indices and values must have the same length")

    def to_dict(self) -> dict[str, float | int]:
        """转换为 ES 等后端常用的 key-value 稀疏向量格式。"""
        if self.values is None:
            raise ValueError("SparseVector.values is None")
        return {str(index): value for index, value in zip(self.indices, self.values)}


@dataclass(slots=True)
class MatchTextExpr:
    """全文检索表达式。"""

    fields: list[str]
    matching_text: str
    topn: int
    extra_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MatchDenseExpr:
    """稠密向量检索表达式。"""

    vector_field: str
    embedding: Vector
    distance_type: DistanceType = "cosine"
    topn: int = 10
    extra_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class MatchSparseExpr:
    """稀疏向量检索表达式。"""

    vector_field: str
    sparse_data: SparseVector | dict[str, float | int]
    distance_type: DistanceType = "dot_product"
    topn: int = 10
    extra_options: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class FusionExpr:
    """多路召回融合表达式。"""

    method: FusionMethod
    topn: int
    params: dict[str, Any] = field(default_factory=dict)


MatchExpr = MatchTextExpr | MatchDenseExpr | MatchSparseExpr | FusionExpr


@dataclass(slots=True)
class OrderByExpr:
    """排序表达式。"""

    fields: list[tuple[str, Literal["asc", "desc"]]] = field(default_factory=list)

    def asc(self, field_name: str) -> "OrderByExpr":
        self.fields.append((field_name, "asc"))
        return self

    def desc(self, field_name: str) -> "OrderByExpr":
        self.fields.append((field_name, "desc"))
        return self


@dataclass(slots=True)
class SearchRequest:
    """检索请求。"""

    index_names: str | list[str]
    kb_ids: list[str]
    match_exprs: list[MatchExpr]
    select_fields: list[str] = field(default_factory=list)
    highlight_fields: list[str] = field(default_factory=list)
    filters: dict[str, Any] = field(default_factory=dict)
    order_by: OrderByExpr = field(default_factory=OrderByExpr)
    offset: int = 0
    limit: int = 10
    agg_fields: list[str] = field(default_factory=list)
    rank_feature: dict[str, Any] | None = None


@dataclass(slots=True)
class SearchResult:
    """检索响应。"""

    total: int
    chunks: list[dict[str, Any]]
    aggregations: dict[str, Any] = field(default_factory=dict)
    highlights: dict[str, Any] = field(default_factory=dict)
    raw: Any | None = None
