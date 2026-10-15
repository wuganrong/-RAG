from __future__ import annotations

import os
from pathlib import Path

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
root_dir = str(PROJECT_ROOT)


def get_logger(_name: str):
    return logger


def _data_dir(relative_path: str) -> str:
    path = PROJECT_ROOT / relative_path
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def page_relpath(image: str) -> str:
    return (image or "").replace("\\", "/").removeprefix("images/").lstrip("/")


def page_abs_path(image: str) -> str:
    return os.path.join(PAGE_IMAGE_DIR, page_relpath(image))


DATA_DIR = _data_dir("data")
UPLOAD_DIR = _data_dir("data/uploads")
PAGE_IMAGE_DIR = _data_dir("data/page_images")
BYALDI_DIR = _data_dir("data/byaldi")
