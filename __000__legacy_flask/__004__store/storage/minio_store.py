from __future__ import annotations

import os

from __000__common.__002__log import get_logger
from __000__common.__004__infra import MINIO_BUCKET, MINIO_SECURE, MINIO_USER, MINIO_PASSWORD, minio_endpoint
from __004__store.storage.local import LocalObjectStorage

logger = get_logger(__name__)


class DualObjectStorage(LocalObjectStorage):
    """Keep a local copy for ColPali and mirror objects to the existing MinIO."""

    def __init__(self, root: str):
        super().__init__(root)
        self.client = None
        self.bucket = MINIO_BUCKET
        self._tried = False

    def _ensure_client(self, retry: bool = False):
        if retry:
            self._tried = False
            self.client = None
        if self._tried:
            return self.client
        self._tried = True
        try:
            from minio import Minio
            from urllib3 import Timeout
            from urllib3.poolmanager import PoolManager

            http = PoolManager(timeout=Timeout(connect=1.5, read=2.0))
            client = Minio(
                minio_endpoint(),
                access_key=MINIO_USER,
                secret_key=MINIO_PASSWORD,
                secure=MINIO_SECURE,
                http_client=http,
            )
            if not client.bucket_exists(self.bucket):
                client.make_bucket(self.bucket)
            self.client = client
            logger.info("MinIO ready %s bucket=%s", minio_endpoint(), self.bucket)
        except Exception as exc:
            logger.warning("MinIO unavailable, local disk only: %s", exc)
            self.client = None
        return self.client

    def put_file(self, key: str, src_path: str) -> str:
        dest = super().put_file(key, src_path)
        client = self._ensure_client()
        if client is not None:
            try:
                size = os.path.getsize(dest)
                with open(dest, "rb") as f:
                    client.put_object(self.bucket, key.replace("\\", "/"), f, size)
            except Exception as exc:
                logger.warning("MinIO put failed key=%s: %s", key, exc)
        return dest

    def delete(self, key: str) -> None:
        super().delete(key)
        client = self._ensure_client()
        if client is not None:
            try:
                client.remove_object(self.bucket, key.replace("\\", "/"))
            except Exception:
                pass

    def health(self, retry: bool = False) -> dict:
        client = self._ensure_client(retry=retry)
        return {"ok": client is not None, "endpoint": minio_endpoint(), "bucket": self.bucket}
