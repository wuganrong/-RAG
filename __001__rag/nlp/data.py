"""统一 NLP 数据加载 — 一次 DB 查询，构建各模块所需的最优格式。"""

from __future__ import annotations

# 1. Python 标准库
import base64
import math
import pickle
import struct
import threading
import time
import zlib
from dataclasses import dataclass, field

# 2. 第三方库
import marisa_trie
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.models import NerDict, ReplaceSynonym
from __001__rag.storage.redis_service import redis_service

DENOMINATOR = 1000000

_cached_data: NLPData | None = None
_cache_lock = threading.Lock()

# POS tag ↔ byte 映射（共 12 种，远小于 uint8 上限 255）
_POS_LIST = ("noun", "verb", "adj", "adv", "pron", "prep",
             "conj", "aux", "interj", "num", "class", "")
POS_TO_BYTE: dict[str, int] = {tag: i for i, tag in enumerate(_POS_LIST)}
POS_RMAP: dict[int, str] = {i: tag for i, tag in enumerate(_POS_LIST)}
_DEFAULT_POS_BYTE: int = POS_TO_BYTE[""]


def _get_data_cache_key() -> str:
    """从 settings 读取 NLP data 缓存 key。"""
    return getattr(settings, "NLP_DATA_CACHE_KEY", "nlp:cache:data")


def _serialize(obj) -> str:
    """pickle → zlib 压缩 → base64 编码为字符串。"""
    return base64.b64encode(zlib.compress(pickle.dumps(obj))).decode("ascii")


def _deserialize(raw: str):
    """base64 解码 → zlib 解压 → pickle 反序列化。"""
    return pickle.loads(zlib.decompress(base64.b64decode(raw.encode("ascii"))))


@dataclass(slots=True)
class NLPData:
    """一次加载 NerDict + ReplaceSynonym，预构建所有 NLP 模块需要的格式。

    使用方法::

        data = NLPData.load()
        tokenizer.load_dict(data)       # 构建 trie
        Dealer(data)                    # 直接使用 data.ner_lookup / data.synonym_lookup
    """

    # tokenizer: encoded_key/reverse_key → bytes (struct '<hB': log_freq, pos_byte)
    dict_trie_entries: marisa_trie.BytesTrie | None = None

    # term_weight: word → entity_type (e.g. {"华为": "corp", "北京": "loca"})
    ner_lookup: dict[str, str] = field(default_factory=dict)

    # synonym: word → [synonym1, synonym2, ...]
    synonym_lookup: dict[str, list[str]] = field(default_factory=dict)
    # synonym: ReplaceSynonym 表记录列表
    replace_synonyms: list[dict[str, str]] = field(default_factory=list)

    @classmethod
    def load(cls) -> "NLPData":
        """加载 NLP 数据：内存缓存 → Redis 缓存 → 数据库查询。"""
        global _cached_data
        t0 = time.monotonic()
        if _cached_data is not None:
            logger.info("NLP 数据缓存命中 (内存)，耗时 {:.3f}s", time.monotonic() - t0)
            return _cached_data

        with _cache_lock:
            if _cached_data is not None:
                return _cached_data
            data = cls._load_from_redis()
            if data is not None:
                _cached_data = data
                logger.info("NLP 数据缓存命中 (Redis)，跳过数据库查询，耗时 {:.3f}s", time.monotonic() - t0)
                return data
            data = cls._load_from_db()
            cls._save_to_redis(data)
            _cached_data = data
            return data

    @classmethod
    def reload(cls, tag: str | None = None) -> "NLPData":
        """强制刷新缓存。tag 为 None 时全量刷新，否则按 ner/dict/synonym/replace_synonym 增量刷新。"""
        with _cache_lock:
            data = cls._load_from_db()
            cls._save_to_redis(data)
            return data

    @classmethod
    def _load_from_redis(cls) -> "NLPData | None":
        """从 Redis 加载缓存的 NLPData（不含 trie，trie 由 TrieManager 单独加载）。"""
        try:
            cache_key = _get_data_cache_key()
            raw = redis_service.get(cache_key)
            if raw:
                data = _deserialize(raw)
                if cls._is_cache_compatible(data):
                    return data
                redis_service.delete(cache_key)
                logger.info("Redis NLP 数据缓存结构已过期，已删除并回退到数据库加载")
                return None
            logger.info("Redis 缓存已过期或不存在，从数据库重新加载")
        except Exception as e:
            try:
                cache_key = _get_data_cache_key()
                redis_service.delete(cache_key)
                logger.info("Redis NLP 数据缓存读取失败，已删除旧缓存 key={}", cache_key)
            except Exception as cleanup_exc:
                logger.info("Redis NLP 数据缓存清理失败 key={} error={}", _get_data_cache_key(), cleanup_exc)
            logger.info("Redis 缓存读取失败: {}，回退到数据库加载", e)
        return None

    @staticmethod
    def _is_cache_compatible(data: object) -> bool:
        """校验 Redis 中的 NLPData 结构是否兼容。"""
        return isinstance(data, NLPData)

    @classmethod
    def _save_to_redis(cls, data: "NLPData") -> None:
        """将 NLPData 序列化后存入 Redis（trie 单独缓存，此处排除）。"""
        try:
            # BytesTrie 不可 pickle，排除后单独由 TrieManager 持久化
            saved_trie = data.dict_trie_entries
            data.dict_trie_entries = None
            try:
                ttl = getattr(settings, "NLP_CACHE_TTL", 86400)
                redis_service.set(_get_data_cache_key(), _serialize(data), ex=ttl)
                logger.info("NLP 数据已缓存至 Redis (TTL={}s)", ttl)
            finally:
                data.dict_trie_entries = saved_trie
        except Exception as e:
            logger.info("NLP 数据 Redis 缓存写入失败: {}", e)

    @classmethod
    def _load_replace_synonyms(cls, data: "NLPData") -> int:
        """增量加载 ReplaceSynonym 表数据，返回加载条数。"""
        data.replace_synonyms = list(
            ReplaceSynonym.objects.filter(status="0").values("dict", "synonym")
        )
        return len(data.replace_synonyms)

    @classmethod
    def _load_tag(cls, data: "NLPData", tag: str) -> None:
        """增量加载指定 tag 的数据，直接修改传入的 data 实例。"""
        t0 = time.monotonic()
        try:
            records = (
                NerDict.objects
                .filter(status="0", tag=tag)
                .values("tag", "type", "dict", "synonym", "f", "n")
            )

            if tag == "dict":
                entries: dict[str, bytes] = {}
                for row in records.iterator():
                    word = row.get("dict") or ""
                    if not word:
                        continue
                    f_val = row.get("f") or 0
                    n_val = row.get("n") or ""
                    k = _encode_key(word)
                    rk = _encode_rkey(word)
                    F = int(math.log(float(f_val) / DENOMINATOR) + 0.5) if f_val > 0 else 0
                    pos_byte = POS_TO_BYTE.get(n_val, _DEFAULT_POS_BYTE)
                    # 正向词条：(log_freq, pos_byte)
                    old = entries.get(k)
                    if old is not None:
                        old_freq = struct.unpack('<h', old[:2])[0]
                        if old_freq >= F:
                            continue
                    entries[k] = struct.pack('<hB', F, pos_byte)
                    # 反向词条（用于逆向最大匹配）
                    entries[rk] = struct.pack('<hB', 1, _DEFAULT_POS_BYTE)
                data.dict_trie_entries = marisa_trie.BytesTrie(entries.items()) if entries else marisa_trie.BytesTrie()
                logger.info("NLP dict 数据增量刷新完成 (marisa-trie)，词条 {} 条，耗时 {:.3f}s",
                            len(entries), time.monotonic() - t0)

            elif tag == "ner":
                ner: dict[str, str] = {}
                for row in records.iterator():
                    word = row.get("dict") or ""
                    if not word:
                        continue
                    _type = row.get("type") or ""
                    if _type:
                        ner[word] = _type
                data.ner_lookup = ner
                logger.info("NLP ner 数据增量刷新完成，实体 {} 条，耗时 {:.3f}s", len(ner), time.monotonic() - t0)

            elif tag == "synonym":
                synonym: dict[str, list[str]] = {}
                for row in records.iterator():
                    word = row.get("dict") or ""
                    if not word:
                        continue
                    syn_raw = row.get("synonym") or ""
                    if syn_raw and "," in syn_raw:
                        synonym[word] = syn_raw.split(",")
                    elif syn_raw:
                        synonym[word] = [syn_raw]
                    else:
                        synonym[word] = []
                data.synonym_lookup = synonym
                replace_count = cls._load_replace_synonyms(data)
                logger.info(
                    "NLP synonym 数据增量刷新完成，同义词 {} 条，replace {} 条，耗时 {:.3f}s",
                    len(synonym), replace_count, time.monotonic() - t0,
                )

        except Exception:
            logger.exception("NLPData._load_tag 失败 tag={}", tag)

    @classmethod
    def _load_from_db(cls) -> "NLPData":
        """全量 DB 查询并构建数据结构。"""
        t0 = time.monotonic()
        data = cls()
        try:
            cls._load_tag(data, "dict")
            cls._load_tag(data, "ner")
            cls._load_tag(data, "synonym")
            cls._load_tag(data, "synonym")

            trie_len = len(data.dict_trie_entries) if data.dict_trie_entries else 0
            logger.info(
                "NLP 数据全量加载完成 (marisa-trie)，词条 {} 条，耗时 {:.3f}s",
                trie_len, time.monotonic() - t0,
            )
        except Exception:
            logger.exception("NLPData._load_from_db 失败")
        return data


# ------------------------------------------------------------------
# 键编码
# ------------------------------------------------------------------

def _encode_key(line: str) -> str:
    return str(line.lower().encode("utf-8"))[2:-1]


def _encode_rkey(line: str) -> str:
    return str(("DD" + (line[::-1].lower())).encode("utf-8"))[2:-1]
