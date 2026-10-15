# models/local_paths.py
"""Resolve and prepare locally downloaded ColPali weights."""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from __010__colpali.paths import get_logger, root_dir

logger = get_logger(__name__)

load_dotenv()


def _patch_peft_json_loader() -> None:
    """PEFT opens adapter_config.json without encoding; on Windows that is cp936."""
    try:
        from peft.config import PeftConfig
    except Exception:
        return

    if getattr(PeftConfig.from_json_file, "_utf8_patched", False):
        return

    @classmethod
    def _from_json_file_utf8(cls, path_json_file: str, **kwargs):
        with open(path_json_file, encoding="utf-8") as file:
            json_object = json.load(file)
        if "runtime_config" in json_object:
            del json_object["runtime_config"]
        return json_object

    _from_json_file_utf8._utf8_patched = True
    PeftConfig.from_json_file = _from_json_file_utf8


_patch_peft_json_loader()

# Project root = localGPT-Vision-main/
_PROJECT_ROOT = Path(root_dir)
# Sibling folder: .../vlm-rag项目/models
_DEFAULT_MODELS_DIR = _PROJECT_ROOT.parent / "models"

COLPALI_DIR_NAME = "vidore-colpali-v1.2"
BASE_DIR_NAME = "vidore-colpaligemma-3b-pt-448-base"

# HuggingFace hub IDs that map to local folders when available
_HF_TO_LOCAL = {
    "vidore/colpali-v1.2": COLPALI_DIR_NAME,
    "vidore/colpali": COLPALI_DIR_NAME,
}


def get_models_dir() -> Path:
    raw = os.getenv("LOCAL_MODELS_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return _DEFAULT_MODELS_DIR.resolve()


def get_local_colpali_path() -> Path | None:
    models_dir = get_models_dir()
    path = models_dir / COLPALI_DIR_NAME
    if path.is_dir() and (path / "adapter_config.json").is_file():
        return path
    return None


def get_local_base_path() -> Path | None:
    models_dir = get_models_dir()
    path = models_dir / BASE_DIR_NAME
    if path.is_dir() and (path / "config.json").is_file():
        return path
    return None


def _as_hf_path(path: Path | str) -> str:
    """Windows-safe path for HuggingFace/PEFT JSON (forward slashes, no raw '\\')."""
    resolved = Path(path).expanduser().resolve()
    return resolved.as_posix()


def get_default_indexer_model() -> str:
    """Prefer local ColPali; fall back to HuggingFace id."""
    override = os.getenv("LOCAL_COLPALI_PATH", "").strip()
    if override:
        return _as_hf_path(override)
    local = get_local_colpali_path()
    if local is not None:
        return _as_hf_path(local)
    return "vidore/colpali-v1.2"


def _patch_adapter_config(adapter_dir: Path, base_path: Path) -> None:
    cfg_path = adapter_dir / "adapter_config.json"
    if not cfg_path.is_file():
        return
    with cfg_path.open("r", encoding="utf-8") as f:
        cfg = json.load(f)
    desired = _as_hf_path(base_path)
    current = cfg.get("base_model_name_or_path")
    raw = cfg_path.read_text(encoding="utf-8")
    # PEFT opens this file with the Windows ANSI codec (cp936). Keep the
    # file ASCII-only so '\\' next to Chinese characters cannot be eaten.
    needs_ascii = any(ord(ch) > 127 for ch in raw)
    if current == desired and not needs_ascii:
        return
    cfg["base_model_name_or_path"] = desired
    with cfg_path.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(cfg, f, indent=2, ensure_ascii=True)
        f.write("\n")
    logger.info(f"Patched {cfg_path}: base_model -> {desired}")


def ensure_local_colpali_ready() -> str | None:
    """
    Point PEFT adapter configs at the local base model and return the
    local ColPali path. Returns None if local weights are incomplete.
    """
    colpali = get_local_colpali_path()
    base = get_local_base_path()
    if colpali is None or base is None:
        missing = []
        if colpali is None:
            missing.append(COLPALI_DIR_NAME)
        if base is None:
            missing.append(BASE_DIR_NAME)
        logger.warning(
            f"Local ColPali incomplete under {get_models_dir()} (missing: {missing}). "
            "Will use HuggingFace ids unless a full local path is set."
        )
        return None

    _patch_adapter_config(colpali, base)
    ckpt = colpali / "checkpoint-18000"
    if ckpt.is_dir():
        _patch_adapter_config(ckpt, base)

    logger.info(f"Local ColPali ready: {colpali} (base={base})")
    return _as_hf_path(colpali)


def resolve_indexer_model(indexer_model: str | None) -> str:
    """
    Map HF ids / empty defaults to the local folder when available.
    Absolute paths are left unchanged (after normalize).
    """
    ensure_local_colpali_ready()
    if not indexer_model:
        return get_default_indexer_model()

    # Already a local path
    candidate = Path(indexer_model)
    if candidate.exists():
        return _as_hf_path(candidate)

    local_name = _HF_TO_LOCAL.get(indexer_model)
    if local_name:
        local_path = get_models_dir() / local_name
        if local_path.is_dir():
            logger.info(f"Redirecting '{indexer_model}' -> local {local_path}")
            return _as_hf_path(local_path)

    return indexer_model
