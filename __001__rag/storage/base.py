"""对象存储基础抽象。"""

from __future__ import annotations

# 1. Python 标准库
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import timedelta
from typing import BinaryIO


@dataclass(slots=True)
class StorageObject:
    """对象存储中的文件引用。"""

    bucket: str
    name: str
    content_type: str = "application/octet-stream"


class BaseObjectStorage(ABC):
    """对象存储端口，屏蔽 MinIO/OSS/S3 等实现差异。"""

    @abstractmethod
    def health(self) -> object:
        """检查对象存储连接可用性。"""
        raise NotImplementedError

    @abstractmethod
    def normalize_bucket(self, bucket: str) -> str:
        """规范化 bucket 名称。"""
        raise NotImplementedError

    @abstractmethod
    def ensure_bucket(self, bucket: str) -> None:
        """确保 bucket 存在。"""
        raise NotImplementedError

    @abstractmethod
    def put(
        self,
        bucket: str,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """上传二进制内容。"""
        raise NotImplementedError

    def upload_bytes(
        self,
        bucket: str,
        name: str,
        data: bytes,
        content_type: str = "application/octet-stream",
    ) -> None:
        """上传二进制内容。"""
        self.put(bucket=bucket, name=name, data=data, content_type=content_type)

    @abstractmethod
    def upload_file(
        self,
        bucket: str,
        name: str,
        file_obj: BinaryIO,
        size: int,
        content_type: str = "application/octet-stream",
    ) -> None:
        """上传文件对象。"""
        raise NotImplementedError

    @abstractmethod
    def get(self, bucket: str, name: str) -> bytes:
        """下载对象内容。"""
        raise NotImplementedError

    def download_bytes(self, bucket: str, name: str) -> bytes:
        """下载对象内容。"""
        return self.get(bucket=bucket, name=name)

    @abstractmethod
    def rm(self, bucket: str, name: str) -> None:
        """删除对象。"""
        raise NotImplementedError

    def remove(self, bucket: str, name: str) -> None:
        """删除对象。"""
        self.rm(bucket=bucket, name=name)

    @abstractmethod
    def obj_exist(self, bucket: str, name: str) -> bool:
        """判断对象是否存在。"""
        raise NotImplementedError

    @abstractmethod
    def get_presigned_url(self, bucket: str, name: str, expires: timedelta | int | float) -> str | None:
        """生成对象预签名下载地址。"""
        raise NotImplementedError
