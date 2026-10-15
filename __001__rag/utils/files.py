"""文件处理工具函数。"""

from __future__ import annotations

# 1. Python 标准库
import hashlib
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager


def get_file_extension(filename: str) -> str | None:
    """从文件名中提取扩展名，返回小写且不包含点。"""
    match = re.search(r"\.([^.]+)$", filename)
    return match.group(1).lower() if match else None


def is_pdf_filename(filename: str) -> bool:
    """判断文件名是否为 PDF。"""
    return (get_file_extension(filename or "") or "").lower() == "pdf"


MINERU_SUPPORTED_EXTENSIONS = frozenset({"pdf", "docx", "pptx", "xlsx"})

MINERU_MIME_TYPES: dict[str, str] = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


def is_mineru_supported_filename(filename: str) -> bool:
    """判断文件名是否为 MinerU 支持的文档类型。"""
    ext = (get_file_extension(filename or "") or "").lower()
    return ext in MINERU_SUPPORTED_EXTENSIONS


def get_mineru_mime_type(filename: str) -> str:
    """根据文件名返回 MinerU 上传用的 MIME 类型。"""
    ext = (get_file_extension(filename or "") or "").lower()
    return MINERU_MIME_TYPES.get(ext, "application/octet-stream")


def ensure_upload_name(filename: str | None, default_ext: str = "pdf") -> str:
    """确保上传给解析服务的文件名带合法扩展名（保留真实后缀）。"""
    upload_name = (filename or f"__003__document.{default_ext}").strip() or f"__003__document.{default_ext}"
    ext = get_file_extension(upload_name)
    if ext and ext.lower() in MINERU_SUPPORTED_EXTENSIONS:
        return upload_name
    if upload_name.lower().endswith(f".{default_ext}"):
        return upload_name
    return f"{upload_name}.{default_ext}"


def sha256_bytes(data: bytes) -> str:
    """计算二进制内容的 SHA256。"""
    return hashlib.sha256(data or b"").hexdigest()


def ensure_pdf_upload_name(filename: str | None) -> str:
    """确保上传给解析服务的文件名带 .pdf 后缀。"""
    upload_name = (filename or "__003__document.pdf").strip() or "__003__document.pdf"
    if not upload_name.lower().endswith(".pdf"):
        upload_name = f"{upload_name}.pdf"
    return upload_name


@contextmanager
def temporary_pdf_file(pdf_bytes: bytes) -> Iterator[str]:
    """将 PDF 二进制写入临时文件，并在退出时清理。"""
    fd, path = tempfile.mkstemp(suffix=".pdf")
    try:
        with os.fdopen(fd, "wb") as tmp:
            tmp.write(pdf_bytes or b"")
        yield path
    finally:
        if os.path.exists(path):
            os.unlink(path)
