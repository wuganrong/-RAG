from __future__ import annotations

import os
import shutil
from pathlib import Path


class LocalObjectStorage:
    """Local disk stand-in for MinIO/OSS. Keys look like {kb_id}/{filename}."""

    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def full_path(self, key: str) -> str:
        path = (self.root / key.replace("\\", "/")).resolve()
        root = self.root.resolve()
        if root not in path.parents and path != root:
            raise ValueError("非法存储路径")
        path.parent.mkdir(parents=True, exist_ok=True)
        return str(path)

    def put_file(self, key: str, src_path: str) -> str:
        dest = self.full_path(key)
        if os.path.abspath(src_path) != os.path.abspath(dest):
            shutil.copy2(src_path, dest)
        return dest.replace("\\", "/")

    def delete(self, key: str) -> None:
        path = Path(self.full_path(key))
        if path.is_file():
            path.unlink(missing_ok=True)

    def delete_prefix(self, prefix: str) -> None:
        folder = Path(self.full_path(prefix))
        if folder.is_dir():
            shutil.rmtree(folder, ignore_errors=True)


from __000__common.__001__path import UPLOAD_DIR

storage = LocalObjectStorage(UPLOAD_DIR)
