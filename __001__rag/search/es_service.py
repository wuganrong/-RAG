"""Elasticsearch 统一服务 — 合并客户端管理、查询构建与业务逻辑。"""

from __future__ import annotations

# 1. Python 标准库
import copy
import re
import time
from typing import Any

# 2. 第三方库
from django.conf import settings
from elasticsearch import Elasticsearch, NotFoundError
from loguru import logger

# 3. 本地应用
from __001__rag.nlp.utils.indexing_tokenizer import token_string
from __001__rag.search.base import (
    FusionExpr,
    MatchDenseExpr,
    MatchSparseExpr,
    MatchTextExpr,
    OrderByExpr,
    SearchRequest,
    SearchResult,
)
from __001__rag.search.constants import CHUNK_SELECT_FIELDS, TEXT_SEARCH_FIELDS
from __001__rag.search.mapping import get_default_es_mapping

# Painless 脚本安全 key 正则
_SAFE_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class ESService:
    """对业务层暴露统一的 Elasticsearch 操作入口。

    直接管理 ES 客户端、构建查询、执行 CRUD 和检索，无中间适配层。
    """

    def __init__(self) -> None:
        self.client = self._open_client()
        self.mapping = get_default_es_mapping()
        self._es_major: int | None = None

    # ------------------------------------------------------------------
    # 客户端管理
    # ------------------------------------------------------------------

    @staticmethod
    def _normalize_hosts(hosts: str | list[str] | tuple[str, ...] | None) -> list[str]:
        if not hosts:
            return []
        if isinstance(hosts, str):
            return [h.strip() for h in hosts.split(",") if h.strip()]
        return [str(h).strip() for h in hosts if str(h).strip()]

    def _open_client(self) -> Elasticsearch:
        hosts = self._normalize_hosts(getattr(settings, "ES_HOSTS", None))
        username = getattr(settings, "ES_USERNAME", None)
        password = getattr(settings, "ES_PASSWORD", None)
        basic_auth = (username, password) if username and password else None
        return Elasticsearch(
            hosts,
            basic_auth=basic_auth,
            verify_certs=getattr(settings, "ES_VERIFY_CERTS", False),
            request_timeout=getattr(settings, "ES_REQUEST_TIMEOUT", 600),
        )

    def _es_major_version(self) -> int:
        """读取 ES 主版本。7.x 不支持 _search 顶层 knn，需走 script_score。"""
        if self._es_major is not None:
            return self._es_major
        try:
            number = str((self.client.info() or {}).get("version", {}).get("number") or "8")
            self._es_major = int(number.split(".", 1)[0])
        except Exception:
            logger.exception("[ES] 读取版本失败，按 8.x knn 处理")
            self._es_major = 8
        logger.info("[ES] elasticsearch major={}", self._es_major)
        return self._es_major

    # ------------------------------------------------------------------
    # 索引管理
    # ------------------------------------------------------------------

    @staticmethod
    def index_name(kb_id: str) -> str:
        """按知识库 ID 生成索引名（ragflow_{kb_id}）。"""
        return f"ragflow_{kb_id}"

    def chunk_index_name(self, kb_id: str) -> str:
        """获取切片查询/检索时使用的索引名。

        当 CHUNK_LEGACY_COMPAT=True 时返回固定的旧版索引，
        否则按 kb_id 动态生成索引名。
        """
        if getattr(settings, "CHUNK_LEGACY_COMPAT", False):
            legacy_index = getattr(settings, "CHUNK_LEGACY_INDEX", self.index_name(kb_id))
            logger.info("[ES.chunk_index_name] 旧版兼容模式 index={} kb_id={}", legacy_index, kb_id)
            return legacy_index
        return self.index_name(kb_id)

    def ensure_index(self, kb_id: str, vector_size: int = 0) -> str:
        """确保知识库索引存在并返回索引名。"""
        index_name = self.chunk_index_name(kb_id)
        if not self.index_exists(index_name, kb_id):
            t0 = time.perf_counter()
            self.create_index(index_name, kb_id, vector_size)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "[ES.ensure_index] 索引创建完成 kb_id={} index={} vector_size={} elapsed_ms={:.1f}",
                kb_id, index_name, vector_size, elapsed,
            )
        else:
            logger.info("[ES.ensure_index] 索引已存在 kb_id={} index={}", kb_id, index_name)
        return index_name

    def create_index(self, index_name: str, kb_id: str, vector_size: int) -> None:
        """创建索引。"""
        if self.index_exists(index_name, kb_id):
            return
        self.client.indices.create(
            index=index_name,
            settings=self.mapping["settings"],
            mappings=self.mapping["mappings"],
        )

    def delete_index(self, index_name: str, kb_id: str) -> None:
        """删除索引。"""
        try:
            self.client.indices.delete(index=index_name, ignore_unavailable=True)
        except NotFoundError:
            pass

    def index_exists(self, index_name: str, kb_id: str) -> bool:
        """判断索引是否存在。"""
        attempt_count = getattr(settings, "ES_ATTEMPT_COUNT", 2)
        sleep_sec = getattr(settings, "ES_RETRY_SLEEP_SECONDS", 1)
        for _ in range(attempt_count):
            try:
                return bool(self.client.indices.exists(index=index_name))
            except Exception as exc:
                exc_str = str(exc).lower()
                if "timeout" in exc_str or "connection" in exc_str:
                    logger.info("[ES.index_exists] 连接/超时异常，准备重试 index={} err={}", index_name, exc)
                    time.sleep(sleep_sec)
                    continue
                raise
        return False

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------

    def create_chunk(self, kb_id: str, row: dict[str, Any]) -> list[str]:
        """写入单条切片。"""
        vector_size = self._infer_vector_size(row)
        index_name = self.ensure_index(kb_id, vector_size)
        t0 = time.perf_counter()
        errors = self._insert([row], index_name, kb_id)
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "[ES.create_chunk] 写入完成 kb_id={} index={} chunk_id={} vector_size={} errors={} elapsed_ms={:.1f}",
            kb_id, index_name, row.get("id"), vector_size, len(errors), elapsed,
        )
        return errors

    def create_chunks_to_index(
        self, index_name: str, kb_id: str, rows: list[dict[str, Any]]
    ) -> list[str]:
        """批量写入切片到指定的索引名。"""
        if not rows:
            logger.info("[ES.create_chunks_to_index] rows 为空 index={} kb_id={}", index_name, kb_id)
            return []
        vector_size = max((self._infer_vector_size(r) for r in rows), default=0)
        if not self.index_exists(index_name, kb_id):
            self.create_index(index_name, kb_id, vector_size)
        t0 = time.perf_counter()
        errors = self._insert(rows, index_name, kb_id)
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "[ES.create_chunks_to_index] 批量写入完成 index={} kb_id={} row_count={} errors={} elapsed_ms={:.1f}",
            index_name, kb_id, len(rows), len(errors), elapsed,
        )
        return errors

    def _insert(self, rows: list[dict[str, Any]], index_name: str, kb_id: str) -> list[str]:
        """底层 bulk 写入。"""
        operations: list[dict[str, Any]] = []
        for row in rows:
            if "id" not in row:
                raise ValueError("ES row must contain id")
            doc = copy.deepcopy(row)
            chunk_id = str(doc.pop("id"))
            doc["kb_id"] = [kb_id]
            operations.append({"index": {"_index": index_name, "_id": chunk_id}})
            operations.append(doc)

        if not operations:
            return []
        bulk_timeout = getattr(settings, "ES_BULK_REQUEST_TIMEOUT", 60)
        try:
            response = self.client.bulk(
                index=index_name, operations=operations, refresh=False, request_timeout=bulk_timeout,
            )
        except Exception:
            logger.exception("[ES._insert] 批量写入异常 index={} row_count={}", index_name, len(rows))
            raise

        errors: list[str] = []
        for item in response.get("items", []):
            for action in ("create", "delete", "index", "update"):
                if action in item and "error" in item[action]:
                    errors.append(f"{item[action].get('_id')}:{item[action]['error']}")
        return errors

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------

    def get_chunk(self, kb_id: str, chunk_id: str) -> dict[str, Any] | None:
        """按 chunk_id 获取切片。"""
        index_name = self.chunk_index_name(kb_id)
        try:
            response = self.client.get(index=index_name, id=chunk_id, source=True)
        except NotFoundError:
            return None
        except Exception:
            logger.exception("[ES.get_chunk] 获取失败 kb_id={} chunk_id={}", kb_id, chunk_id)
            return None

        source = dict(response.get("_source", {}) or {})
        if kb_id and not self._source_matches_kb(source, [kb_id]):
            return None
        source["id"] = response.get("_id", chunk_id)
        return source

    def find_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        """未指定知识库时，按 chunk_id 在所有 RAG 索引中查找切片。"""
        try:
            response = self.client.search(
                index="ragflow_*",
                body={"query": {"ids": {"values": [chunk_id]}}, "size": 1},
                ignore_unavailable=True,
                track_total_hits=False,
            )
        except NotFoundError:
            return None
        except Exception:
            logger.exception("[ES.find_chunk] 查找失败 chunk_id={}", chunk_id)
            return None

        hits = response.get("hits", {}).get("hits", [])
        if not hits:
            return None
        hit = hits[0]
        source = dict(hit.get("_source", {}) or {})
        source["id"] = hit.get("_id", chunk_id)
        return source

    # ------------------------------------------------------------------
    # 更新
    # ------------------------------------------------------------------

    def update_chunk(self, kb_id: str, chunk_id: str, values: dict[str, Any]) -> bool:
        """更新单条切片。"""
        index_name = self.chunk_index_name(kb_id)
        if not self.index_exists(index_name, kb_id):
            return False
        doc = copy.deepcopy(values)
        doc.pop("id", None)
        try:
            self.client.update(index=index_name, id=chunk_id, body={"doc": doc})
            return True
        except NotFoundError:
            return False
        except Exception:
            logger.exception("[ES.update_chunk] 更新失败 kb_id={} chunk_id={}", kb_id, chunk_id)
            return False

    def update_chunks(self, kb_id: str, chunk_ids: list[str], values: dict[str, Any]) -> bool:
        """批量更新切片；逐条按 ID 更新，避免条件为空时误更新整个索引。"""
        if not chunk_ids:
            return True
        ok = True
        for chunk_id in chunk_ids:
            ok = self.update_chunk(kb_id, chunk_id, values) and ok
        return ok

    def update_chunks_doc(self, kb_id: str, chunk_ids: list[str], doc_id: str, doc_name: str) -> bool:
        """批量更新切片关联文档信息。"""
        return self.update_chunks(kb_id, chunk_ids, {"doc_id": doc_id, "docnm_kwd": doc_name})

    def update_doc_available(self, kb_id: str, doc_id: str, available: int) -> bool:
        """同步文档下所有切片的可用状态。"""
        index_name = self.chunk_index_name(kb_id)
        if not self.index_exists(index_name, kb_id):
            return False
        count = self._update_by_query(
            {"doc_id": doc_id}, {"available_int": available}, index_name, kb_id,
        )
        return count > 0

    def _update_by_query(
        self, filters: dict[str, Any], values: dict[str, Any], index_name: str, kb_id: str,
    ) -> int:
        """按条件批量更新，返回更新数量。"""
        doc = copy.deepcopy(values)
        doc.pop("id", None)
        query = self._build_filter_query(filters, kb_id)
        script = self._build_update_script(doc)
        try:
            response = self.client.update_by_query(
                index=index_name,
                body={"query": query, "script": script},
                refresh=True,
                conflicts="proceed",
            )
            return int(response.get("updated", 0))
        except Exception:
            logger.exception("[ES._update_by_query] 批量更新异常 index={} kb_id={}", index_name, kb_id)
            return 0

    # ------------------------------------------------------------------
    # 删除
    # ------------------------------------------------------------------

    def delete_chunk(self, kb_id: str, chunk_id: str) -> int:
        """删除单条切片。"""
        return self._delete_by_query({"id": chunk_id}, self.chunk_index_name(kb_id), kb_id)

    def delete_chunks(self, kb_id: str, chunk_ids: list[str]) -> int:
        """批量删除切片。"""
        if not chunk_ids:
            return 0
        return self._delete_by_query({"id": chunk_ids}, self.chunk_index_name(kb_id), kb_id)

    def delete_doc_chunks(self, kb_id: str, doc_id: str) -> int:
        """删除文档下所有切片。"""
        return self._delete_by_query({"doc_id": doc_id}, self.chunk_index_name(kb_id), kb_id)

    def delete_kb_chunks(self, kb_id: str) -> int:
        """删除知识库索引数据，返回删除前的文档数。

        CHUNK_LEGACY_COMPAT=True 时所有知识库共享同一索引，
        只能按 kb_id 条件删除，不能直接删除整个索引。
        """
        index_name = self.chunk_index_name(kb_id)
        if not self.index_exists(index_name, kb_id):
            return 0
        t0 = time.perf_counter()
        is_legacy = getattr(settings, "CHUNK_LEGACY_COMPAT", False)
        if is_legacy:
            # 共享索引：按 kb_id 条件删除，保留索引本身
            deleted = self._delete_by_query({}, index_name, kb_id)
            elapsed = (time.perf_counter() - t0) * 1000
            logger.info(
                "[ES.delete_kb_chunks] 旧版兼容模式，按 kb_id 删除完成 kb_id={} index={} deleted={} elapsed_ms={:.1f}",
                kb_id, index_name, deleted, elapsed,
            )
            return deleted
        try:
            count_resp = self.client.count(index=index_name, ignore_unavailable=True)
            doc_count = int(count_resp.get("count", 0))
        except Exception:
            doc_count = 0
        self.delete_index(index_name, kb_id)
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "[ES.delete_kb_chunks] 删除完成 kb_id={} index={} doc_count={} elapsed_ms={:.1f}",
            kb_id, index_name, doc_count, elapsed,
        )
        return doc_count

    def _delete_by_query(self, filters: dict[str, Any], index_name: str, kb_id: str) -> int:
        """按条件批量删除，返回删除数量。"""
        condition = copy.deepcopy(filters)
        if "id" in condition:
            ids = condition["id"]
            ids = ids if isinstance(ids, list) else [ids]
            if not ids:
                return 0
            query: dict[str, Any] = {
                "bool": {
                    "filter": [
                        {"ids": {"values": ids}},
                        {"term": {"kb_id": kb_id}},
                    ],
                },
            }
        else:
            query = self._build_filter_query(condition, kb_id)
        try:
            response = self.client.delete_by_query(
                index=index_name, body={"query": query}, refresh=True,
            )
            return int(response.get("deleted", 0))
        except NotFoundError:
            return 0
        except Exception:
            logger.exception("[ES._delete_by_query] 删除异常 index={} kb_id={}", index_name, kb_id)
            return 0

    # ------------------------------------------------------------------
    # 检索
    # ------------------------------------------------------------------

    def search(
        self,
        *,
        kb_ids: list[str],
        match_exprs: list[Any],
        select_fields: list[str],
        filters: dict[str, Any] | None = None,
        offset: int = 0,
        limit: int = 10,
        agg_fields: list[str] | None = None,
        highlight_fields: list[str] | None = None,
        order_by: OrderByExpr | None = None,
    ) -> SearchResult:
        """统一检索入口：自动注入 CUSTOM_KB_ID、解析索引名并执行检索。"""
        custom_kb_id: str | None = getattr(settings, "CUSTOM_KB_ID", None)
        if custom_kb_id and custom_kb_id not in kb_ids:
            kb_ids = [*kb_ids, custom_kb_id]

        request = SearchRequest(
            index_names=[self.chunk_index_name(kb_id) for kb_id in kb_ids],
            kb_ids=kb_ids,
            match_exprs=match_exprs,
            select_fields=select_fields,
            filters=filters or {},
            order_by=order_by or OrderByExpr(),
            offset=offset,
            limit=limit,
            agg_fields=agg_fields or [],
            highlight_fields=highlight_fields or [],
        )
        return self._execute_search(request)

    def retrieve_chunks(
        self,
        *,
        kb_ids: list[str],
        question: str,
        embedding: list[float] | None,
        page: int,
        size: int,
        top_k: int,
        similarity_threshold: float,
        vector_similarity_weight: float,
        doc_ids: list[str] | None = None,
        highlight: bool = False,
    ) -> SearchResult:
        """执行混合检索：MatchTextExpr + 可选 MatchDenseExpr + FusionExpr。"""
        if not kb_ids:
            return SearchResult(total=0, chunks=[], aggregations={})

        logger.info(
            "[ES.retrieve_chunks] kb_ids={} question_len={} embedding_dim={} top_k={} "
            "similarity={} vector_weight={} doc_ids_count={}",
            kb_ids, len(question), len(embedding) if embedding else 0, top_k,
            similarity_threshold, vector_similarity_weight, len(doc_ids) if doc_ids else 0,
        )

        filters: dict[str, Any] = {"available_int": 1}
        if doc_ids:
            filters["doc_id"] = doc_ids

        match_exprs: list[Any] = [
            MatchTextExpr(
                fields=TEXT_SEARCH_FIELDS,
                matching_text=token_string(question),
                topn=top_k,
                extra_options={"minimum_should_match": float(getattr(settings, "RETRIEVAL_MINIMUM_SHOULD_MATCH", 0.3))},
            )
        ]
        if embedding:
            match_exprs.append(
                MatchDenseExpr(
                    vector_field=f"q_{len(embedding)}_vec",
                    embedding=embedding,
                    topn=top_k,
                    extra_options={"similarity": similarity_threshold},
                )
            )
            match_exprs.append(
                FusionExpr(
                    method="weighted_sum",
                    topn=top_k,
                    params={"weights": [1.0 - vector_similarity_weight, vector_similarity_weight]},
                )
            )

        return self.search(
            kb_ids=kb_ids,
            match_exprs=match_exprs,
            select_fields=CHUNK_SELECT_FIELDS,
            filters=filters,
            offset=max(page - 1, 0) * size,
            limit=size,
            highlight_fields=["content_with_weight"] if highlight else [],
            agg_fields=["docnm_kwd"],
        )

    def list_chunks(
        self,
        *,
        kb_id: str,
        page: int,
        size: int,
        chunk_title_kwd: str = "",
        user_name: str = "",
        available_int: int | None = None,
    ) -> dict[str, Any]:
        """分页查询自定义切片列表。"""
        filters: dict[str, Any] = {}
        wildcard: dict[str, str] = {}
        if chunk_title_kwd:
            wildcard["chunk_title_kwd"] = f"*{chunk_title_kwd}*"
        if user_name:
            wildcard["create_user_name"] = f"*{user_name}*"
        if wildcard:
            filters["wildcard"] = wildcard
        if available_int is not None:
            filters["available_int"] = available_int

        request = SearchRequest(
            index_names=self.chunk_index_name(kb_id),
            kb_ids=[kb_id],
            match_exprs=[],
            select_fields=[
                "id", "doc_id", "docnm_kwd", "content_with_weight",
                "important_kwd", "question_kwd", "img_id", "available_int",
                "create_user_name", "create_time", "chunk_title_kwd",
            ],
            filters=filters,
            order_by=OrderByExpr().desc("create_timestamp_flt"),
            offset=max(page - 1, 0) * size,
            limit=size,
        )
        t0 = time.perf_counter()
        result = self._execute_search(request)
        elapsed = (time.perf_counter() - t0) * 1000
        chunks = [self._format_chunk(c) for c in result.chunks]
        logger.info(
            "[ES.list_chunks] 查询完成 kb_id={} page={} size={} total={} returned={} elapsed_ms={:.1f}",
            kb_id, page, size, result.total, len(chunks), elapsed,
        )
        return {"total": result.total, "chunks": chunks, "doc": {}}

    def list_document_chunks(
        self,
        *,
        kb_id: str,
        doc_id: str,
        page: int,
        size: int,
        keywords: str = "",
        available_int: int | None = None,
    ) -> SearchResult:
        """按文档分页查询普通切片。"""
        filters: dict[str, Any] = {"doc_id": doc_id}
        if available_int is not None:
            filters["available_int"] = available_int

        match_exprs: list[Any] = []
        if keywords:
            match_exprs.append(
                MatchTextExpr(
                    fields=TEXT_SEARCH_FIELDS,
                    matching_text=token_string(keywords),
                    topn=size,
                    extra_options={"minimum_should_match": float(getattr(settings, "RETRIEVAL_MINIMUM_SHOULD_MATCH", 0.3))},
                )
            )

        request = SearchRequest(
            index_names=self.chunk_index_name(kb_id),
            kb_ids=[kb_id],
            match_exprs=match_exprs,
            select_fields=CHUNK_SELECT_FIELDS,
            highlight_fields=["content_with_weight"] if keywords else [],
            filters=filters,
            order_by=OrderByExpr().asc("parent_group_id").asc("chunk_order"),
            offset=max(page - 1, 0) * size,
            limit=size,
        )
        t0 = time.perf_counter()
        result = self._execute_search(request)
        elapsed = (time.perf_counter() - t0) * 1000
        logger.info(
            "[ES.list_document_chunks] 查询完成 kb_id={} doc_id={} page={} size={} "
            "total={} returned={} elapsed_ms={:.1f}",
            kb_id, doc_id, page, size, result.total, len(result.chunks), elapsed,
        )
        return result

    def get_tags(self, kb_ids: list[str]) -> list[str]:
        """聚合查询知识库标签。"""
        if not kb_ids:
            return []
        index_names: list[str] = [self.chunk_index_name(kb_id) for kb_id in kb_ids]
        body: dict[str, Any] = {
            "size": 0,
            "query": {"terms": {"kb_id": kb_ids}},
            "aggs": {"tags": {"terms": {"field": "tag_kwd", "size": int(getattr(settings, "ES_AGGREGATION_MAX_SIZE", 1000))}}},
        }
        try:
            response = self.client.search(index=index_names, body=body, ignore_unavailable=True)
        except NotFoundError:
            return []
        except Exception:
            logger.exception("[ES.get_tags] 聚合查询失败 kb_ids={}", kb_ids)
            return []

        buckets: list[dict[str, Any]] = response.get("aggregations", {}).get("tags", {}).get("buckets", [])
        return [bucket["key"] for bucket in buckets]

    # ------------------------------------------------------------------
    # 底层检索执行
    # ------------------------------------------------------------------

    def _execute_search(self, request: SearchRequest) -> SearchResult:
        """执行 ES 检索，含重试逻辑。"""
        index_names = request.index_names
        body = self._build_search_body(request)
        attempt_count = getattr(settings, "ES_ATTEMPT_COUNT", 2)
        sleep_sec = getattr(settings, "ES_RETRY_SLEEP_SECONDS", 1)
        request_timeout = getattr(settings, "ES_REQUEST_TIMEOUT", 600)

        t0 = time.perf_counter()
        for _ in range(attempt_count):
            try:
                response = self.client.search(
                    index=index_names,
                    body=body,
                    track_total_hits=True,
                    request_timeout=request_timeout,
                    ignore_unavailable=True,
                    allow_no_indices=True,
                )
                elapsed = (time.perf_counter() - t0) * 1000
                result = self._to_search_result(response)
                self._log_search(request, elapsed)
                return result
            except NotFoundError:
                logger.info("[ES.search] 索引不存在 index={}", index_names)
                return SearchResult(total=0, chunks=[], raw=None)
            except Exception as exc:
                if "timeout" in str(exc).lower():
                    logger.info("[ES.search] 检索超时，准备重试 index={} err={}", index_names, exc)
                    time.sleep(sleep_sec)
                    continue
                logger.exception("[ES.search] 检索异常 index={}", index_names)
                raise
        raise TimeoutError(f"Elasticsearch search timeout after {attempt_count} attempts.")

    def _log_search(self, request: SearchRequest, elapsed: float) -> None:
        """记录一条精简的检索完成日志。"""
        text_exprs = [e for e in request.match_exprs if isinstance(e, MatchTextExpr)]
        dense_exprs = [e for e in request.match_exprs if isinstance(e, MatchDenseExpr)]
        text_len = len(text_exprs[0].matching_text) if text_exprs else 0
        emb_dim = len(dense_exprs[0].embedding) if dense_exprs else 0
        similarity = dense_exprs[0].extra_options.get("similarity", "N/A") if dense_exprs else "N/A"
        vt_weight = self._vector_similarity_weight(request.match_exprs) if dense_exprs else 1.0

        logger.info(
            "[ES.search] kb_ids={} index={} text_len={} embedding_dim={} "
            "top_k={} similarity={} vector_weight={} elapsed_ms={:.1f}",
            request.kb_ids, request.index_names, text_len, emb_dim,
            request.limit, similarity, f"{vt_weight:.2f}", elapsed,
        )

    # ------------------------------------------------------------------
    # 查询构建
    # ------------------------------------------------------------------

    def _build_search_body(self, request: SearchRequest) -> dict[str, Any]:
        """构建 ES search body。"""
        full_query = self._build_bool_query(request)
        body: dict[str, Any] = {
            "query": full_query,
            "from": request.offset,
            "size": request.limit,
        }
        if request.select_fields:
            body["_source"] = request.select_fields
        if request.order_by.fields:
            body["sort"] = [
                {field: self._build_order_info(field, order)}
                for field, order in request.order_by.fields
            ]
        if request.highlight_fields:
            body["highlight"] = {"fields": {field: {} for field in request.highlight_fields}}
        if request.agg_fields:
            agg_size = getattr(settings, "ES_AGGREGATION_MAX_SIZE", 1000)
            body["aggs"] = {
                f"aggs_{field}": {"terms": {"field": field, "size": agg_size}}
                for field in request.agg_fields
            }

        # KNN 向量检索 — ES 8+ 用顶层 knn；ES 7 用 script_score 兼容
        dense_exprs = [e for e in request.match_exprs if isinstance(e, MatchDenseExpr)]
        if dense_exprs:
            expr = dense_exprs[0]
            if self._es_major_version() >= 8:
                knn_filter = self._build_knn_filter(request)
                body["knn"] = {
                    "field": expr.vector_field,
                    "query_vector": list(expr.embedding),
                    "k": expr.topn,
                    "num_candidates": expr.extra_options.get("num_candidates", expr.topn * 2),
                    "filter": knn_filter,
                }
                similarity = expr.extra_options.get("similarity")
                if similarity is not None:
                    body["knn"]["similarity"] = similarity
            else:
                body["query"] = self._build_es7_hybrid_query(full_query, expr, request)

        return body

    def _build_es7_hybrid_query(
        self,
        full_query: dict[str, Any],
        expr: MatchDenseExpr,
        request: SearchRequest,
    ) -> dict[str, Any]:
        """ES 7.x 无 _search.knn，用 cosineSimilarity script_score 做向量分。"""
        field = expr.vector_field
        if not _SAFE_KEY_RE.match(field):
            raise ValueError(f"unsafe vector field: {field}")
        knn_filter = self._build_knn_filter(request)
        vector_query = {
            "script_score": {
                "query": knn_filter,
                "script": {
                    "source": (
                        f"if (doc['{field}'].size() == 0) {{ return 0.0; }} "
                        f"return (cosineSimilarity(params.query_vector, '{field}') + 1.0) / 2.0;"
                    ),
                    "params": {"query_vector": [float(x) for x in expr.embedding]},
                },
            }
        }
        return {
            "bool": {
                "should": [full_query, vector_query],
                "minimum_should_match": 1,
            }
        }

    def _build_bool_query(self, request: SearchRequest) -> dict[str, Any]:
        """构建完整的 bool query（filter + must + should）。"""
        filters: list[dict[str, Any]] = []
        must: list[dict[str, Any]] = []
        should: list[dict[str, Any]] = []

        if request.kb_ids:
            filters.append({"terms": {"kb_id": request.kb_ids}})

        self._append_filter_clauses(filters, request.filters)

        vector_similarity_weight = self._vector_similarity_weight(request.match_exprs)
        for expr in request.match_exprs:
            if isinstance(expr, MatchTextExpr) and expr.matching_text:
                query_string: dict[str, Any] = {
                    "fields": expr.fields,
                    "type": "best_fields",
                    "query": expr.matching_text,
                    "boost": 1.0 - vector_similarity_weight,
                }
                minimum_should_match = expr.extra_options.get("minimum_should_match")
                if minimum_should_match is not None:
                    if isinstance(minimum_should_match, float):
                        minimum_should_match = f"{int(minimum_should_match * 100)}%"
                    query_string["minimum_should_match"] = minimum_should_match
                must.append({"query_string": query_string})
            elif isinstance(expr, MatchSparseExpr):
                raise NotImplementedError(
                    "MatchSparseExpr 暂不支持 Elasticsearch 后端"
                )

        if request.rank_feature:
            for field, boost in request.rank_feature.items():
                should.append({"rank_feature": {"field": field, "linear": {}, "boost": boost}})

        bool_query: dict[str, Any] = {}
        if filters:
            bool_query["filter"] = filters
        if must:
            bool_query["must"] = must
        if should:
            bool_query["should"] = should
        return {"bool": bool_query} if bool_query else {"match_all": {}}

    def _build_knn_filter(self, request: SearchRequest) -> dict[str, Any]:
        """构建 KNN 专用过滤条件（仅元数据，不含文本 query_string）。

        ES 8.x 中 knn 和 query 并行执行后合并结果，
        knn.filter 不应包含文本 must 条件，否则会限制向量搜索空间。
        """
        filters: list[dict[str, Any]] = []
        if request.kb_ids:
            filters.append({"terms": {"kb_id": request.kb_ids}})
        self._append_filter_clauses(filters, request.filters)
        return {"bool": {"filter": filters}} if filters else {"match_all": {}}

    @staticmethod
    def _append_filter_clauses(
        filters: list[dict[str, Any]], filter_dict: dict[str, Any],
    ) -> None:
        """将 filter_dict 转换为 ES filter clauses 并追加到 filters 列表。"""
        for key, value in filter_dict.items():
            if key == "available_int":
                if value == 0:
                    filters.append({"range": {"available_int": {"lt": 1}}})
                else:
                    filters.append({"bool": {"must_not": [{"range": {"available_int": {"lt": 1}}}]}})
                continue
            if key == "exists" and value:
                filters.append({"exists": {"field": value}})
                continue
            if value is None or value == "" or value == []:
                continue
            if key == "wildcard" and isinstance(value, dict):
                # wildcard 放在 must 语义更准确，但此处作为 filter 也可以
                for field, pattern in value.items():
                    filters.append({"wildcard": {field: pattern}})
                continue
            if isinstance(value, list):
                filters.append({"terms": {key: value}})
            else:
                filters.append({"term": {key: value}})

    def _build_filter_query(self, filters: dict[str, Any], kb_id: str) -> dict[str, Any]:
        """构建用于 update_by_query / delete_by_query 的过滤查询。"""
        clauses: list[dict[str, Any]] = [{"term": {"kb_id": kb_id}}]
        for key, value in filters.items():
            if key in {"id", "_id"} or value is None or value == "" or value == []:
                continue
            if key == "exists":
                clauses.append({"exists": {"field": value}})
            elif isinstance(value, list):
                clauses.append({"terms": {key: value}})
            else:
                clauses.append({"term": {key: value}})
        return {"bool": {"filter": clauses}}

    @staticmethod
    def _build_update_script(values: dict[str, Any]) -> dict[str, Any]:
        """构建 Painless 更新脚本，含 key 安全校验。"""
        source_parts: list[str] = []
        params: dict[str, Any] = {}
        for key, value in values.items():
            if key == "remove":
                fields = [value] if isinstance(value, str) else list(value or [])
                for field in fields:
                    if not _SAFE_KEY_RE.match(str(field)):
                        logger.info("[ES._build_update_script] 跳过不安全的 remove field={}", field)
                        continue
                    source_parts.append(f"ctx._source.remove('{field}');")
                continue
            if not isinstance(key, str) or not _SAFE_KEY_RE.match(key):
                logger.info("[ES._build_update_script] 跳过不安全的 key={}", key)
                continue
            param_key = f"p_{re.sub(r'[^a-zA-Z0-9_]', '_', key)}"
            source_parts.append(f"ctx._source['{key}'] = params.{param_key};")
            params[param_key] = value
        return {"source": "".join(source_parts), "lang": "painless", "params": params}

    @staticmethod
    def _build_order_info(field: str, order: str) -> dict[str, Any]:
        """构建排序字段配置。"""
        if field in {"page_num_int", "top_int"}:
            return {"order": order, "unmapped_type": "float", "mode": "avg", "numeric_type": "double"}
        if field == "chunk_order":
            return {"order": order, "unmapped_type": "long"}
        if field.endswith(("_int", "_flt")):
            return {"order": order, "unmapped_type": "float"}
        return {"order": order, "unmapped_type": "keyword"}

    @staticmethod
    def _vector_similarity_weight(match_exprs: list[Any]) -> float:
        """从 FusionExpr 中提取向量权重。"""
        for expr in match_exprs:
            if isinstance(expr, FusionExpr) and expr.method == "weighted_sum":
                weights = expr.params.get("weights")
                if isinstance(weights, str) and "," in weights:
                    try:
                        return float(weights.split(",")[1])
                    except (TypeError, ValueError):
                        return 0.5
                if isinstance(weights, (list, tuple)) and len(weights) > 1:
                    try:
                        return float(weights[1])
                    except (TypeError, ValueError):
                        return 0.5
        return 0.5

    # ------------------------------------------------------------------
    # 结果处理
    # ------------------------------------------------------------------

    @staticmethod
    def _to_search_result(response: Any) -> SearchResult:
        """将 ES 原始响应转换为 SearchResult。"""
        raw = dict(response)
        hits = raw.get("hits", {})
        total_info = hits.get("total", 0)
        total = total_info.get("value", 0) if isinstance(total_info, dict) else int(total_info or 0)
        chunks: list[dict[str, Any]] = []
        highlights: dict[str, Any] = {}

        for hit in hits.get("hits", []):
            source = hit.get("_source", {}) or {}
            chunk = dict(source)
            chunk["id"] = hit.get("_id")
            score = hit.get("_score")
            chunk["_score"] = score
            # 将 ES 综合评分映射到 similarity，避免下游读取时为空
            if "similarity" not in chunk and score is not None:
                chunk["similarity"] = score
            chunks.append(chunk)
            if hit.get("highlight"):
                highlights[str(hit.get("_id"))] = hit["highlight"]

        aggregations: dict[str, Any] = {}
        for key, value in raw.get("aggregations", {}).items():
            if isinstance(value, dict) and "buckets" in value:
                field = key.removeprefix("aggs_")
                aggregations[field] = [(b["key"], b["doc_count"]) for b in value["buckets"]]
            else:
                aggregations[key] = value

        return SearchResult(total=total, chunks=chunks, aggregations=aggregations, highlights=highlights, raw=raw)

    @staticmethod
    def _format_chunk(source: dict[str, Any]) -> dict[str, Any]:
        """将 ES 原始字段转换为自定义切片列表的返回格式。"""
        return {
            "chunk_id": source.get("id", ""),
            "content_with_weight": source.get("content_with_weight", ""),
            "doc_id": source.get("doc_id", ""),
            "docnm_kwd": source.get("docnm_kwd", ""),
            "chunk_title_kwd": source.get("chunk_title_kwd", ""),
            "important_kwd": source.get("important_kwd", []),
            "question_kwd": source.get("question_kwd", []),
            "image_id": source.get("img_id", ""),
            "available_int": int(source.get("available_int", 1)),
            "create_user_name": source.get("create_user_name", ""),
            "create_time": source.get("create_time", ""),
        }

    @staticmethod
    def _source_matches_kb(source: dict[str, Any], kb_ids: list[str]) -> bool:
        """校验文档的 kb_id 是否在目标列表中。"""
        kb_value = source.get("kb_id")
        if isinstance(kb_value, list):
            return bool(set(kb_value) & set(kb_ids))
        return kb_value in kb_ids

    # ------------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------------

    @staticmethod
    def _infer_vector_size(row: dict[str, Any]) -> int:
        """从 row 中推断向量维度。"""
        for key, value in row.items():
            if key.startswith("q_") and key.endswith("_vec") and isinstance(value, list):
                return len(value)
        return 0


es_service = ESService()
