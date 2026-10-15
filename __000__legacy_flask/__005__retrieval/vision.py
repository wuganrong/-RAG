from __future__ import annotations

from typing import Any

from __000__common.__003__orm.models import Knowledgebase
from __003__colpali.index.vision_index import get_vision_model
from __003__colpali.retrieve.retriever import retrieve_documents


def retrieve_pages(kb: Knowledgebase, question: str, index_root: str) -> list[dict[str, Any]]:
    rag = get_vision_model(kb.id, index_root)
    if rag is None:
        return []
    k = max(kb.page_top_n or 3, 1)
    images = retrieve_documents(rag, question, kb.id, k=k)
    citations = []
    for rank, item in enumerate(images, start=1):
        rel = item["image"] if isinstance(item, dict) else item
        page_no = item.get("page_no") if isinstance(item, dict) else rank
        doc_name = item.get("doc_name") if isinstance(item, dict) else ""
        citations.append(
            {
                "kind": "page",
                "id": f"{kb.id}-{rank}",
                "doc_id": kb.id,
                "doc_name": doc_name or "",
                "page_no": page_no or rank,
                "score": None,
                "preview": rel,
                "content": "",
                "image": rel,
            }
        )
    return citations
