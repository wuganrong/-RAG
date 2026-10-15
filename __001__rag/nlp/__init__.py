"""NLP 模块 —— 中文分词、词权重、同义词、全文检索查询构建。

数据由 NLPData.load() 统一提供。
"""

from __001__rag.nlp.tokenizer import (  # noqa: F401
    fine_grained_tokenize,
    freq,
    strQ2B,
    tag,
    tokenize,
    tokenizer,
    tradi2simp,
)
from __001__rag.nlp.term_weight import Dealer as TermWeightDealer  # noqa: F401
from __001__rag.nlp.synonym import Dealer as SynonymDealer  # noqa: F401
from __001__rag.nlp.query import FulltextQueryer  # noqa: F401
