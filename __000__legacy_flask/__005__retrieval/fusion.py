from __future__ import annotations

from typing import Any

from __000__common.__003__orm.models import RAG_HYBRID, RAG_TEXT, RAG_VISION, Knowledgebase
from __005__retrieval.text import retrieve_chunks
from __005__retrieval.vision import retrieve_pages
from __006__llm.factory import embed_query


def retrieve_for_kb(
    session,
    kb: Knowledgebase,
    question: str,
    index_root: str,
    doc_ids: list[str] | None = None,
) -> dict[str, list[dict[str, Any]]]:
    mode = kb.rag_mode or RAG_VISION
    chunks: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    if mode in {RAG_VISION, RAG_HYBRID}:
        pages = retrieve_pages(kb, question, index_root)
    if mode in {RAG_TEXT, RAG_HYBRID}:
        query_vec = embed_query(question, model=kb.embd_id)
        chunks = retrieve_chunks(session, kb, question, query_vec, doc_ids)
    if pages and mode == RAG_VISION:
        chunks = []
    return {"chunks": chunks, "pages": pages}
