"""中文分词器 —— 基于前缀树的最大匹配 + DFS 消歧。

使用前向/后向最大匹配 + DFS 消歧进行中文分词，
词典数据由 NLPData.load() 统一提供。
"""

from __future__ import annotations

# 1. Python 标准库
import copy
import math
import re
import struct

# 2. 第三方库
import marisa_trie
from hanziconv import HanziConv
from loguru import logger
from nltk import word_tokenize
from nltk.stem import PorterStemmer, WordNetLemmatizer

# 3. 本地应用
from __001__rag.nlp.data import NLPData, POS_RMAP

DENOMINATOR = 1000000
_SPLIT_CHAR = re.compile(r"([ ,\.<>/?;:'\[\]\\`!@#$%^&*\(\)\{\}\|_+=《》，。？、；‘'：“”【】~！￥%……（）——-]+|[a-zA-Z0-9,\.-]+)")


def is_chinese(ch: str) -> bool:
    return "一" <= ch <= "龥"


def is_number(ch: str) -> bool:
    return "0" <= ch <= "9"


def is_alphabet(ch: str) -> bool:
    return ("A" <= ch <= "Z") or ("a" <= ch <= "z")


class _TrieDict:
    """marisa_trie.BytesTrie + struct 解码的轻量包装，对外兼容 datrie.Trie 的访问模式。"""

    __slots__ = ("_trie",)

    def __init__(self, trie: marisa_trie.BytesTrie):
        self._trie = trie

    def __contains__(self, k: str) -> bool:
        return k in self._trie

    def __len__(self) -> int:
        return len(self._trie)

    def __getitem__(self, k: str) -> tuple[int, str]:
        raw = self._trie[k][0]
        log_freq, pos_byte = struct.unpack('<hB', raw)
        return log_freq, POS_RMAP.get(pos_byte, "")

    def has_prefix(self, k: str) -> bool:
        """替代 datrie.has_keys_with_prefix(k)，使用 iterkeys 惰性检查。"""
        try:
            next(self._trie.iterkeys(k))
            return True
        except StopIteration:
            return False


class RagTokenizer:
    """中文分词器，基于前缀树的最大匹配 + DFS 消歧。"""

    def __init__(self, debug: bool = False):
        self.DEBUG = debug
        self.stemmer = PorterStemmer()
        self.lemmatizer = WordNetLemmatizer()
        self.trie_ = _TrieDict(marisa_trie.BytesTrie())

    # ------------------------------------------------------------------
    # 键编码
    # ------------------------------------------------------------------

    def key_(self, line: str) -> str:
        return str(line.lower().encode("utf-8"))[2:-1]

    def rkey_(self, line: str) -> str:
        return str(("DD" + (line[::-1].lower())).encode("utf-8"))[2:-1]

    # ------------------------------------------------------------------
    # 词典加载
    # ------------------------------------------------------------------

    def load_dict(self, data=None) -> None:
        """从 NLPData 加载词典到 trie（由 init_nlp 统一调用）。"""
        if data is None:
            data = NLPData.load()

        try:
            if data.dict_trie_entries is None:
                logger.info("NLPData 不含 marisa-trie，跳过词典加载")
                return
            self.trie_ = _TrieDict(data.dict_trie_entries)
            logger.info("自定义分词器词典加载完成 (marisa-trie) entries={}", len(self.trie_))
        except Exception:
            logger.exception("自定义分词器词典加载失败")

    def set_trie(self, trie: marisa_trie.BytesTrie) -> None:
        """直接设置已加载的 BytesTrie（由 TrieManager 调用）。"""
        self.trie_ = _TrieDict(trie)
        logger.info("分词器 marisa-trie 已注入，词条 {} 条", len(self.trie_))

    # ------------------------------------------------------------------
    # 预处理
    # ------------------------------------------------------------------

    def _strQ2B(self, ustring: str) -> str:
        """全角字符转半角字符。"""
        rstring = ""
        for uchar in ustring:
            inside_code = ord(uchar)
            if inside_code == 0x3000:
                inside_code = 0x0020
            else:
                inside_code -= 0xFEE0
            if inside_code < 0x0020 or inside_code > 0x7E:
                rstring += uchar
            else:
                rstring += chr(inside_code)
        return rstring

    def _tradi2simp(self, line: str) -> str:
        return HanziConv.toSimplified(line)

    # ------------------------------------------------------------------
    # 词典查询
    # ------------------------------------------------------------------

    def freq(self, tk: str) -> int:
        k = self.key_(tk)
        if k not in self.trie_:
            return 0
        return int(math.exp(self.trie_[k][0]) * DENOMINATOR + 0.5)

    def tag(self, tk: str) -> str:
        k = self.key_(tk)
        if k not in self.trie_:
            return ""
        return self.trie_[k][1]

    # ------------------------------------------------------------------
    # 评分
    # ------------------------------------------------------------------

    def score_(self, tfts: list) -> tuple[list, float]:
        B = 30
        F, L, tks = 0, 0, []
        for tk, (freq_val, _tag) in tfts:
            F += freq_val
            L += 0 if len(tk) < 2 else 1
            tks.append(tk)
        L /= len(tks) if tks else 1
        return tks, B / (len(tks) if tks else 1) + L + F

    def sortTks_(self, tkslist: list) -> list:
        res = []
        for tfts in tkslist:
            tks, s = self.score_(tfts)
            res.append((tks, s))
        return sorted(res, key=lambda x: x[1], reverse=True)

    def merge_(self, tks: str) -> str:
        """若分隔符是词的一部分则合并。"""
        res: list[str] = []
        tokens = re.sub(r"[ ]+", " ", tks).split()
        s = 0
        while s < len(tokens):
            E = s + 1
            for e in range(s + 2, min(len(tokens) + 2, s + 6)):
                tk = "".join(tokens[s:e])
                if _SPLIT_CHAR.search(tk) and self.freq(tk):
                    E = e
            res.append("".join(tokens[s:E]))
            s = E
        return " ".join(res)

    # ------------------------------------------------------------------
    # DFS 分词核心
    # ------------------------------------------------------------------

    def dfs_(
        self,
        chars: list,
        s: int,
        preTks: list,
        tkslist: list,
        _depth: int = 0,
        _memo: dict | None = None,
    ) -> int:
        if _memo is None:
            _memo = {}
        MAX_DEPTH = 10
        if _depth > MAX_DEPTH:
            if s < len(chars):
                copy_pretks = copy.deepcopy(preTks)
                remaining = "".join(chars[s:])
                copy_pretks.append((remaining, (-12, "")))
                tkslist.append(copy_pretks)
            return s

        state_key = (s, tuple(tk[0] for tk in preTks)) if preTks else (s, None)
        if state_key in _memo:
            return _memo[state_key]

        res = s
        if s >= len(chars):
            tkslist.append(preTks)
            _memo[state_key] = s
            return s

        # 连续重复字符（≥5个）
        if s < len(chars) - 4:
            is_repetitive = True
            char_to_check = chars[s]
            for i in range(1, 5):
                if s + i >= len(chars) or chars[s + i] != char_to_check:
                    is_repetitive = False
                    break
            if is_repetitive:
                end = s
                while end < len(chars) and chars[end] == char_to_check:
                    end += 1
                mid = s + min(10, end - s)
                t = "".join(chars[s:mid])
                k = self.key_(t)
                copy_pretks = copy.deepcopy(preTks)
                if k in self.trie_:
                    copy_pretks.append((t, self.trie_[k]))
                else:
                    copy_pretks.append((t, (-12, "")))
                next_res = self.dfs_(chars, mid, copy_pretks, tkslist, _depth + 1, _memo)
                res = max(res, next_res)
                _memo[state_key] = res
                return res

        # 搜索起点优化
        S = s + 1
        if s + 2 <= len(chars):
            t1 = "".join(chars[s : s + 1])
            t2 = "".join(chars[s : s + 2])
            if self.trie_.has_prefix(self.key_(t1)) and not self.trie_.has_prefix(self.key_(t2)):
                S = s + 2
        if len(preTks) > 2 and len(preTks[-1][0]) == 1 and len(preTks[-2][0]) == 1 and len(preTks[-3][0]) == 1:
            t1 = preTks[-1][0] + "".join(chars[s : s + 1])
            if self.trie_.has_prefix(self.key_(t1)):
                S = s + 2

        for e in range(S, len(chars) + 1):
            t = "".join(chars[s:e])
            k = self.key_(t)
            if e > s + 1 and not self.trie_.has_prefix(k):
                break
            if k in self.trie_:
                pretks = copy.deepcopy(preTks)
                pretks.append((t, self.trie_[k]))
                res = max(res, self.dfs_(chars, e, pretks, tkslist, _depth + 1, _memo))

        if res > s:
            _memo[state_key] = res
            return res

        t = "".join(chars[s : s + 1])
        k = self.key_(t)
        copy_pretks = copy.deepcopy(preTks)
        if k in self.trie_:
            copy_pretks.append((t, self.trie_[k]))
        else:
            copy_pretks.append((t, (-12, "")))
        result = self.dfs_(chars, s + 1, copy_pretks, tkslist, _depth + 1, _memo)
        _memo[state_key] = result
        return result

    # ------------------------------------------------------------------
    # 最大匹配
    # ------------------------------------------------------------------

    def maxForward_(self, line: str) -> tuple[list, float]:
        """正向最大匹配。"""
        res: list = []
        s = 0
        while s < len(line):
            e = s + 1
            t = line[s:e]
            while e < len(line) and self.trie_.has_prefix(self.key_(t)):
                e += 1
                t = line[s:e]

            while e - 1 > s and self.key_(t) not in self.trie_:
                e -= 1
                t = line[s:e]

            if self.key_(t) in self.trie_:
                res.append((t, self.trie_[self.key_(t)]))
            else:
                res.append((t, (0, "")))
            s = e
        return self.score_(res)

    def maxBackward_(self, line: str) -> tuple[list, float]:
        """逆向最大匹配。"""
        res: list = []
        s = len(line) - 1
        while s >= 0:
            e = s + 1
            t = line[s:e]
            while s > 0 and self.trie_.has_prefix(self.rkey_(t)):
                s -= 1
                t = line[s:e]

            while s + 1 < e and self.key_(t) not in self.trie_:
                s += 1
                t = line[s:e]

            if self.key_(t) in self.trie_:
                res.append((t, self.trie_[self.key_(t)]))
            else:
                res.append((t, (0, "")))
            s -= 1
        return self.score_(res[::-1])

    # ------------------------------------------------------------------
    # 分词主入口
    # ------------------------------------------------------------------

    def english_normalize_(self, tks: list[str]) -> list[str]:
        return [
            self.stemmer.stem(self.lemmatizer.lemmatize(t))
            if re.match(r"[a-zA-Z_-]+$", t)
            else t
            for t in tks
        ]

    def _split_by_lang(self, line: str) -> list[tuple[str, bool]]:
        txt_lang_pairs: list[tuple[str, bool]] = []
        arr = _SPLIT_CHAR.split(line)
        for a in arr:
            if not a:
                continue
            s = 0
            e = s + 1
            zh = is_chinese(a[s])
            while e < len(a):
                _zh = is_chinese(a[e])
                if _zh == zh:
                    e += 1
                    continue
                txt_lang_pairs.append((a[s:e], zh))
                s = e
                e = s + 1
                zh = _zh
            if s >= len(a):
                continue
            txt_lang_pairs.append((a[s:e], zh))
        return txt_lang_pairs

    def tokenize(self, line: str) -> str:
        """核心分词入口。"""
        line = re.sub(r"\W+", " ", line)
        line = self._strQ2B(line).lower()
        line = self._tradi2simp(line)

        arr = self._split_by_lang(line)
        res: list[str] = []

        for L, lang in arr:
            if not lang:
                for t in word_tokenize(L):
                    if self.key_(t) in self.trie_:
                        res.append(t)
                    else:
                        res.append(self.stemmer.stem(self.lemmatizer.lemmatize(t)))
                continue

            if len(L) < 2 or re.match(r"[a-z\.-]+$", L) or re.match(r"[0-9\.-]+$", L):
                res.append(L)
                continue

            tks, s = self.maxForward_(L)
            tks1, s1 = self.maxBackward_(L)

            # 合并公共前缀
            i, j, _i, _j = 0, 0, 0, 0
            same = 0
            while i + same < len(tks1) and j + same < len(tks) and tks1[i + same] == tks[j + same]:
                same += 1
            if same > 0:
                res.append(" ".join(tks[j : j + same]))
            _i = i + same
            _j = j + same
            j = _j + 1
            i = _i + 1

            # 消歧
            while i < len(tks1) and j < len(tks):
                tk1 = "".join(tks1[_i:i])
                tk = "".join(tks[_j:j])

                if tk1 != tk:
                    if len(tk1) > len(tk):
                        j += 1
                    else:
                        i += 1
                    continue

                if tks1[i] != tks[j]:
                    i += 1
                    j += 1
                    continue

                tkslist: list = []
                self.dfs_("".join(tks[_j:j]), 0, [], tkslist)
                res.append(" ".join(self.sortTks_(tkslist)[0][0]))

                same = 1
                while i + same < len(tks1) and j + same < len(tks) and tks1[i + same] == tks[j + same]:
                    same += 1
                res.append(" ".join(tks[j : j + same]))
                _i = i + same
                _j = j + same
                j = _j + 1
                i = _i + 1

            if _i < len(tks1):
                assert _j < len(tks)
                assert "".join(tks1[_i:]) == "".join(tks[_j:])
                tkslist = []
                self.dfs_("".join(tks[_j:]), 0, [], tkslist)
                res.append(" ".join(self.sortTks_(tkslist)[0][0]))

        res_str = " ".join(res)
        return self.merge_(res_str)

    # ------------------------------------------------------------------
    # 细粒度分词
    # ------------------------------------------------------------------

    def fine_grained_tokenize(self, tks: str) -> str:
        tks_list = tks.split()
        zh_num = len([1 for c in tks_list if c and is_chinese(c[0])])

        if zh_num < len(tks_list) * 0.2:
            res: list[str] = []
            for tk in tks_list:
                res.extend(tk.split("/"))
            return " ".join(res)

        res = []
        for tk in tks_list:
            if len(tk) < 3 or re.match(r"[0-9,\.-]+$", tk):
                res.append(tk)
                continue

            tkslist: list = []
            if len(tk) > 10:
                tkslist.append(tk)
            else:
                self.dfs_(tk, 0, [], tkslist)

            if len(tkslist) < 2:
                res.append(tk)
                continue

            stk = self.sortTks_(tkslist)[1][0]

            if len(stk) == len(tk):
                stk = tk
            else:
                if re.match(r"[a-z\.-]+$", tk):
                    for t in stk:
                        if len(t) < 3:
                            stk = tk
                            break
                    else:
                        stk = " ".join(stk)
                else:
                    stk = " ".join(stk)

            res.append(stk)

        return " ".join(self.english_normalize_(res))


# ------------------------------------------------------------------
# 模块级实例与便捷函数
# ------------------------------------------------------------------

tokenizer = RagTokenizer(debug=True)
tokenize = tokenizer.tokenize
fine_grained_tokenize = tokenizer.fine_grained_tokenize
tag = tokenizer.tag
freq = tokenizer.freq
tradi2simp = tokenizer._tradi2simp
strQ2B = tokenizer._strQ2B
