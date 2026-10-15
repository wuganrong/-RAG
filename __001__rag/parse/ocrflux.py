"""OCRFlux API PDF -> Markdown 解析器。"""

from __future__ import annotations

# 1. Python 标准库
import base64
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

# 2. 第三方库
import requests
from django.conf import settings
from loguru import logger

# 3. 本地应用
from __001__rag.models import DocToMarkdownCache
from __001__rag.parse.base import BaseParser, ParsedDocument, ParsedElement, ParserContext
from __001__rag.utils import ensure_pdf_upload_name, get_numeric_id, is_pdf_filename, sha256_bytes

PARSE_METHOD_OCRFLUX = "ocrflux"
ProgressCallback = Callable[[float, str], None]


class OCRFluxParser(BaseParser):
    """通过 OCRFlux HTTP API 将 PDF 解析为 Markdown。"""

    parser_id = "use_ocrflux"

    def __init__(
        self,
        api_url: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.api_url = (api_url or getattr(settings, "OCRFLUX_API_URL", "")).strip()
        self.timeout = timeout if timeout is not None else int(getattr(settings, "OCRFLUX_REQUEST_TIMEOUT", 300))
        self.max_retries = max_retries if max_retries is not None else int(getattr(settings, "OCRFLUX_MAX_RETRIES", 3))
        user_agent = getattr(settings, "OCRFLUX_USER_AGENT", "YF-RAG-OCRFlux-Client/1.0")
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": user_agent,
            }
        )

    def supports(self, filename: str, content_type: str | None = None) -> bool:
        """OCRFlux 当前仅支持 PDF。"""
        return is_pdf_filename(filename) or content_type == "application/pdf"

    def parse(self, file_bytes: bytes, context: ParserContext) -> ParsedDocument:
        """解析 PDF 字节为 Markdown 文档。"""
        callback = _get_callback(context)
        logger.info(
            "OCRFlux 开始解析文档 doc_id={} filename={} bytes={} api_url={}",
            context.doc_id,
            context.filename,
            len(file_bytes or b""),
            self.api_url,
        )
        markdown_content = self.pdf_binary_to_markdown_no_split(
            file_bytes,
            doc_id=context.doc_id,
            file_name=context.filename,
            callback=callback,
            skip_cross_page_merge=bool(context.config.get("skip_cross_page_merge", False)),
            max_page_retries=int(context.config.get("max_page_retries") or getattr(settings, "OCRFLUX_MAX_PAGE_RETRIES", 3)),
            target_longest_image_dim=int(context.config.get("target_longest_image_dim") or getattr(settings, "OCRFLUX_TARGET_LONGEST_IMAGE_DIM", 1024)),
        )
        logger.info(
            "OCRFlux 文档解析完成 doc_id={} filename={} markdown_chars={}",
            context.doc_id,
            context.filename,
            len(markdown_content),
        )
        return ParsedDocument(
            doc_id=context.doc_id,
            filename=context.filename,
            elements=[
                ParsedElement(
                    content=markdown_content,
                    element_type="markdown",
                    metadata={"parse_method": PARSE_METHOD_OCRFLUX},
                )
            ],
            metadata={"parse_method": PARSE_METHOD_OCRFLUX},
        )

    def pdf_binary_to_markdown_no_split(
        self,
        pdf_binary: bytes,
        doc_id: str | None = None,
        file_name: str | None = None,
        callback: ProgressCallback | None = None,
        skip_cross_page_merge: bool = False,
        max_page_retries: int | None = None,
        target_longest_image_dim: int | None = None,
    ) -> str:
        """整份 PDF 二进制直接提交 OCRFlux，并按 sha256 做 Markdown 缓存。"""
        callback = callback or _noop_callback
        if not self.api_url:
            raise ValueError("OCRFLUX_API_URL 不能为空")

        _max_page_retries = max_page_retries if max_page_retries is not None else int(getattr(settings, "OCRFLUX_MAX_PAGE_RETRIES", 3))
        _target_dim = target_longest_image_dim if target_longest_image_dim is not None else int(getattr(settings, "OCRFLUX_TARGET_LONGEST_IMAGE_DIM", 1024))

        pdf_sha256 = sha256_bytes(pdf_binary)
        logger.info(
            "OCRFlux 准备解析 PDF doc_id={} filename={} sha256={} bytes={}",
            doc_id,
            file_name,
            pdf_sha256,
            len(pdf_binary or b""),
        )
        cached = self._get_cached_markdown(pdf_sha256)
        if cached:
            logger.info("OCRFlux 命中 Markdown 缓存 doc_id={} filename={} sha256={} chars={}", doc_id, file_name, pdf_sha256, len(cached))
            callback(0.2, "OCRFlux 命中 Markdown 缓存")
            return cached

        logger.info("OCRFlux 未命中 Markdown 缓存，准备调用 API doc_id={} filename={} sha256={}", doc_id, file_name, pdf_sha256)
        callback(0.3, "调用 OCRFlux API")
        markdown_content = self._call_api(
            pdf_binary=pdf_binary,
            file_name=ensure_pdf_upload_name(file_name),
            callback=callback,
            skip_cross_page_merge=skip_cross_page_merge,
            max_page_retries=_max_page_retries,
            target_longest_image_dim=_target_dim,
        )
        self._save_markdown_cache(
            pdf_sha256=pdf_sha256,
            markdown_content=markdown_content,
            doc_id=doc_id,
            file_name=file_name,
            size_bytes=len(pdf_binary or b""),
        )
        logger.info(
            "OCRFlux Markdown 结果已生成 doc_id={} filename={} sha256={} chars={}",
            doc_id,
            file_name,
            pdf_sha256,
            len(markdown_content),
        )
        callback(0.9, "OCRFlux 解析完成")
        return markdown_content

    def _call_api(
        self,
        *,
        pdf_binary: bytes,
        file_name: str,
        callback: ProgressCallback,
        skip_cross_page_merge: bool,
        max_page_retries: int,
        target_longest_image_dim: int,
    ) -> str:
        if not isinstance(skip_cross_page_merge, bool):
            raise ValueError("skip_cross_page_merge 必须为 boolean")
        if max_page_retries < 1:
            raise ValueError("max_page_retries 必须 >= 1")
        if target_longest_image_dim < 1:
            raise ValueError("target_longest_image_dim 必须 >= 1")

        payload = {
            "file_base64": base64.b64encode(pdf_binary or b"").decode("utf-8"),
            "filename": file_name,
            "skip_cross_page_merge": skip_cross_page_merge,
            "max_page_retries": max_page_retries,
            "target_longest_image_dim": target_longest_image_dim,
        }

        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                logger.info(
                    "OCRFlux API 请求开始 filename={} attempt={}/{} bytes={} skip_cross_page_merge={} max_page_retries={} target_longest_image_dim={}",
                    file_name,
                    attempt + 1,
                    self.max_retries,
                    len(pdf_binary or b""),
                    skip_cross_page_merge,
                    max_page_retries,
                    target_longest_image_dim,
                )
                callback(0.35 + attempt * 0.1, f"调用 OCRFlux API ({attempt + 1}/{self.max_retries})")
                response = self.session.post(self.api_url, json=payload, timeout=self.timeout)
                if response.status_code == 200:
                    markdown = self._extract_markdown_response(response.json())
                    logger.info(
                        "OCRFlux API 请求成功 filename={} attempt={}/{} markdown_chars={}",
                        file_name,
                        attempt + 1,
                        self.max_retries,
                        len(markdown),
                    )
                    return markdown
                if response.status_code == 429 and attempt < self.max_retries - 1:
                    wait_seconds = int(getattr(settings, "OCRFLUX_RETRY_BACKOFF_BASE", 2)) ** attempt
                    logger.info(
                        "OCRFlux API 请求被限流，准备重试 filename={} attempt={}/{} wait_seconds={}",
                        file_name,
                        attempt + 1,
                        self.max_retries,
                        wait_seconds,
                    )
                    callback(0.5, f"OCRFlux 请求限流，{wait_seconds}s 后重试")
                    time.sleep(wait_seconds)
                    continue
                logger.info(
                    "OCRFlux API 请求失败 filename={} attempt={}/{} status_code={} response={}",
                    file_name,
                    attempt + 1,
                    self.max_retries,
                    response.status_code,
                    response.text[:500],
                )
                raise RuntimeError(f"OCRFlux API 请求失败: HTTP {response.status_code} - {response.text[:500]}")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    logger.info(
                        "OCRFlux API 连接异常，准备重试 filename={} attempt={}/{} error={}",
                        file_name,
                        attempt + 1,
                        self.max_retries,
                        exc,
                    )
                    callback(0.5, f"OCRFlux 连接异常，重试 {attempt + 1}/{self.max_retries}")
                    time.sleep(int(getattr(settings, "OCRFLUX_RETRY_BACKOFF_BASE", 2)) ** attempt)
                    continue
                logger.info("OCRFlux API 连接异常且重试耗尽 filename={} error={}", file_name, exc)
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    logger.info(
                        "OCRFlux API 请求异常，准备重试 filename={} attempt={}/{} error={}",
                        file_name,
                        attempt + 1,
                        self.max_retries,
                        exc,
                    )
                    callback(0.5, f"OCRFlux 请求失败，重试 {attempt + 1}/{self.max_retries}: {exc}")
                    time.sleep(int(getattr(settings, "OCRFLUX_RETRY_BACKOFF_BASE", 2)) ** attempt)
                    continue
                logger.info("OCRFlux API 请求异常且重试耗尽 filename={} error={}", file_name, exc)
                raise
        if last_error:
            raise last_error
        raise RuntimeError("OCRFlux API 调用失败")

    @staticmethod
    def _extract_markdown_response(payload: dict[str, Any]) -> str:
        if not payload.get("success", False):
            raise RuntimeError(f"OCRFlux API 返回错误: {payload.get('error', '未知错误')}")
        data = payload.get("data") or {}
        if not isinstance(data, dict):
            raise RuntimeError("OCRFlux API data 字段不是对象")
        markdown_content = (data.get("document_text") or "").strip()
        if not markdown_content:
            raise RuntimeError("OCRFlux API 返回空 Markdown")
        return markdown_content

    def _get_cached_markdown(self, pdf_sha256: str) -> str | None:
        try:
            row = (
                DocToMarkdownCache.objects.filter(
                    pdf_sha256=pdf_sha256,
                    parse_method=PARSE_METHOD_OCRFLUX,
                    status="1",
                )
                .order_by("-create_date")
                .first()
            )
        except Exception:
            logger.info("OCRFlux Markdown 缓存查询失败 sha256={}", pdf_sha256)
            return None
        logger.info("OCRFlux Markdown 缓存查询完成 sha256={} hit={}", pdf_sha256, row is not None)
        return row.markdown_content if row else None

    def _save_markdown_cache(
        self,
        *,
        pdf_sha256: str,
        markdown_content: str,
        doc_id: str | None,
        file_name: str | None,
        size_bytes: int,
    ) -> DocToMarkdownCache | None:
        try:
            now = datetime.now()
            row, _ = DocToMarkdownCache.objects.update_or_create(
                pdf_sha256=pdf_sha256,
                create_defaults={
                    "id": str(get_numeric_id()),
                    "markdown_content": markdown_content,
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "size_bytes": size_bytes,
                    "parse_method": PARSE_METHOD_OCRFLUX,
                    "status": "1",
                    "create_date": now,
                    "update_date": now,
                },
                defaults={
                    "markdown_content": markdown_content,
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "size_bytes": size_bytes,
                    "parse_method": PARSE_METHOD_OCRFLUX,
                    "status": "1",
                    "update_date": now,
                },
            )
            logger.info(
                "OCRFlux Markdown 缓存保存完成 doc_id={} filename={} sha256={} chars={} size_bytes={}",
                doc_id,
                file_name,
                pdf_sha256,
                len(markdown_content),
                size_bytes,
            )
            return row
        except Exception:
            logger.info("OCRFlux Markdown 缓存保存失败 doc_id={} filename={} sha256={}", doc_id, file_name, pdf_sha256)
            return None


def _get_callback(context: ParserContext) -> ProgressCallback:
    callback = context.config.get("callback")
    return callback if callable(callback) else _noop_callback


def _noop_callback(progress: float, message: str) -> None:
    return None
