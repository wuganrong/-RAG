from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text or "")]


def keyword_score(query: str, content: str) -> float:
    q = set(tokenize(query))
    if not q:
        return 0.0
    t = set(tokenize(content))
    return len(q & t) / len(q)
