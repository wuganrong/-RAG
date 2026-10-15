from __future__ import annotations

from __002__chunk.naive import chunk_text


def chunk_document(text: str, chunker_id: str = "naive", **opts) -> list[str]:
    if chunker_id in {"naive", "", None}:
        return chunk_text(
            text,
            chunk_size=int(opts.get("chunk_size", 600)),
            overlap=int(opts.get("overlap", 80)),
        )
    raise ValueError(f"不支持的切块器: {chunker_id}")
