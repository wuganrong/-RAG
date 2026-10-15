from __future__ import annotations

from typing import Any


def rrf_merge(rank_lists: list[list[dict[str, Any]]], id_key: str = "id", k: int = 60) -> list[dict[str, Any]]:
    scores: dict[str, float] = {}
    items: dict[str, dict[str, Any]] = {}
    for ranked in rank_lists:
        for rank, item in enumerate(ranked, start=1):
            key = str(item.get(id_key) or item.get("preview") or rank)
            scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
            items[key] = item
    ordered = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)
    merged = []
    for key, score in ordered:
        item = dict(items[key])
        item["rrf"] = round(score, 6)
        item["score"] = round(max(float(item.get("score") or 0), score), 4)
        merged.append(item)
    return merged
