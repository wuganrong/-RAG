"""对象存储工厂。"""

from __future__ import annotations

# 1. Python 标准库
import io
import re
from datetime import timedelta
from enum import Enum
from typing import BinaryIO

# 2. 第三方库
from django.conf import settings
from loguru import logger
from minio import Minio
from minio.error import S3Error

# 3. 本地应用
from __001__rag.storage.base import BaseObjectStorage
from __001__rag.utils.retry import retry_call


class StorageType(str, Enum):
    """支持的对象存储类型。"""

    MINIO = "minio"


class MinioObjectStorage(BaseObjectStorage):
    """MinIO 对象存储适配器。"""

    def __init__(self, client: Minio | None = None) -> None:
        self.client = client or self._open_client()

    def _open_client(self) -> Minio:
        host: str = getattr(settings, "MINIO_HOST", "")
        user: str = getattr(settings, "MINIO_USER", "")
        password: str = getattr(settings, "MINIO_PASSWORD", "")
        secure: bool = getattr(settings, "MINIO_SECURE", False)
        return Minio(endpoint=host, access_key=user, secret_key=password, secure=secure)

    def _reopen(self) -> None:
        self.client = self._open_client()

    def health(self) -> object:
        bucket = getattr(settings, "MINIO_HEALTH_CHECK_BUCKET", "txtxtxtxt1")
        name = getattr(settings, "MINIO_HEALTH_CHECK_OBJECT", "txtxtxtxt1")
        data = b"_t@@@1"
        self.ensure_bucket(bucket)
        return self.client.put_object(bucket, name, io.BytesIO(data), len(data))

    def normalize_bucket(self, bucket: str) -> str:
        """将 bucket 名称统一为 MinIO 可接受格式。"""
        default_bucket = getattr(settings, "MINIO_DEFAULT_BUCKET_NAME", "kb-default")
        normalized = re.sub(r"[^a-z0-9-]+", "-", (bucket or "").lower().replace("_", "-"))
        normalized = normalized.strip("-")
        if not normalized:
            normalized = default_bucket
        if len(normalized) < 3:
            normalized = f"kb-{normalized}"
        return normalized[:63].strip("-") or default_bucket

    def ensure_bucket(self, bucket: str) -> None:
        safe_bucket = self.normalize_bucket(bucket)
        if not self.client.bucket_exists(safe_bucket):
            self.client.make_bucket(safe_bucket)
            logger.info("MinIO bucket 已创建: {}", safe_bucket)

    def put(
        self,
        bucket: str,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        safe_bucket = self.normalize_bucket(bucket)
        self.ensure_bucket(safe_bucket)

        def _do_put():
            self.client.put_object(
                bucket_name=safe_bucket,
                object_name=name,
                data=io.BytesIO(data),
                length=len(data),
                content_type=content_type,
            )

        retry_call(_do_put, op_name="MinIO.put", reconnect_fn=self._reopen)
        logger.info("MinIO.put completed bucket={} name={} size={}", safe_bucket, name, len(data))

    def upload_file(
        self,
        bucket: str,
        name: str,
        file_obj: BinaryIO,
        size: int,
        content_type: str = "application/octet-stream",
    ) -> None:
        safe_bucket = self.normalize_bucket(bucket)
        self.ensure_bucket(safe_bucket)

        def _reset_file():
            if hasattr(file_obj, "seek"):
                file_obj.seek(0)

        def _do_upload():
            self.client.put_object(
                bucket_name=safe_bucket,
                object_name=name,
                data=file_obj,
                length=size,
                content_type=content_type,
            )

        retry_call(_do_upload, op_name="MinIO.upload_file", reconnect_fn=self._reopen, on_retry=_reset_file)

    def get(self, bucket: str, name: str) -> bytes:
        safe_bucket = self.normalize_bucket(bucket)
        try:
            response = self.client.get_object(bucket_name=safe_bucket, object_name=name)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()
        except Exception:
            logger.exception("MinIO.get failed bucket={}/{}", safe_bucket, name)
            self._reopen()
            raise

    def rm(self, bucket: str, name: str) -> None:
        safe_bucket = self.normalize_bucket(bucket)
        try:
            self.client.remove_object(bucket_name=safe_bucket, object_name=name)
        except S3Error as exc:
            if exc.code == "NoSuchKey":
                return
            logger.exception("MinIO.rm failed bucket={}/{}", safe_bucket, name)
        except Exception:
            logger.exception("MinIO.rm failed bucket={}/{}", safe_bucket, name)

    def obj_exist(self, bucket: str, name: str) -> bool:
        safe_bucket = self.normalize_bucket(bucket)
        try:
            if not self.client.bucket_exists(safe_bucket):
                return False
            return bool(self.client.stat_object(safe_bucket, name))
        except S3Error as exc:
            if exc.code in {"NoSuchKey", "NoSuchBucket", "ResourceNotFound"}:
                return False
            logger.exception("MinIO.obj_exist failed bucket={}/{}", safe_bucket, name)
            raise
        except Exception:
            logger.exception("MinIO.obj_exist failed bucket={}/{}", safe_bucket, name)
            raise

    def get_presigned_url(self, bucket: str, name: str, expires: timedelta | int | float) -> str | None:
        safe_bucket = self.normalize_bucket(bucket)
        expires_delta = timedelta(seconds=expires) if isinstance(expires, (int, float)) else expires
        return retry_call(
            lambda: self.client.get_presigned_url("GET", safe_bucket, name, expires=expires_delta),
            op_name="MinIO.get_presigned_url",
            reconnect_fn=self._reopen,
            max_retries_setting="MINIO_PRESIGN_MAX_RETRIES",
            default_retries=10,
            on_failure="none",
        )


class StorageFactory:
    """对象存储工厂，后续可扩展 OSS/S3 实现。"""

    _mapping: dict[StorageType, type[BaseObjectStorage]] = {
        StorageType.MINIO: MinioObjectStorage,
    }

    @classmethod
    def create(cls, storage_type: StorageType | str = StorageType.MINIO) -> BaseObjectStorage:
        """按类型创建对象存储实例。"""
        normalized = storage_type if isinstance(storage_type, StorageType) else StorageType(storage_type.lower())
        storage_cls = cls._mapping[normalized]
        return storage_cls()
