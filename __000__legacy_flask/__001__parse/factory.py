from __future__ import annotations

from __001__parse.naive import parse_document_to_text


def parse_document(path: str, parser_id: str = "naive") -> str:
    if parser_id in {"naive", "", None}:
        return parse_document_to_text(path)
    raise ValueError(f"不支持的解析器: {parser_id}")
