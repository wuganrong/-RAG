"""MinerU API 文档（PDF/DOCX/PPTX/XLSX）-> Markdown 解析器。"""

from __future__ import annotations

# 1. Python 标准库
import hashlib
import json
import re
import threading
import time
from collections.abc import Callable
from datetime import datetime
from typing import Any

# 2. 第三方库
import requests
from django.conf import settings
from django.db import transaction
from loguru import logger

# 3. 本地应用
from __001__rag.models import DocImagesCache, DocToMarkdownCache
from __001__rag.parse.base import BaseParser, ParsedDocument, ParsedElement, ParserContext
from __001__rag.parse.utils.markdown import (
    build_document_image_url,
    decode_base64_image,
    extract_base64_content,
    extract_markdown_image_names,
    replace_markdown_images_to_html,
)
from __001__rag.storage import minio_service
from __001__rag.storage.minio_service import MinioService
from __001__rag.utils import ensure_upload_name, get_mineru_mime_type, get_numeric_id, get_uuid, is_mineru_supported_filename, sha256_bytes
from __001__rag.utils.files import MINERU_MIME_TYPES

PARSE_METHOD_MINERU = "mineru"
ProgressCallback = Callable[[float, str], None]

_IMG_KEY_PATTERN = re.compile(r"images/([A-Za-z0-9._-]+\.(?:png|jpe?g|webp|gif))", re.IGNORECASE)
_mineru_api_semaphore: threading.BoundedSemaphore | None = None
_mineru_api_semaphore_lock = threading.Lock()


class MinerUParser(BaseParser):
    """通过 MinerU `/file_parse` API 将 PDF/DOCX/PPTX/XLSX 解析为 Markdown。"""

    parser_id = "mineru"

    def __init__(
        self,
        api_url: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        session: requests.Session | None = None,
        storage_service: MinioService | None = None,
    ) -> None:
        self.api_url = (api_url or getattr(settings, "MINERU_FILE_PARSE_URL", "")).strip().rstrip("/")
        self.timeout = timeout if timeout is not None else int(getattr(settings, "MINERU_REQUEST_TIMEOUT", 1200))
        self.max_retries = max_retries if max_retries is not None else int(getattr(settings, "MINERU_MAX_RETRIES", 3))
        user_agent = getattr(settings, "MINERU_USER_AGENT", "YF-RAG-MinerU-Client/1.0")
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        self.storage_service = storage_service or minio_service

    def supports(self, filename: str, content_type: str | None = None) -> bool:
        """MinerU 支持 PDF、DOCX、PPTX、XLSX。"""
        if is_mineru_supported_filename(filename):
            return True
        if content_type:
            return content_type in set(MINERU_MIME_TYPES.values())
        return False

    def parse(self, file_bytes: bytes, context: ParserContext) -> ParsedDocument:
        """解析文档字节为 Markdown。"""
        callback = _get_callback(context)
        parser_result = self.file_binary_to_markdown_no_split(
            file_bytes,
            doc_id=context.doc_id,
            file_name=context.filename,
            callback=callback,
        )
        raw_response = parser_result.get("raw_response") or ""
        markdown_content = self.extract_mineru_markdown(raw_response)
        image_url_map = parser_result.get("image_url_map") or {}
        markdown_content = replace_markdown_images_to_html(markdown_content, image_url_map)
        return ParsedDocument(
            doc_id=context.doc_id,
            filename=context.filename,
            elements=[
                ParsedElement(
                    content=markdown_content,
                    element_type="markdown",
                    metadata={
                        "parse_method": PARSE_METHOD_MINERU,
                        "cache_id": parser_result.get("cache_id"),
                        "image_count": len(image_url_map),
                    },
                )
            ],
            metadata={
                "parse_method": PARSE_METHOD_MINERU,
                "cache_id": parser_result.get("cache_id"),
                "image_url_map": image_url_map,
            },
        )

    def file_binary_to_markdown_no_split(
        self,
        file_binary: bytes,
        doc_id: str | None = None,
        file_name: str | None = None,
        callback: ProgressCallback | None = None,
    ) -> dict[str, Any]:
        """整份文档二进制提交 MinerU，并缓存瘦身后的原始响应。"""
        callback = callback or _noop_callback
        if not self.api_url:
            raise ValueError("MINERU_FILE_PARSE_URL 不能为空")

        file_sha256 = sha256_bytes(file_binary)
        cached = self._get_cached_response(file_sha256)
        if cached:
            callback(0.2, "MinerU 命中 Markdown 缓存")
            return {
                "cache_id": cached.id,
                "raw_response": cached.markdown_content,
                "image_url_map": self._load_image_url_map(cached.markdown_content),
            }

        upload_name = ensure_upload_name(file_name)
        sem = _get_mineru_api_semaphore()
        sem.acquire()
        try:
            callback(0.1, "MinerU 上传文档解析")
            response_body = self._post_file_parse(
                file_binary=file_binary,
                upload_name=upload_name,
                callback=callback,
            )
            response_body, image_rows, image_url_map = self._normalize_payload_and_collect_images(
                response_body=response_body,
                callback=callback,
            )
            cache_id = get_numeric_id()
            self._save_cache_and_images(
                cache_id=cache_id,
                pdf_sha256=file_sha256,
                response_body=response_body,
                image_rows=image_rows,
                doc_id=doc_id,
                file_name=file_name,
                size_bytes=len(file_binary or b""),
            )
            callback(0.9, "MinerU 解析完成")
            return {"cache_id": str(cache_id), "raw_response": response_body, "image_url_map": image_url_map}
        finally:
            sem.release()

    def _post_file_parse(self, file_binary: bytes, upload_name: str, callback: ProgressCallback) -> str:
        content_type = get_mineru_mime_type(upload_name)
        files = [("files", (upload_name, file_binary, content_type))]
        _return_images = "true" if getattr(settings, "MINERU_RETURN_IMAGES", True) else "false"
        _backend = getattr(settings, "MINERU_PARSE_BACKEND", "vlm-auto-engine")
        data = {"return_images": _return_images, "backend": _backend}
        last_error: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                callback(0.3 + attempt * 0.05, f"调用 MinerU file_parse ({attempt + 1}/{self.max_retries})")
                response = self.session.post(
                    self.api_url,
                    files=files,
                    data=data,
                    timeout=self.timeout,
                )
                if response.status_code == 200:
                    raw = (response.text or "").strip()
                    if raw:
                        return raw
                    raise RuntimeError("MinerU 返回空正文")
                _backoff_base = int(getattr(settings, "MINERU_RETRY_BACKOFF_BASE", 2))
                if response.status_code == 429 and attempt < self.max_retries - 1:
                    wait_seconds = _backoff_base**attempt
                    callback(0.5, f"MinerU 请求限流，{wait_seconds}s 后重试")
                    time.sleep(wait_seconds)
                    continue
                raise RuntimeError(f"MinerU API 请求失败: HTTP {response.status_code} - {response.text[:500]}")
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    _backoff_base = int(getattr(settings, "MINERU_RETRY_BACKOFF_BASE", 2))
                    callback(0.5, f"MinerU 连接异常，重试 {attempt + 1}/{self.max_retries}")
                    time.sleep(_backoff_base**attempt)
                    continue
                raise
            except Exception as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    _backoff_base = int(getattr(settings, "MINERU_RETRY_BACKOFF_BASE", 2))
                    callback(0.5, f"MinerU 请求失败，重试 {attempt + 1}/{self.max_retries}: {exc}")
                    time.sleep(_backoff_base**attempt)
                    continue
                raise
        if last_error:
            raise last_error
        raise RuntimeError("MinerU API 调用失败")

    def _normalize_payload_and_collect_images(
        self,
        response_body: str,
        callback: ProgressCallback,
    ) -> tuple[str, list[dict[str, Any]], dict[str, str]]:
        """缩短图片 key、上传被 Markdown 引用的图片，并移除 payload 中的 images。"""
        payload = json.loads(response_body or "{}")
        results = payload.get("results")
        if not isinstance(results, dict):
            return response_body, [], {}

        image_payload: dict[str, dict[str, str]] = {}
        used_image_keys: set[str] = set()
        for item in results.values():
            if not isinstance(item, dict):
                continue
            images = item.get("images")
            old_to_new: dict[str, str] = {}
            new_images: dict[str, str] = {}
            if isinstance(images, dict):
                for old_key, value in images.items():
                    if not isinstance(old_key, str) or not old_key:
                        continue
                    short_key = f"{hashlib.blake2b(old_key.encode('utf-8'), digest_size=8).hexdigest()}.jpg"
                    old_to_new[old_key] = short_key
                    new_images[short_key] = value

            if isinstance(item.get("md_content"), str) and old_to_new:
                item["md_content"] = _IMG_KEY_PATTERN.sub(
                    lambda match: f"images/{old_to_new[match.group(1)]}"
                    if match.group(1) in old_to_new
                    else match.group(0),
                    item["md_content"],
                )

            for key in extract_markdown_image_names(item.get("md_content") or ""):
                raw = new_images.get(key)
                if not raw:
                    continue
                image_payload[key] = {
                    "image_key": key,
                    "image_data": extract_base64_content(raw),
                    "bucket": getattr(settings, "MINERU_IMAGES_BUCKET", "mineru"),
                }
                used_image_keys.add(key)

            item.pop("images", None)

        existing_remote_map = self._get_existing_remote_url_map(used_image_keys)
        image_rows: list[dict[str, Any]] = []
        image_url_map: dict[str, str] = {}
        total = len(image_payload)
        for idx, key in enumerate(sorted(image_payload)):
            row = image_payload[key]
            bucket = self.storage_service.normalize_bucket(row.get("bucket") or getattr(settings, "MINERU_IMAGES_BUCKET", "mineru"))
            remote_url = existing_remote_map.get(key)
            if not remote_url:
                binary = decode_base64_image(row.get("image_data") or "")
                if not binary:
                    continue
                self.storage_service.put(bucket, key, binary, content_type="image/jpeg")
                remote_url = build_document_image_url(bucket, key)
                callback(0.72 + 0.18 * ((idx + 1) / total) if total else 0.9, f"MinerU 上传图片 {idx + 1}/{total}")
            else:
                callback(0.72 + 0.18 * ((idx + 1) / total) if total else 0.9, f"MinerU 复用图片 {idx + 1}/{total}")

            row["bucket"] = bucket
            row["remote_url"] = remote_url
            image_url_map[key] = remote_url
            image_rows.append(row)

        return json.dumps(payload, ensure_ascii=False), image_rows, image_url_map

    @staticmethod
    def extract_mineru_markdown(raw_response: str) -> str:
        """从 MinerU JSON 响应中提取第一个 `md_content`。"""
        payload = json.loads(raw_response or "{}")
        results = payload.get("results")
        if not isinstance(results, dict) or not results:
            raise ValueError("MinerU 响应中缺少有效 results")
        item = next(iter(results.values()))
        if not isinstance(item, dict):
            raise ValueError("MinerU results 条目不是对象")
        markdown_content = (item.get("md_content") or "").strip()
        if not markdown_content:
            raise ValueError("MinerU 返回空 md_content")
        return markdown_content

    def _get_cached_response(self, pdf_sha256: str) -> DocToMarkdownCache | None:
        try:
            return (
                DocToMarkdownCache.objects.filter(
                    pdf_sha256=pdf_sha256,
                    parse_method=PARSE_METHOD_MINERU,
                    status="1",
                )
                .order_by("-create_date")
                .first()
            )
        except Exception:
            logger.info("MinerU Markdown 缓存查询失败")
            return None

    def _save_cache_and_images(
        self,
        *,
        cache_id: int,
        pdf_sha256: str,
        response_body: str,
        image_rows: list[dict[str, Any]],
        doc_id: str | None,
        file_name: str | None,
        size_bytes: int,
    ) -> None:
        try:
            now = datetime.now()
            with transaction.atomic():
                DocToMarkdownCache.objects.update_or_create(
                    pdf_sha256=pdf_sha256,
                    create_defaults={
                        "id": str(cache_id),
                        "markdown_content": response_body,
                        "doc_id": doc_id,
                        "file_name": file_name,
                        "size_bytes": size_bytes,
                        "parse_method": PARSE_METHOD_MINERU,
                        "status": "1",
                        "create_date": now,
                        "update_date": now,
                    },
                    defaults={
                        "markdown_content": response_body,
                        "doc_id": doc_id,
                        "file_name": file_name,
                        "size_bytes": size_bytes,
                        "parse_method": PARSE_METHOD_MINERU,
                        "status": "1",
                        "update_date": now,
                    },
                )
                if image_rows:
                    DocImagesCache.objects.bulk_create(
                        [
                            DocImagesCache(
                                id=get_uuid(),
                                cache_id=cache_id,
                                image_key=row["image_key"],
                                image_data=row["image_data"],
                                bucket=row.get("bucket") or getattr(settings, "MINERU_IMAGES_BUCKET", "mineru"),
                                remote_url=row.get("remote_url"),
                                status=1,
                                create_date=now,
                                update_date=now,
                            )
                            for row in image_rows
                            if row.get("image_key") and row.get("image_data")
                        ],
                        ignore_conflicts=True,
                    )
        except Exception:
            logger.info("MinerU 缓存保存失败")

    def _get_existing_remote_url_map(self, image_keys: set[str]) -> dict[str, str]:
        if not image_keys:
            return {}
        try:
            rows = DocImagesCache.objects.filter(
                image_key__in=image_keys,
                status=1,
                remote_url__isnull=False,
            ).exclude(remote_url="")
            return {row.image_key: row.remote_url for row in rows if row.remote_url}
        except Exception:
            logger.info("MinerU 图片缓存查询失败")
            return {}

    def _load_image_url_map(self, raw_response: str) -> dict[str, str]:
        """缓存命中时尽量复用已上传图片 URL。"""
        try:
            image_keys = extract_markdown_image_names(self.extract_mineru_markdown(raw_response))
            if not image_keys:
                return {}
            rows = DocImagesCache.objects.filter(
                image_key__in=image_keys,
                status=1,
                remote_url__isnull=False,
            ).exclude(remote_url="")
            return {row.image_key: row.remote_url for row in rows if row.remote_url}
        except Exception:
            logger.info("MinerU 缓存图片 URL 查询失败")
            return {}


def _get_mineru_api_semaphore() -> threading.BoundedSemaphore:
    global _mineru_api_semaphore
    with _mineru_api_semaphore_lock:
        if _mineru_api_semaphore is None:
            concurrency = int(getattr(settings, "MINERU_MAX_CONCURRENCY", 1) or 1)
            _mineru_api_semaphore = threading.BoundedSemaphore(max(concurrency, 1))
        return _mineru_api_semaphore


def _get_callback(context: ParserContext) -> ProgressCallback:
    callback = context.config.get("callback")
    return callback if callable(callback) else _noop_callback


def _noop_callback(progress: float, message: str) -> None:
    return None
