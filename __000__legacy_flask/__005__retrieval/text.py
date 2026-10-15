from __future__ import annotations

from typing import Any

from __000__common.__003__orm.models import Chunk, Knowledgebase
from __004__store.vectorstore.numpy_store import vector_store
from __005__retrieval.rrf import rrf_merge
from __005__retrieval.text_score import keyword_score


def _to_cite(row: Chunk, score: float) -> dict[str, Any]:
    return {
        "kind": "chunk",
        "id": row.id,
        "doc_id": row.doc_id,
        "doc_name": row.doc_name,
        "page_no": None,
        "score": round(score, 4),
        "preview": row.content[:240],
        "content": row.content,
    }


def retrieve_chunks(
    session,
    kb: Knowledgebase,
    question: str,
    query_embedding: list[float] | None = None,
    doc_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    from __004__store.search import es_store

    es_hits = es_store.search_text(kb.id, question, top_k=max(kb.top_n or 6, 1), query_vec=query_embedding)
    if es_hits:
        return es_hits[: max(kb.top_n or 6, 1)]

    q = session.query(Chunk).filter(Chunk.kb_id == kb.id, Chunk.available == 1)
    if doc_ids:
        q = q.filter(Chunk.doc_id.in_(doc_ids))
    rows = q.all()
    keyword_ranked = []
    for row in rows:
        score = keyword_score(question, row.content)
        if score > 0:
            keyword_ranked.append(_to_cite(row, score))
    keyword_ranked.sort(key=lambda item: item["score"], reverse=True)

    vector_ranked = []
    if query_embedding:
        for score, item in vector_store.search(
            kb.id,
            query_embedding,
            top_k=max((kb.top_n or 6) * 3, 6),
            doc_ids=doc_ids,
        ):
            vector_ranked.append(
                {
                    "kind": "chunk",
                    "id": item["id"],
                    "doc_id": item["doc_id"],
                    "doc_name": item.get("doc_name") or "",
                    "page_no": None,
                    "score": round(score, 4),
                    "preview": (item.get("content") or "")[:240],
                    "content": item.get("content") or "",
                }
            )

    if vector_ranked and keyword_ranked:
        merged = rrf_merge([vector_ranked, keyword_ranked], id_key="id")
    else:
        merged = vector_ranked or keyword_ranked

    threshold = kb.similarity_threshold or 0
    filtered = [
        item
        for item in merged
        if float(item.get("score") or 0) >= threshold or item.get("rrf")
    ]
    return filtered[: max(kb.top_n or 6, 1)]
