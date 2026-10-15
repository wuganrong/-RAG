"""Pure helpers for converting parsed documents into chunkable text."""

from __future__ import annotations

# 1. Python 标准库
import csv
import re
from dataclasses import dataclass
from io import StringIO
from typing import Any

# 3. 本地应用
from __001__rag.nlp.utils.indexing_tokenizer import estimate_token_count
from __001__rag.parse.base import ParsedDocument, ParsedElement

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_QA_RE = re.compile(
    r"(?:^|\n)\s*(?:Q|Question|问题|问)[:：]\s*(?P<q>.+?)\s*(?:\n|\r\n)+\s*(?:A|Answer|答案|答)[:：]\s*(?P<a>.+?)(?=\n\s*(?:Q|Question|问题|问)[:：]|\Z)",
    re.IGNORECASE | re.DOTALL,
)


@dataclass(slots=True)
class TextSection:
    """A chunkable section extracted from Markdown or parsed elements."""

    title: str | None
    content: str
    page: int | None = None
    metadata: dict[str, Any] | None = None


def document_text(document: ParsedDocument) -> str:
    """Join non-empty parsed elements into a single text body."""
    return "\n\n".join(element.content.strip() for element in document.elements if element.content and element.content.strip())


def document_sections(document: ParsedDocument) -> list[TextSection]:
    """Extract sections while preserving element title/page metadata where possible."""
    sections: list[TextSection] = []
    for element in document.elements:
        content = (element.content or "").strip()
        if not content:
            continue
        if element.element_type == "markdown":
            sections.extend(split_markdown_sections(content, default_page=element.page, metadata=element.metadata))
            continue
        title = element.title or (content if element.element_type == "title" else None)
        sections.append(
            TextSection(
                title=title,
                content=content,
                page=element.page,
                metadata={"element_type": element.element_type, **(element.metadata or {})},
            )
        )
    if sections:
        return sections
    text = document_text(document)
    return [TextSection(title=None, content=text)] if text else []


def split_markdown_sections(
    markdown_content: str,
    *,
    default_page: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[TextSection]:
    """Split Markdown by headings, keeping each heading with its body."""
    lines = (markdown_content or "").splitlines()
    sections: list[TextSection] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_lines
        content = "\n".join(line for line in current_lines).strip()
        if content:
            sections.append(
                TextSection(
                    title=current_title,
                    content=content,
                    page=default_page,
                    metadata=dict(metadata or {}),
                )
            )
        current_lines = []

    for line in lines:
        match = _HEADING_RE.match(line)
        if match:
            flush()
            current_title = match.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)
    flush()
    if sections:
        return sections
    text = (markdown_content or "").strip()
    return [TextSection(title=None, content=text, page=default_page, metadata=dict(metadata or {}))] if text else []


def split_text_by_token_budget(text: str, max_tokens: int, delimiter: str = "\n\n") -> list[str]:
    """Split text into chunks no larger than an approximate token budget."""
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    max_tokens = max(int(max_tokens or 0), 1)
    if estimate_token_count(cleaned) <= max_tokens:
        return [cleaned]

    parts = [part.strip() for part in cleaned.split(delimiter) if part.strip()] if delimiter else []
    if len(parts) <= 1:
        parts = [part.strip() for part in re.split(r"(?<=[。！？.!?])\s+|\n+", cleaned) if part.strip()]
    if len(parts) <= 1:
        return _hard_split_by_chars(cleaned, max_tokens)

    chunks: list[str] = []
    current: list[str] = []
    for part in parts:
        candidate = delimiter.join([*current, part]) if current and delimiter else "\n\n".join([*current, part])
        if current and estimate_token_count(candidate) > max_tokens:
            chunks.append((delimiter if delimiter else "\n\n").join(current).strip())
            current = [part]
        elif estimate_token_count(part) > max_tokens:
            if current:
                chunks.append((delimiter if delimiter else "\n\n").join(current).strip())
                current = []
            chunks.extend(_hard_split_by_chars(part, max_tokens))
        else:
            current.append(part)
    if current:
        chunks.append((delimiter if delimiter else "\n\n").join(current).strip())
    return [chunk for chunk in chunks if chunk]


def extract_markdown_tables(markdown_content: str) -> list[TextSection]:
    """Extract simple pipe-style Markdown tables as sections."""
    lines = (markdown_content or "").splitlines()
    tables: list[TextSection] = []
    current: list[str] = []
    for line in lines:
        if "|" in line and line.strip().startswith("|"):
            current.append(line)
            continue
        if current:
            tables.append(TextSection(title="table", content="\n".join(current), metadata={"element_type": "table"}))
            current = []
    if current:
        tables.append(TextSection(title="table", content="\n".join(current), metadata={"element_type": "table"}))
    return tables


def extract_qa_sections(text: str) -> list[TextSection]:
    """Extract Q&A sections from Markdown/text."""
    sections: list[TextSection] = []
    for match in _QA_RE.finditer(text or ""):
        question = _compact_line(match.group("q"))
        answer = match.group("a").strip()
        if question and answer:
            sections.append(
                TextSection(
                    title=question,
                    content=f"Q: {question}\nA: {answer}",
                    metadata={"question": question, "answer": answer},
                )
            )
    return sections


def extract_tag_sections(text: str) -> list[TextSection]:
    """Extract content/tag pairs from CSV-like text."""
    sections: list[TextSection] = []
    reader = csv.reader(StringIO(text or ""))
    for row in reader:
        if len(row) < 2:
            continue
        content = (row[0] or "").strip()
        tags = [tag.strip() for tag in ",".join(row[1:]).replace("，", ",").split(",") if tag.strip()]
        if content and tags:
            sections.append(TextSection(title=None, content=content, metadata={"tag_kwd": tags}))
    return sections


def _hard_split_by_chars(text: str, max_tokens: int) -> list[str]:
    approx_chars = max(max_tokens * 2, 200)
    return [text[idx : idx + approx_chars].strip() for idx in range(0, len(text), approx_chars) if text[idx : idx + approx_chars].strip()]


def _compact_line(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip())
