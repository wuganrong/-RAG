from __future__ import annotations

from __000__common.__001__path import UPLOAD_DIR
from __004__store.storage.local import LocalObjectStorage
from __004__store.storage.minio_store import DualObjectStorage

storage = DualObjectStorage(UPLOAD_DIR)


def get_storage() -> LocalObjectStorage:
    return storage
