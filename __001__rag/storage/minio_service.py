"""MinIO 存储服务门面。"""

from __future__ import annotations

# 1. Python 标准库
from datetime import timedelta
from typing import BinaryIO

# 3. 本地应用
from __001__rag.models import File, File2Document
from __001__rag.storage.base import BaseObjectStorage
from __001__rag.storage.factory import StorageFactory, StorageType


class MinioService:
    """对业务层暴露统一的 MinIO 调用入口。"""

    def __init__(self, storage: BaseObjectStorage | None = None) -> None:
        self.storage = storage or StorageFactory.create(StorageType.MINIO)

    def health(self) -> object:
        return self.storage.health()

    def normalize_bucket(self, bucket: str) -> str:
        return self.storage.normalize_bucket(bucket)

    def ensure_bucket(self, bucket: str) -> None:
        self.storage.ensure_bucket(bucket)

    def put(
        self,
        bucket: str,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.storage.put(bucket=bucket, name=name, data=data, content_type=content_type)

    def upload_file(
        self,
        bucket: str,
        name: str,
        file_obj: BinaryIO,
        size: int,
        content_type: str = "application/octet-stream",
    ) -> None:
        self.storage.upload_file(
            bucket=bucket,
            name=name,
            file_obj=file_obj,
            size=size,
            content_type=content_type,
        )

    def get(self, bucket: str, name: str) -> bytes:
        return self.storage.get(bucket=bucket, name=name)

    def rm(self, bucket: str, name: str) -> None:
        self.storage.rm(bucket=bucket, name=name)

    def obj_exist(self, bucket: str, name: str) -> bool:
        return self.storage.obj_exist(bucket=bucket, name=name)

    def get_presigned_url(self, bucket: str, name: str, expires: timedelta | int | float) -> str | None:
        return self.storage.get_presigned_url(bucket=bucket, name=name, expires=expires)

    def get_storage_address(self, doc_id: str) -> tuple[str, str]:
        """根据文档 ID 从 File2Document 表查询存储地址。"""
        f2d = File2Document.objects.filter(document_id=doc_id).first()
        if not f2d:
            raise LookupError(f"File2Document record not found for doc_id={doc_id}")

        try:
            file_obj = File.objects.get(id=f2d.file_id)
        except File.DoesNotExist as exc:
            raise LookupError(f"File record not found: file_id={f2d.file_id}") from exc

        bucket = self.normalize_bucket(file_obj.parent_id)
        object_name = file_obj.location or doc_id
        return bucket, object_name

minio_service = MinioService()
