"""词权重计算 —— NER 实体类型、词性、词频、文档频率综合加权。

综合 NER 实体类型、词性、词频、文档频率计算归一化 token 重要性权重。
NER 数据由 NLPData.load() 统一提供。
"""

from __future__ import annotations

# 1. Python 标准库
import math
import re

# 2. 第三方库
import numpy as np
from loguru import logger

# 3. 本地应用
from __001__rag.nlp import tokenizer as rag_tokenizer
from __001__rag.nlp.data import NLPData


class Dealer:
    """IDF-Based 词权重计算器。"""

    def __init__(self, data=None):
        self.stop_words = {
            "请问", "您", "你", "我", "他", "是", "的", "就", "有", "于", "及", "即",
            "在", "为", "最", "有", "从", "以", "了", "将", "与", "吗", "吧", "中",
            "#", "什么", "怎么", "哪个", "哪些", "啥", "相关",
        }
        self.df: dict[str, int] = {}
        self.sk: set = set()

        if data is not None:
            self.ne = data.ner_lookup
        else:
            self.ne = NLPData.load().ner_lookup

    def pretoken(self, txt: str, num: bool = False, stpwd: bool = True) -> list[str]:
        patt = [
            r"[~—\t @#%!<>,\.\?\":;'\{\}\[\]_=\(\)\|，。？》•●○↓《；‘’：“”【¥ 】…￥！、·（）×`&\\/「」\\]"
        ]
        rewt: list[tuple[str, str]] = []
        for p, r in rewt:
            txt = re.sub(p, r, txt)

        res: list[str] = []
        for t in rag_tokenizer.tokenize(txt).split():
            tk = t
            if (stpwd and tk in self.stop_words) or (re.match(r"[0-9]$", tk) and not num):
                continue
            for p in patt:
                if re.match(p, t):
                    tk = "#"
                    break
            if tk != "#" and tk:
                res.append(tk)
        return res

    def tokenMerge(self, tks: list[str]) -> list[str]:
        def oneTerm(t: str) -> bool:
            return len(t) == 1 or bool(re.match(r"[0-9a-z]{1,2}$", t))

        res: list[str] = []
        i = 0
        while i < len(tks):
            j = i
            if i == 0 and oneTerm(tks[i]) and len(tks) > 1 and (
                len(tks[i + 1]) > 1 and not re.match(r"[0-9a-zA-Z]", tks[i + 1])
            ):
                res.append(" ".join(tks[0:2]))
                i = 2
                continue

            while j < len(tks) and tks[j] and tks[j] not in self.stop_words and oneTerm(tks[j]):
                j += 1
            if j - i > 1:
                if j - i < 5:
                    res.append(" ".join(tks[i:j]))
                    i = j
                else:
                    res.append(" ".join(tks[i : i + 2]))
                    i = i + 2
            else:
                if len(tks[i]) > 0:
                    res.append(tks[i])
                i += 1
        return [t for t in res if t]

    def ner(self, t: str) -> str:
        if not self.ne:
            return ""
        return self.ne.get(t, "")

    def split(self, txt: str) -> list[str]:
        tks = []
        for t in re.sub(r"[ \t]+", " ", txt).split():
            if (
                tks
                and re.match(r".*[a-zA-Z]$", tks[-1])
                and re.match(r".*[a-zA-Z]$", t)
                and tks
                and self.ne.get(t, "") != "func"
                and self.ne.get(tks[-1], "") != "func"
            ):
                tks[-1] = tks[-1] + " " + t
            else:
                tks.append(t)
        return tks

    def weights(self, tks: list[str], preprocess: bool = True) -> list[tuple[str, float]]:
        """计算 token 归一化权重（总和为 1）。"""

        def skill(t: str) -> float:
            if t not in self.sk:
                return 1
            return 6

        def _ner(t: str) -> float:
            if re.match(r"[0-9,.]{2,}$", t):
                return 2
            if re.match(r"[a-z]{1,2}$", t):
                return 0.01
            if not self.ne or t not in self.ne:
                return 1
            m = {
                "toxic": 2, "func": 1, "corp": 3, "loca": 3,
                "sch": 3, "stock": 3, "firstnm": 1,
            }
            return m[self.ne[t]]

        def _postag(t: str) -> float:
            t = rag_tokenizer.tag(t)
            if t in {"r", "c", "d"}:
                return 0.3
            if t in {"ns", "nt"}:
                return 3
            if t in {"n"}:
                return 2
            if re.match(r"[0-9-]+", t):
                return 2
            return 1

        def _freq(t: str) -> float:
            if re.match(r"[0-9. -]{2,}$", t):
                return 3
            s = rag_tokenizer.freq(t)
            if not s and re.match(r"[a-z. -]+$", t):
                return 300
            if not s:
                s = 0

            if not s and len(t) >= 4:
                s_list = [
                    tt
                    for tt in rag_tokenizer.fine_grained_tokenize(t).split()
                    if len(tt) > 1
                ]
                if len(s_list) > 1:
                    s = np.min([_freq(tt) for tt in s_list]) / 6.0
                else:
                    s = 0

            return max(s, 10)

        def _df(t: str) -> float:
            if re.match(r"[0-9. -]{2,}$", t):
                return 5
            if t in self.df:
                return self.df[t] + 3
            if re.match(r"[a-z. -]+$", t):
                return 300
            if len(t) >= 4:
                s_list = [
                    tt
                    for tt in rag_tokenizer.fine_grained_tokenize(t).split()
                    if len(tt) > 1
                ]
                if len(s_list) > 1:
                    return max(3, np.min([_df(tt) for tt in s_list]) / 6.0)
            return 3

        def _idf(s: float, N: int) -> float:
            return math.log10(10 + ((N - s + 0.5) / (s + 0.5)))

        tw: list[tuple[str, float]] = []

        if not preprocess:
            idf1 = np.array([_idf(_freq(t), 10000000) for t in tks])
            idf2 = np.array([_idf(_df(t), 1000000000) for t in tks])
            wts = (0.3 * idf1 + 0.7 * idf2) * np.array([_ner(t) * _postag(t) for t in tks])
            wts = [float(s) for s in wts]
            tw = list(zip(tks, wts))
        else:
            for tk in tks:
                tt = self.tokenMerge(self.pretoken(tk, True))
                idf1 = np.array([_idf(_freq(t), 10000000) for t in tt])
                idf2 = np.array([_idf(_df(t), 1000000000) for t in tt])
                wts = (0.3 * idf1 + 0.7 * idf2) * np.array([_ner(t) * _postag(t) for t in tt])
                wts = [float(s) for s in wts]
                tw.extend(zip(tt, wts))

        S = np.sum([s for _, s in tw])
        return [(t, s / S) for t, s in tw]


# 模块级单例，由 init_nlp() 初始化
dealer: Dealer | None = None
