"""同义词查找 —— 中文 DB 查找 + 英文 WordNet。

中文同义词和 ReplaceSynonym 数据由 NLPData.load() 统一提供，
英文同义词使用 NLTK WordNet。
"""

from __future__ import annotations

# 1. Python 标准库
import re
import time

# 2. 第三方库
from loguru import logger
from nltk.corpus import wordnet

# 3. 本地应用
from __001__rag.nlp.data import NLPData


class Dealer:
    """同义词查找器。"""

    def __init__(self, data=None):
        self.lookup_num = 100000000
        self.load_tm = time.time() - 1000000

        if data is not None:
            self.dictionary = data.synonym_lookup
            self.replaceSynonym = data.replace_synonyms
        else:
            d = NLPData.load()
            self.dictionary = d.synonym_lookup
            self.replaceSynonym = d.replace_synonyms

        if not self.dictionary:
            logger.info("同义词词典加载为空")

    def lookup(self, tk: str, topn: int = 8) -> list[str]:
        """查找同义词，中文查 DB，英文查 WordNet。"""
        if re.match(r"[a-z]+$", tk):
            res = list(
                set(
                    [
                        re.sub("_", " ", syn.name().split(".")[0])
                        for syn in wordnet.synsets(tk)
                    ]
                )
                - {tk}
            )
            return [t for t in res if t]

        self.lookup_num += 1
        res = self.dictionary.get(re.sub(r"[ \t]+", " ", tk.lower()), [])
        if isinstance(res, str):
            res = [res]
        return res[:topn]

    def replace_questions(self, questions: list[str]) -> list[str]:
        """根据 replaceSynonym 表替换问句中的词。"""
        if not questions:
            return questions
        replace_list = self.replaceSynonym or []
        if not replace_list:
            return questions
        try:
            pairs: list[tuple[str, str]] = []
            for r in replace_list:
                d = r.get("dict") or ""
                syn = r.get("synonym") or ""
                if d and syn:
                    pairs.append((d.lower(), syn))
            result = []
            for q in questions:
                for dict_word, synonym in pairs:
                    if dict_word.lower() in q.lower():
                        q = re.sub(re.escape(dict_word), synonym, q, flags=re.IGNORECASE)
                result.append(q)
            return result
        except Exception:
            logger.exception("同义词替换失败")
            return questions


# 模块级单例，由 init_nlp() 初始化
dealer: Dealer | None = None
