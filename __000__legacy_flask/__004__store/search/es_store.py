from __future__ import annotations

from typing import Any

from __000__common.__002__log import get_logger
from __000__common.__004__infra import ES_HOSTS, ES_INDEX_PREFIX, ES_PASSWORD, ES_USERNAME

logger = get_logger(__name__)

_client = None
_failed = False


def _index_name(kb_id: str) -> str:
    return f"{ES_INDEX_PREFIX}{kb_id}".lower()


def get_es(retry: bool = False):
    global _client, _failed
    if retry:
        _failed = False
        _client = None
    if _failed:
        return None
    if _client is not None:
        return _client
    try:
        from elasticsearch import Elasticsearch

        kwargs = {"hosts": [ES_HOSTS], "request_timeout": 3, "verify_certs": False}
        if ES_USERNAME:
            kwargs["basic_auth"] = (ES_USERNAME, ES_PASSWORD)
        client = Elasticsearch(**kwargs)
        if not client.ping():
            raise RuntimeError("ES ping failed")
        _client = client
        logger.info("Elasticsearch ready %s", ES_HOSTS)
        return _client
    except Exception as exc:
        _failed = True
        logger.warning("Elasticsearch unavailable, fallback numpy store: %s", exc)
        return None


def upsert_chunks(kb_id: str, rows: list[dict[str, Any]]) -> bool:
    client = get_es()
    if client is None or not rows:
        return False
    index = _index_name(kb_id)
    try:
        from elasticsearch import helpers

        actions = []
        for row in rows:
            body = {
                "kb_id": kb_id,
                "doc_id": row["doc_id"],
                "doc_name": row.get("doc_name") or "",
                "content": row.get("content") or "",
                "available_int": 1,
            }
            if row.get("embedding"):
                body["q_vec"] = row["embedding"]
            actions.append({"_index": index, "_id": row["id"], "_source": body})
        if not client.indices.exists(index=index):
            mapping = {
                "mappings": {
                    "properties": {
                        "kb_id": {"type": "keyword"},
                        "doc_id": {"type": "keyword"},
                        "doc_name": {"type": "keyword"},
                        "content": {"type": "text"},
                        "available_int": {"type": "integer"},
                        "q_vec": {"type": "dense_vector", "dims": len(rows[0]["embedding"]), "index": True, "similarity": "cosine"},
                    }
                }
            } if rows[0].get("embedding") else {"mappings": {"properties": {"content": {"type": "text"}}}}
            client.indices.create(index=index, **mapping)
        helpers.bulk(client, actions, refresh=True)
        return True
    except Exception as exc:
        logger.warning("ES upsert failed: %s", exc)
        return False


def delete_doc(kb_id: str, doc_id: str) -> None:
    client = get_es()
    if client is None:
        return
    try:
        client.delete_by_query(index=_index_name(kb_id), query={"term": {"doc_id": doc_id}}, refresh=True)
    except Exception:
        pass


def drop_kb(kb_id: str) -> None:
    client = get_es()
    if client is None:
        return
    try:
        client.indices.delete(index=_index_name(kb_id), ignore_unavailable=True)
    except Exception:
        pass


def search_text(kb_id: str, question: str, top_k: int = 6, query_vec: list[float] | None = None) -> list[dict[str, Any]]:
    client = get_es()
    if client is None:
        return []
    index = _index_name(kb_id)
    try:
        knn = None
        if query_vec:
            knn = {"field": "q_vec", "query_vector": query_vec, "k": top_k, "num_candidates": max(top_k * 4, 20)}
        body = {
            "size": top_k,
            "query": {
                "bool": {
                    "must": [{"match": {"content": question}}],
                    "filter": [{"term": {"kb_id": kb_id}}, {"term": {"available_int": 1}}],
                }
            },
        }
        if knn:
            resp = client.search(index=index, knn=knn, query=body["query"], size=top_k)
        else:
            resp = client.search(index=index, **body)
        hits = []
        for item in resp.get("hits", {}).get("hits", []):
            src = item.get("_source") or {}
            hits.append(
                {
                    "kind": "chunk",
                    "id": item.get("_id"),
                    "doc_id": src.get("doc_id"),
                    "doc_name": src.get("doc_name") or "",
                    "page_no": None,
                    "score": round(float(item.get("_score") or 0), 4),
                    "preview": (src.get("content") or "")[:240],
                    "content": src.get("content") or "",
                }
            )
        return hits
    except Exception as exc:
        logger.warning("ES search failed: %s", exc)
        return []


def health(retry: bool = False) -> dict:
    client = get_es(retry=retry)
    return {"ok": client is not None, "hosts": ES_HOSTS}
