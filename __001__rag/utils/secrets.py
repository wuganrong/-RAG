"""API Key 兼容式保护工具。"""

from __future__ import annotations

from django.core import signing

_PREFIX = "signed:"


def protect_secret(value: str | None) -> str:
    if not value:
        return ""
    if value.startswith(_PREFIX):
        return value
    return _PREFIX + signing.dumps(value)


def reveal_secret(value: str | None) -> str:
    if not value:
        return ""
    if not value.startswith(_PREFIX):
        return value
    try:
        return signing.loads(value[len(_PREFIX):])
    except signing.BadSignature:
        return ""
