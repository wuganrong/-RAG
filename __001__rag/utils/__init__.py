"""项目通用工具函数，供所有 app 复用。"""

from __future__ import annotations

# 3. 本地应用
from __001__rag.utils.context import get_trace_id, set_trace_id
from __001__rag.utils.db import check_duplicate_name
from __001__rag.utils.files import (
    ensure_pdf_upload_name,
    ensure_upload_name,
    get_file_extension,
    get_mineru_mime_type,
    is_mineru_supported_filename,
    is_pdf_filename,
    sha256_bytes,
)
from __001__rag.utils.ids import get_numeric_id, get_uuid
from __001__rag.utils.redis import redis_json_dumps, redis_json_loads
from __001__rag.utils.responses import error_response, success_response
from __001__rag.utils.time import format_datetime

__all__ = [
    "check_duplicate_name",
    "ensure_pdf_upload_name",
    "ensure_upload_name",
    "get_file_extension",
    "get_mineru_mime_type",
    "get_trace_id",
    "is_mineru_supported_filename",
    "is_pdf_filename",
    "set_trace_id",
    "sha256_bytes",
    "get_numeric_id",
    "get_uuid",
    "redis_json_dumps",
    "redis_json_loads",
    "error_response",
    "success_response",
    "format_datetime",
]
