"""Markdown 与解析图片处理工具。"""

from __future__ import annotations

# 1. Python 标准库
import base64
import re
from typing import Match

_IMG_REF_RE = re.compile(r"images/([A-Za-z0-9._-]+\.(?:png|jpe?g|webp|gif))", re.IGNORECASE)
_MD_IMG_RE = re.compile(r"!\[([^\]]*)\]\(\s*(images/[^\)\s\"']+)\s*\)")
_PAREN_IMG_RE = re.compile(r"\(\s*(images/[^\)\s\"']+)\s*\)")


def extract_markdown_image_names(markdown_content: str) -> set[str]:
    """从 Markdown 中提取 `images/<name>` 引用的图片文件名。"""
    return {match.group(1) for match in _IMG_REF_RE.finditer(markdown_content or "")}


def extract_base64_content(image_raw: str) -> str:
    """提取普通 base64 或 data URL 中的 base64 正文。"""
    text = (image_raw or "").strip()
    if text.startswith("data:"):
        _, _, text = text.partition(",")
    return text.strip()


def decode_base64_image(image_raw: str) -> bytes:
    """解码普通 base64 或 data URL 图片。"""
    text = extract_base64_content(image_raw)
    return base64.b64decode(text) if text else b""


def build_document_image_url(bucket: str, key: str) -> str:
    """构造文档图片接口 URL。"""
    return f"/carbody-ai/document/image/{bucket}-{key}"


def replace_markdown_image_paths(markdown_content: str, image_url_map: dict[str, str]) -> str:
    """将 Markdown 中的 `images/<key>` 路径替换为文档图片接口 URL。"""
    if not markdown_content or not image_url_map:
        return markdown_content

    def replace_image_path(match: Match[str]) -> str:
        key = match.group(1)
        return image_url_map.get(key) or image_url_map.get(f"images/{key}") or match.group(0)

    return _IMG_REF_RE.sub(replace_image_path, markdown_content)


def replace_markdown_images_to_html(markdown_content: str, image_url_map: dict[str, str]) -> str:
    """将 Markdown 中命中的本地图片引用替换成可访问的 HTML 图片标签。"""
    if not markdown_content or not image_url_map:
        return markdown_content

    def replace_md_image(match: Match[str]) -> str:
        alt = (match.group(1) or "").strip()
        path = (match.group(2) or "").strip()
        key = path.split("/")[-1]
        url = image_url_map.get(key)
        if not url:
            return match.group(0)
        alt_attr = f' alt="{alt}"' if alt else ""
        return f'<img src="{url}"{alt_attr} />'

    def replace_paren_image(match: Match[str]) -> str:
        path = (match.group(1) or "").strip()
        key = path.split("/")[-1]
        url = image_url_map.get(key)
        if not url:
            return match.group(0)
        return f'(<img src="{url}" data-image-key="{key}" alt="{key}" />)'

    out = _MD_IMG_RE.sub(replace_md_image, markdown_content)
    return _PAREN_IMG_RE.sub(replace_paren_image, out)
