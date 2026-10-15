from __future__ import annotations

import os
import threading

from __010__colpali.local_paths import get_default_indexer_model, resolve_indexer_model
from __010__colpali.paths import get_logger

logger = get_logger(__name__)

_lock = threading.Lock()
_models: dict[str, object] = {}


def get_vision_model(kb_id: str, index_root: str):
    from byaldi import RAGMultiModalModel

    with _lock:
        cached = _models.get(kb_id)
        if cached is not None:
            return cached
        index_dir = os.path.join(index_root, kb_id)
        if not os.path.isdir(index_dir):
            return None
        try:
            rag = RAGMultiModalModel.from_index(kb_id, index_root=index_root)
            _models[kb_id] = rag
            logger.info("Loaded shared ColPali index for kb=%s", kb_id)
            return rag
        except Exception as exc:
            logger.error("Failed to load ColPali index for kb=%s: %s", kb_id, exc)
            return None


def build_vision_index(kb_id: str, folder_path: str, index_root: str, indexer_model: str | None = None):
    from __010__colpali.index.indexer import index_documents

    model = resolve_indexer_model(indexer_model or get_default_indexer_model())
    index_path = os.path.join(index_root, kb_id)
    with _lock:
        rag = index_documents(
            folder_path,
            index_name=kb_id,
            index_path=index_path,
            indexer_model=model,
        )
        _models[kb_id] = rag
        return rag


def add_vision_document(
    kb_id: str,
    file_path: str,
    index_root: str,
    indexer_model: str | None = None,
):
    from __010__colpali.index.converters import convert_file_to_pdf
    from __010__colpali.index.indexer import index_documents

    path = convert_file_to_pdf(file_path)
    model = resolve_indexer_model(indexer_model or get_default_indexer_model())
    index_path = os.path.join(index_root, kb_id)
    with _lock:
        rag = _models.get(kb_id)
        if rag is None and os.path.isdir(os.path.join(index_root, kb_id)):
            from byaldi import RAGMultiModalModel

            rag = RAGMultiModalModel.from_index(kb_id, index_root=index_root)
            _models[kb_id] = rag
        if rag is None:
            rag = index_documents(
                path,
                index_name=kb_id,
                index_path=index_path,
                indexer_model=model,
            )
            _models[kb_id] = rag
            logger.info("Created vision index for kb=%s from %s", kb_id, path)
            return rag
        rag.add_to_index(path, store_collection_with_index=True)
        logger.info("Incrementally added %s to vision index kb=%s", path, kb_id)
        return rag


def drop_vision_index(kb_id: str, index_root: str | None = None) -> None:
    import shutil

    with _lock:
        _models.pop(kb_id, None)
        if index_root:
            folder = os.path.join(index_root, kb_id)
            if os.path.isdir(folder):
                shutil.rmtree(folder, ignore_errors=True)


def rebuild_from_files(
    kb_id: str,
    file_paths: list[str],
    index_root: str,
    indexer_model: str | None = None,
) -> int:
    """Byaldi cannot delete one document; rebuild the whole KB vision index."""
    drop_vision_index(kb_id, index_root)
    added = 0
    for path in file_paths:
        if path and os.path.isfile(path):
            add_vision_document(kb_id, path, index_root, indexer_model)
            added += 1
    return added
