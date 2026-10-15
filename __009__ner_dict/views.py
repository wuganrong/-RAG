"""NER 词典接口视图。"""

from __future__ import annotations

# 1. Python 标准库
import threading
from typing import Any

# 2. 第三方库
from django.db.models import QuerySet
from drf_spectacular.utils import OpenApiParameter, OpenApiTypes, extend_schema
from loguru import logger
from rest_framework.decorators import api_view
from rest_framework.request import Request
from rest_framework.response import Response

# 3. 本地应用
import __001__rag.nlp.query as q_mod
import __001__rag.nlp.synonym as syn_mod
import __001__rag.nlp.term_weight as tw_mod
from __001__rag.models import NerDict, SysDict
from __001__rag.nlp.data import NLPData
from __001__rag.nlp.tokenizer import _TrieDict, tokenizer as nlp_tokenizer
from __001__rag.startup import TrieManager
from __001__rag.utils import error_response, format_datetime, get_uuid, success_response

from .serializers import (
    NerDictAddSerializer,
    NerDictDeleteSerializer,
    NerDictGetTypesSerializer,
    NerDictListPageSerializer,
    NerDictRefreshSerializer,
    NerDictUpdateSerializer,
)

_NER_DICT_TAG = ["ner_dict"]


def _get_user_id(request: Request) -> str:
    """从请求头 X-User-Id 中读取用户 ID。"""
    return request.META.get("HTTP_X_USER_ID", "")


def _ner_dict_to_dict(ner_dict: NerDict) -> dict[str, Any]:
    """将 NerDict 实例转换为响应字典。"""
    return {
        "id": ner_dict.id,
        "tag": ner_dict.tag,
        "type": ner_dict.type,
        "dict": ner_dict.dict,
        "synonym": ner_dict.synonym,
        "f": ner_dict.f,
        "n": ner_dict.n,
        "status": ner_dict.status,
        "remark": ner_dict.remark,
        "create_by": ner_dict.create_by,
        "update_by": ner_dict.update_by,
        "create_date": format_datetime(ner_dict.create_date),
        "update_date": format_datetime(ner_dict.update_date),
    }


def _apply_list_filters(
    queryset: QuerySet[NerDict],
    tag: str | None,
    dict_keyword: str | None,
    n: str | None,
    status_val: str | None,
    synonym: str | None,
    type_val: str | None,
) -> QuerySet[NerDict]:
    """应用列表查询过滤条件。"""
    if tag:
        queryset = queryset.filter(tag=tag)
    if dict_keyword:
        queryset = queryset.filter(dict__icontains=dict_keyword)
    if n:
        queryset = queryset.filter(n=n)
    if status_val:
        queryset = queryset.filter(status=status_val)
    if synonym:
        queryset = queryset.filter(synonym__icontains=synonym)
    if type_val:
        queryset = queryset.filter(type=type_val)
    return queryset


@extend_schema(
    tags=_NER_DICT_TAG,
    summary="分页查询词典列表",
    description="支持按 tag、type、dict 关键词、status、n、synonym 等条件过滤。",
    parameters=[
        OpenApiParameter("page", OpenApiTypes.INT, description="当前页码，默认 1"),
        OpenApiParameter("page_size", OpenApiTypes.INT, description="每页条数，默认 10"),
        OpenApiParameter("tag", OpenApiTypes.STR, description="类型标识(ner,dict,synonym)"),
        OpenApiParameter("type", OpenApiTypes.STR, description="细分类型"),
        OpenApiParameter("dict", OpenApiTypes.STR, description="词典词关键词"),
        OpenApiParameter("status", OpenApiTypes.STR, description="状态"),
        OpenApiParameter("n", OpenApiTypes.STR, description="词性"),
        OpenApiParameter("synonym", OpenApiTypes.STR, description="同义词"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def ner_dict_list_page(request: Request) -> Response:
    """GET /rag/ner_dict/list_page — 分页查询词典列表。"""
    ser = NerDictListPageSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    page: int = vd["page"]
    page_size: int = vd["page_size"]
    tag: str | None = vd.get("tag") or None
    type_val: str | None = vd.get("type") or None
    dict_keyword: str | None = vd.get("dict") or None
    status_val: str | None = vd.get("status") or None
    n: str | None = vd.get("n") or None
    synonym: str | None = vd.get("synonym") or None

    queryset = NerDict.objects.all()
    queryset = _apply_list_filters(queryset, tag, dict_keyword, n, status_val, synonym, type_val)
    queryset = queryset.order_by("-update_date")

    total: int = queryset.count()
    offset: int = (page - 1) * page_size
    records: list[NerDict] = list(queryset[offset: offset + page_size])

    return success_response({
        "total": total,
        "list": [_ner_dict_to_dict(r) for r in records],
    })


@extend_schema(
    tags=_NER_DICT_TAG,
    summary="新增词典",
    description="新增词典记录，支持 ner、dict、synonym 三种类型。",
    request=NerDictAddSerializer,
    responses={200: None},
)
@api_view(["POST"])
def ner_dict_add(request: Request) -> Response:
    """POST /rag/ner_dict/add — 新增词典。"""
    ser = NerDictAddSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    user_id: str = _get_user_id(request)
    dict_val: str | None = vd.get("dict") or None
    tag: str | None = vd.get("tag") or None

    if dict_val and tag:
        existing: list[NerDict] = list(
            NerDict.objects.filter(dict=dict_val, tag=tag, status="0")
        )
        if existing:
            return error_response("词典已存在")

    entity: dict[str, Any] = {
        "id": get_uuid(),
        "dict": dict_val,
        "tag": tag,
        "type": vd.get("type"),
        "synonym": vd.get("synonym"),
        "f": vd.get("f"),
        "n": vd.get("n"),
        "remark": vd.get("remark"),
        "create_by": user_id,
        "update_by": user_id,
        "status": "0",
    }

    ner_dict = NerDict.objects.create(**entity)
    return success_response({"id": ner_dict.id, "message": "创建成功"})


@extend_schema(
    tags=_NER_DICT_TAG,
    summary="更新词典",
    description="根据 ID 更新词典记录。",
    request=NerDictUpdateSerializer,
    responses={200: None},
)
@api_view(["POST"])
def ner_dict_update(request: Request) -> Response:
    """POST /rag/ner_dict/update — 更新词典。"""
    ser = NerDictUpdateSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    vd = ser.validated_data
    user_id: str = _get_user_id(request)
    record_id: str | None = vd.get("id")

    try:
        ner_dict = NerDict.objects.get(id=record_id)
    except NerDict.DoesNotExist:
        return error_response("记录不存在", code=404)

    update_fields: list[str] = ["update_by"]
    ner_dict.update_by = user_id

    if "dict" in vd and vd["dict"]:
        ner_dict.dict = vd["dict"]
        update_fields.append("dict")
    if "tag" in vd and vd["tag"]:
        ner_dict.tag = vd["tag"]
        update_fields.append("tag")
    if "type" in vd:
        ner_dict.type = vd["type"]
        update_fields.append("type")
    if "synonym" in vd:
        ner_dict.synonym = vd["synonym"]
        update_fields.append("synonym")
    if "f" in vd:
        ner_dict.f = vd["f"]
        update_fields.append("f")
    if "n" in vd and vd["n"]:
        ner_dict.n = vd["n"]
        update_fields.append("n")
    if "status" in vd and vd["status"]:
        ner_dict.status = vd["status"]
        update_fields.append("status")
    if "remark" in vd:
        ner_dict.remark = vd["remark"]
        update_fields.append("remark")

    ner_dict.save(update_fields=update_fields)

    return success_response({"affected_rows": 1, "message": "更新成功"})


@extend_schema(
    tags=_NER_DICT_TAG,
    summary="删除词典",
    description="根据 ID 删除词典记录。",
    request=NerDictDeleteSerializer,
    responses={200: None},
)
@api_view(["POST"])
def ner_dict_delete(request: Request) -> Response:
    """POST /rag/ner_dict/delete — 删除词典。"""
    ser = NerDictDeleteSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    record_id: str = ser.validated_data["id"]

    try:
        ner_dict = NerDict.objects.get(id=record_id)
    except NerDict.DoesNotExist:
        return error_response("记录不存在", code=404)

    ner_dict.delete()

    return success_response({"affected_rows": 1, "message": "删除成功"})


@extend_schema(
    tags=_NER_DICT_TAG,
    summary="查询词典类型枚举",
    description="根据 type_code 查询对应的字典描述列表。",
    parameters=[
        OpenApiParameter("type_code", OpenApiTypes.STR, description="类型编码"),
    ],
    responses={200: None},
)
@api_view(["GET"])
def ner_dict_get_types(request: Request) -> Response:
    """GET /rag/ner_dict/getTypes — 查询词典类型枚举。"""
    ser = NerDictGetTypesSerializer(data=request.GET)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    type_code: str | None = ser.validated_data.get("type_code")
    if not type_code:
        return success_response([])

    records: QuerySet[SysDict] = SysDict.objects.filter(key=type_code, status="1")
    types: list[str] = [r.value for r in records if r.value]

    return success_response(types)


@extend_schema(
    tags=_NER_DICT_TAG,
    summary="刷新词典缓存",
    description="根据 tag 类型重新加载 NLP 数据并重建 trie、单例，更新 Redis 缓存。",
    request=NerDictRefreshSerializer,
    responses={200: None},
)
@api_view(["POST"])
def ner_dict_refresh(request: Request) -> Response:
    """POST /rag/ner_dict/refresh — 刷新词典缓存。

    刷新逻辑：
    1. 强制从数据库重新加载 NLPData（同时更新 Redis 缓存）
    2. dict tag：后台线程重建 marisa-trie + 原子替换 tokenizer
    3. ner tag：同步重建 term_weight 单例
    4. synonym tag：同步重建 synonym 单例，并同时刷新 replace_synonym 表
    5. replace_synonym tag：仅刷新 replace_synonym 表并重建 synonym 单例
    """
    ser = NerDictRefreshSerializer(data=request.data)
    if not ser.is_valid():
        return error_response(str(ser.errors))

    tag: str = ser.validated_data["tag"]
    logger.info("开始刷新词典缓存，tag={}", tag)

    try:
        # 按 tag 增量刷新 NLPData（内部已更新 Redis nlp:cache:data）
        data = NLPData.reload(tag=tag)

        if tag == "dict":
            # 后台线程：原子替换 tokenizer trie + 持久化（不阻塞 HTTP 响应）
            def _rebuild_dict_trie():
                try:
                    if data.dict_trie_entries is not None:
                        nlp_tokenizer.trie_ = _TrieDict(data.dict_trie_entries)
                        TrieManager._persist(data.dict_trie_entries)
                        logger.info("marisa-trie 词典刷新完成，词条 {} 条",
                                    len(data.dict_trie_entries))
                except Exception:
                    logger.exception("marisa-trie 词典后台刷新失败")

            threading.Thread(target=_rebuild_dict_trie, daemon=True).start()

        elif tag == "ner":
            # 重建 term_weight dealer（依赖 ner_lookup）
            tw_mod.dealer = tw_mod.Dealer(data)
            if q_mod.queryer is not None:
                q_mod.queryer.tw = tw_mod.dealer

        elif tag in ("synonym", "replace_synonym"):
            # 重建 synonym dealer + queryer（synonym_lookup / replace_synonyms）
            syn_mod.dealer = syn_mod.Dealer(data)
            if q_mod.queryer is not None:
                q_mod.queryer = q_mod.FulltextQueryer(
                    tw=tw_mod.dealer or tw_mod.Dealer(data),
                    syn=syn_mod.dealer,
                )

        logger.info("词典缓存刷新完成，tag={}", tag)
        return success_response({"message": "刷新成功"})

    except Exception as e:
        logger.exception("词典缓存刷新失败，tag={}", tag)
        return error_response(f"刷新失败: {e}")
