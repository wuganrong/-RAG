"""全文检索查询构建 —— IDF 权重 + 同义词扩展 + 细粒度分词。

FulltextQueryer.question() 用 IDF 权重 + 同义词扩展 + 细粒度分词
构建带权重的 ES query_string 表达式，替代 LLM 关键词提取。
"""

from __future__ import annotations

# 1. Python 标准库
import json
import re

# 2. 第三方库
from loguru import logger

# 3. 本地应用
from __001__rag.nlp.synonym import Dealer as SynonymDealer
from __001__rag.nlp.term_weight import Dealer as TermWeightDealer
from __001__rag.nlp.tokenizer import fine_grained_tokenize, strQ2B, tokenize, tradi2simp
from __001__rag.search.base import MatchTextExpr


class FulltextQueryer:
    """全文检索查询构建器。"""

    def __init__(self, tw: TermWeightDealer | None = None, syn: SynonymDealer | None = None):
        self.tw = tw or TermWeightDealer()
        self.syn = syn or SynonymDealer()
        self.query_fields = [
            "title_tks^10",
            "title_sm_tks^5",
            "important_kwd^30",
            "important_tks^20",
            "question_tks^20",
            "content_ltks^2",
            "content_sm_ltks",
        ]

    @staticmethod
    def subSpecialChar(line: str) -> str:
        return re.sub(r"([:\{\}/\[\]\-\*\"\(\)\|\+~\^])", r"\\\1", line).strip()

    @staticmethod
    def isChinese(line: str) -> bool:
        arr = re.split(r"[ \t]+", line)
        if len(arr) <= 3:
            return True
        e = 0
        for t in arr:
            if not re.match(r"[a-zA-Z]+$", t):
                e += 1
        return e * 1.0 / len(arr) >= 0.7

    @staticmethod
    def rmWWW(txt: str) -> str:
        patts = [
            (
                r"是*(什么样的|哪家|一下|那家|请问|啥样|咋样了|什么时候|何时|何地|何人|是否|是不是|多少|哪里|怎么|哪儿|怎么样|如何|哪些|是啥|啥是|啊|吗|呢|吧|咋|什么|有没有|呀|谁|哪位|哪个)是*",
                "",
            ),
            (r"(^| )(what|who|how|which|where|why)('re|'s)? ", " "),
            (
                r"(^| )('s|'re|is|are|were|was|do|does|did|don't|doesn't|didn't|has|have|be|there|you|me|your|my|mine|just|please|may|i|should|would|wouldn't|will|won't|done|go|for|with|so|the|a|an|by|i'm|it's|he's|she's|they|they're|you're|as|by|on|in|at|up|out|down|of|to|or|and|if) ",
                " ",
            ),
        ]
        otxt = txt
        for r, p in patts:
            txt = re.sub(r, p, txt, flags=re.IGNORECASE)
        if not txt:
            txt = otxt
        return txt

    def question(
        self, txt: str, tbl: str = "qa", min_match: float = 0.6
    ) -> tuple[MatchTextExpr | None, list[str]]:
        """处理用户问题，返回 (MatchTextExpr, 关键词列表)。"""
        # 预处理
        txt = re.sub(
            r"[ :|\r\n\t,，。？?/`!！&^%%()\[\]{}<>]+",
            " ",
            tradi2simp(strQ2B(txt.lower())),
        ).strip()
        txt = FulltextQueryer.rmWWW(txt)

        # ---- 非中文分支 ----
        if not self.isChinese(txt):
            txt = FulltextQueryer.rmWWW(txt)
            tks = tokenize(txt).split()
            keywords = [t for t in tks if t]
            tks_w = self.tw.weights(tks, preprocess=False)
            tks_w = [(re.sub(r"[ \\\"'^]", "", tk), w) for tk, w in tks_w]
            tks_w = [(re.sub(r"^[a-z0-9]$", "", tk), w) for tk, w in tks_w if tk]
            tks_w = [(re.sub(r"^[\+-]", "", tk), w) for tk, w in tks_w if tk]
            tks_w = [(tk.strip(), w) for tk, w in tks_w if tk.strip()]

            syns: list[str] = []
            for tk, w in tks_w[:256]:
                syn = self.syn.lookup(tk)
                syn = tokenize(" ".join(syn)).split()
                keywords.extend(syn)
                syn = ['"{}"^{:.4f}'.format(s, w / 4.0) for s in syn if s.strip()]
                syns.append(" ".join(syn))

            q = [
                "({}^{:.4f}".format(tk, w) + " {})".format(syn)
                for (tk, w), syn in zip(tks_w, syns)
                if tk and not re.match(r"[.^+\(\)-]", tk)
            ]
            for i in range(1, len(tks_w)):
                left, right = tks_w[i - 1][0].strip(), tks_w[i][0].strip()
                if not left or not right:
                    continue
                q.append(
                    '"%s %s"^%.4f'
                    % (tks_w[i - 1][0], tks_w[i][0], max(tks_w[i - 1][1], tks_w[i][1]) * 2)
                )
            if not q:
                q.append(txt)
            query = " ".join(q)
            return (
                MatchTextExpr(self.query_fields, query, 100),
                keywords,
            )

        # ---- 中文分支 ----
        def need_fine_grained_tokenize(tk: str) -> bool:
            if len(tk) < 3:
                return False
            if re.match(r"[0-9a-z\.\+#_\*-]+$", tk):
                return False
            return True

        txt = FulltextQueryer.rmWWW(txt)
        qs: list[str] = []
        keywords: list[str] = []

        for tt in self.tw.split(txt)[:256]:
            if not tt:
                continue
            keywords.append(tt)
            twts = self.tw.weights([tt])

            syns = self.syn.lookup(tt)
            if syns and len(keywords) < 32:
                keywords.extend(syns)
            logger.info(json.dumps(twts, ensure_ascii=False))
            tms: list[tuple[str, float]] = []

            for tk, w in sorted(twts, key=lambda x: x[1] * -1):
                sm = (
                    fine_grained_tokenize(tk).split()
                    if need_fine_grained_tokenize(tk)
                    else []
                )
                sm = [
                    re.sub(
                        r"[ ,\./;'\[\]\\`~!@#$%\^&\*\(\)=\+_<>\?:\"\{\}\|，。；‘’【】、！￥……（）——《》？：“”-]+",
                        "",
                        m,
                    )
                    for m in sm
                ]
                sm = [FulltextQueryer.subSpecialChar(m) for m in sm if len(m) > 1]
                sm = [m for m in sm if len(m) > 1]

                if len(keywords) < 32:
                    keywords.append(re.sub(r"[ \\\"']+", "", tk))
                    keywords.extend(sm)

                tk_syns = self.syn.lookup(tk)
                tk_syns = [FulltextQueryer.subSpecialChar(s) for s in tk_syns]
                if len(keywords) < 32:
                    keywords.extend([s for s in tk_syns if s])
                tk_syns = [f'"{s}"' if s.find(" ") > 0 else s for s in tk_syns]

                if len(keywords) >= 32:
                    break

                tk_esc = FulltextQueryer.subSpecialChar(tk)
                if tk_esc.find(" ") > 0:
                    tk_esc = '"%s"' % tk_esc
                if tk_syns:
                    tk_esc = f"({tk_esc} OR (%s)^0.2)" % " ".join(tk_syns)
                if sm:
                    tk_esc = f'{tk_esc} OR "%s" OR ("%s"~2)^0.5' % (" ".join(sm), " ".join(sm))
                if tk_esc.strip():
                    tms.append((tk_esc, w))

            tms_str = " ".join([f"({t})^{w}" for t, w in tms])

            if len(twts) > 1:
                tms_str += ' ("%s"~2)^1.5' % tokenize(tt)

            syns_str = " OR ".join(
                [
                    '"%s"' % tokenize(FulltextQueryer.subSpecialChar(s))
                    for s in syns
                ]
            )
            if syns_str and tms_str:
                tms_str = f"({tms_str})^5 OR ({syns_str})^0.7"

            qs.append(tms_str)

        if qs:
            query = " OR ".join([f"({t})" for t in qs if t])
            logger.info(f"es 最终查询表达式: {query}")
            return (
                MatchTextExpr(
                    self.query_fields,
                    query,
                    100,
                    {"minimum_should_match": min_match},
                ),
                keywords,
            )
        return None, keywords


# 模块级单例，由 init_nlp() 初始化
queryer: FulltextQueryer | None = None
