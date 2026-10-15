from __future__ import annotations

import json
import os
from typing import Any

import numpy as np


class NumpyVectorStore:
    """Per-KB dense vector index. Phase-2 stand-in for Elasticsearch KNN."""

    def __init__(self, root: str):
        self.root = root
        os.makedirs(self.root, exist_ok=True)

    def _paths(self, kb_id: str) -> tuple[str, str]:
        folder = os.path.join(self.root, kb_id)
        os.makedirs(folder, exist_ok=True)
        return os.path.join(folder, "embeddings.npy"), os.path.join(folder, "meta.json")

    def _load(self, kb_id: str) -> tuple[np.ndarray | None, list[dict[str, Any]]]:
        npy_path, meta_path = self._paths(kb_id)
        if not os.path.exists(meta_path):
            return None, []
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)
        matrix = np.load(npy_path) if os.path.exists(npy_path) else None
        return matrix, meta

    def _save(self, kb_id: str, matrix: np.ndarray | None, meta: list[dict[str, Any]]) -> None:
        npy_path, meta_path = self._paths(kb_id)
        if matrix is not None and len(meta) > 0:
            np.save(npy_path, matrix.astype(np.float32))
        elif os.path.exists(npy_path):
            os.remove(npy_path)
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False)

    def replace_doc(self, kb_id: str, doc_id: str, rows: list[dict[str, Any]]) -> None:
        matrix, meta = self._load(kb_id)
        keep_idx = [i for i, item in enumerate(meta) if item.get("doc_id") != doc_id]
        kept_meta = [meta[i] for i in keep_idx]
        kept_matrix = matrix[keep_idx] if matrix is not None and keep_idx else None
        new_vecs = [row["embedding"] for row in rows if row.get("embedding")]
        new_meta = [
            {k: v for k, v in row.items() if k != "embedding"}
            for row in rows
            if row.get("embedding")
        ]
        if new_vecs:
            added = np.asarray(new_vecs, dtype=np.float32)
            if kept_matrix is None or kept_matrix.size == 0:
                matrix = added
            else:
                matrix = np.vstack([kept_matrix, added])
            meta = kept_meta + new_meta
        else:
            matrix = kept_matrix
            meta = kept_meta
        self._save(kb_id, matrix, meta)

    def delete_doc(self, kb_id: str, doc_id: str) -> None:
        self.replace_doc(kb_id, doc_id, [])

    def drop_kb(self, kb_id: str) -> None:
        folder = os.path.join(self.root, kb_id)
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                os.remove(os.path.join(folder, name))
            os.rmdir(folder)

    def search(
        self,
        kb_id: str,
        query_vec: list[float],
        top_k: int = 6,
        doc_ids: list[str] | None = None,
    ) -> list[tuple[float, dict[str, Any]]]:
        matrix, meta = self._load(kb_id)
        if matrix is None or not meta:
            return []
        query = np.asarray(query_vec, dtype=np.float32)
        if query.ndim != 1 or query.shape[0] != matrix.shape[1]:
            return []
        norms = np.linalg.norm(matrix, axis=1) * (np.linalg.norm(query) + 1e-12)
        scores = (matrix @ query) / (norms + 1e-12)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for idx, item in enumerate(meta):
            if doc_ids and item.get("doc_id") not in doc_ids:
                continue
            ranked.append((float(scores[idx]), item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return ranked[: max(top_k, 1)]


from __000__common.__001__path import VECTOR_DIR

vector_store = NumpyVectorStore(VECTOR_DIR)
