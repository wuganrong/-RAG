"""Elasticsearch 索引 mapping 配置。"""

from __future__ import annotations

# 1. Python 标准库
from copy import deepcopy
from typing import Any

# 2. 第三方库
from django.conf import settings


def _build_default_mapping() -> dict[str, Any]:
    """构建默认 ES mapping，索引参数从 settings 读取。"""
    return {
        "settings": {
            "index": {
                "number_of_shards": int(getattr(settings, "ES_NUMBER_OF_SHARDS", 2)),
                "number_of_replicas": int(getattr(settings, "ES_NUMBER_OF_REPLICAS", 0)),
                "refresh_interval": getattr(settings, "ES_REFRESH_INTERVAL", "1000ms"),
            },
            "similarity": {
                "scripted_sim": {
                    "type": "scripted",
                    "script": {
                        "source": (
                            "double idf = Math.log(1+(field.docCount-term.docFreq+0.5)/(term.docFreq + 0.5))"
                            "/Math.log(1+((field.docCount-0.5)/1.5)); "
                            "return query.boost * idf * Math.min(doc.freq, 1);"
                        ),
                    },
                },
            },
        },
        "mappings": {
            "properties": {
                "chunk_order": {
                    "type": "long",
                    "store": True,
                },
                "lat_lon": {
                    "type": "geo_point",
                    "store": "true",
                },
                "parent_group_id": {
                    "type": "keyword",
                    "store": True,
                },
            },
            "date_detection": "true",
            "dynamic_templates": [
                {"int": {"match": "*_int", "mapping": {"type": "integer", "store": "true"}}},
                {"ulong": {"match": "*_ulong", "mapping": {"type": "unsigned_long", "store": "true"}}},
                {"long": {"match": "*_long", "mapping": {"type": "long", "store": "true"}}},
                {"short": {"match": "*_short", "mapping": {"type": "short", "store": "true"}}},
                {"numeric": {"match": "*_flt", "mapping": {"type": "float", "store": True}}},
                {
                    "tks": {
                        "match": "*_tks",
                        "mapping": {
                            "type": "text",
                            "similarity": "scripted_sim",
                            "analyzer": "whitespace",
                            "store": True,
                        },
                    },
                },
                {
                    "ltks": {
                        "match": "*_ltks",
                        "mapping": {"type": "text", "analyzer": "whitespace", "store": True},
                    },
                },
                {
                    "kwd": {
                        "match_pattern": "regex",
                        "match": "^(.*_(kwd|id|ids|uid|uids)|uid)$",
                        "mapping": {"type": "keyword", "similarity": "boolean", "store": True},
                    },
                },
                {
                    "dt": {
                        "match_pattern": "regex",
                        "match": "^.*(_dt|_time|_at)$",
                        "mapping": {
                            "type": "date",
                            "format": "yyyy-MM-dd HH:mm:ss||yyyy-MM-dd||yyyy-MM-dd_HH:mm:ss",
                            "store": True,
                        },
                    },
                },
                {"nested": {"match": "*_nst", "mapping": {"type": "nested"}}},
                {"object": {"match": "*_obj", "mapping": {"type": "object", "dynamic": "true"}}},
                {
                    "string": {
                        "match_pattern": "regex",
                        "match": "^.*_(with_weight|list)$",
                        "mapping": {"type": "text", "index": "false", "store": True},
                    },
                },
                {"rank_feature": {"match": "*_fea", "mapping": {"type": "rank_feature"}}},
                {"rank_features": {"match": "*_feas", "mapping": {"type": "rank_features"}}},
                {
                    "dense_vector_512": {
                        "match": "*_512_vec",
                        "mapping": {"type": "dense_vector", "index": True, "similarity": "cosine", "dims": 512},
                    },
                },
                {
                    "dense_vector_768": {
                        "match": "*_768_vec",
                        "mapping": {"type": "dense_vector", "index": True, "similarity": "cosine", "dims": 768},
                    },
                },
                {
                    "dense_vector_1024": {
                        "match": "*_1024_vec",
                        "mapping": {"type": "dense_vector", "index": True, "similarity": "cosine", "dims": 1024},
                    },
                },
                {
                    "dense_vector_1536": {
                        "match": "*_1536_vec",
                        "mapping": {"type": "dense_vector", "index": True, "similarity": "cosine", "dims": 1536},
                    },
                },
                {
                    "dense_vector_2048": {
                        "match": "*_2048_vec",
                        "mapping": {"type": "dense_vector", "index": True, "similarity": "cosine", "dims": 2048},
                    },
                },
                {"binary": {"match": "*_bin", "mapping": {"type": "binary"}}},
            ],
        },
    }


DEFAULT_ES_MAPPING: dict[str, Any] = _build_default_mapping()


def get_default_es_mapping() -> dict[str, Any]:
    """返回可安全修改的默认 ES mapping。"""
    return deepcopy(DEFAULT_ES_MAPPING)
