from __future__ import annotations


def chunk_text(text: str, chunk_size: int = 600, overlap: int = 80) -> list[str]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    chunks: list[str] = []
    start = 0
    length = len(cleaned)
    while start < length:
        end = min(start + chunk_size, length)
        piece = cleaned[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        start = max(end - overlap, start + 1)
    return chunks
