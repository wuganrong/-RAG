from __future__ import annotations

import os


def parse_document_to_text(path: str) -> str:
    ext = os.path.splitext(path)[1].lower()
    if ext in {".txt", ".md", ".csv"}:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext in {".docx"}:
        return _parse_docx(path)
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return ""
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _parse_pdf(path: str) -> str:
    from pypdf import PdfReader

    reader = PdfReader(path)
    parts = []
    for page in reader.pages:
        text = page.extract_text() or ""
        if text.strip():
            parts.append(text)
    return "\n\n".join(parts)


def _parse_docx(path: str) -> str:
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError("读取 docx 需要 python-docx") from exc
    doc = Document(path)
    return "\n".join(p.text for p in doc.paragraphs if p.text)
