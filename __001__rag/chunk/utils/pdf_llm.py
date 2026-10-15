"""PDF-LLM / MinerU 章节二次分块工具。"""

from __future__ import annotations

# 1. Python 标准库
import hashlib
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# 2. 第三方库
from django.conf import settings
from django.db import DatabaseError
from loguru import logger

# 3. 本地应用
from __001__rag.llm.base import ChatMessage
from __001__rag.llm.service import LLMService
from __001__rag.models import AssistantConfig as AssistantConfigModel
from __001__rag.models import AssistantType, PdfLlmSectionRawCache, PromptConfig
from __001__rag.utils.ids import get_uuid

GB_CHUNK_ASSISTANT_PREFIX = "gb_"
GB_CHUNK_DEFAULT_KEY = "gb_default"
PARSE_METHOD_MINERU = "mineru"
SECTION_FILE_SEPARATOR = "----------------------------------------章节分隔线----------------------------------------------------------"
CHUNK_DELIMITER = "---CHUNK---"

_CLAUSE_NUM_ONLY_RE = re.compile(r"^(\d+(?:\.\d+)*)\s*$")
_extract_llm_chat_semaphore: threading.BoundedSemaphore | None = None
_extract_llm_chat_semaphore_lock = threading.Lock()

CHUNK_SYSTEM = """
你是一名国家级标准文档结构化工程师。请根据给定的国家标准文档内容，进行高精度语义分块，并将结果按下方「自定义分块格式」输出。

分块原则：
1. 每个分块必须语义完整，可独立理解。
2. 表格、图、注、公式必须整体作为一个块。
3. 列表项必须整体保留，不得切断。
4. 严格遵循原文章节、条款、子条款、附录、图、表边界。
5. 内容必须保真，保留原文文字、符号、单位、空格和换行。
6. 普通条款尽量控制在 1000 字符以内，超长时按自然段落或完整列表项拆分。

输出格式：
每个分块以单独一行 ---CHUNK--- 开始，块内按顺序输出：
title: 完整标题路径，使用 > 连接各级标题
section_ref: 标准章节号
subject: 核心技术主体
content:
正文内容从 content: 下一行开始，直到下一个 ---CHUNK--- 或文本结束。

不要输出 Markdown 代码块标记，不要输出额外解释。
""".strip()


def fix_clause_numbers(markdown_content: str) -> str:
    """把仅含条款编号的独占行改写为 Markdown 标题。"""
    if not markdown_content:
        return markdown_content

    output: list[str] = []
    for raw_line in markdown_content.splitlines():
        normalized = raw_line.replace("　", " ").replace("​", "").strip()
        if normalized.startswith("# "):
            output.append(raw_line)
            continue
        match = _CLAUSE_NUM_ONLY_RE.match(normalized)
        if match and match.group(1).strip():
            output.append(f"# {match.group(1).strip()}")
            continue
        output.append(raw_line)
    return "\n".join(output)


def sections_with_parent(sections: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """为章节补充 `parent_title`，供 LLM 构造完整标题路径。"""
    id_to_title = {str(section.get("section_id")): str(section.get("title") or "") for section in sections}
    for section in sections:
        section_id = str(section.get("section_id") or "")
        parent_id: str | None = None
        if re.match(r"^\d+(\.\d+)*$", section_id):
            parts = section_id.split(".")
            if len(parts) > 1:
                parent_id = ".".join(parts[:-1])
        parent_title = id_to_title.get(parent_id) if parent_id else None
        section["parent_title"] = parent_title.strip() if parent_title else None
    return sections


def extract_gb_standard_from_filename(filename: str) -> str | None:
    """从文件名提取国标号，如 `GB 1234-2020` 或 `GBT 1234-2020`。"""
    if not filename:
        return None
    match = re.search(r"(GBT?\s*\d+(?:\.\d+)?-\d{4})", filename, re.IGNORECASE)
    return match.group(1).strip() if match else None


def write_sections_to_file(file_name: str, sections: list[dict[str, Any]]) -> str | None:
    """按 ragflow 调试格式写出章节内容，失败时返回 None。"""
    if not sections:
        return None

    base = os.path.splitext(os.path.basename(file_name))[0] or "unnamed"
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    output_dir = getattr(settings, "PDF_LLM_SECTIONS_OUTPUT_DIR", "/ragflow/logs/out") or "/ragflow/logs/out"
    output_path = os.path.abspath(os.path.join(output_dir, f"{base}sections{timestamp}.txt"))
    lines = _format_sections_file_lines(sections)

    try:
        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as file_obj:
            file_obj.write("\n".join(lines))
    except OSError as exc:
        logger.info("写出章节文件失败 path={} error={}", output_path, exc)
        return None

    logger.info("章节文件已写出 path={} section_count={}", output_path, len(sections))
    return output_path


def chunk_section_with_llm(
    section: dict[str, Any],
    *,
    callback: Any | None = None,
    doc_id: str | None = None,
    kb_id: str | None = None,
    file_name: str | None = None,
    parse_method: str = PARSE_METHOD_MINERU,
) -> list[dict[str, str]]:
    """对一个章节调用 LLM 二次分块，并缓存原始响应。"""
    section_id = str(section["section_id"])
    title = str(section.get("title") or "")
    parent_title = str(section.get("parent_title") or "") or None
    content = str(section.get("content") or "")
    if not content.strip():
        raise ValueError(f"章节内容为空: {section_id}")

    callback = callback or _noop_callback
    cached_chunks = _load_cached_llm_chunks(content, parse_method, section_id, title, parent_title)
    if cached_chunks:
        return cached_chunks

    user_prompt = build_chunk_user(section_id, title, parent_title, content)
    raw = _extract_llm_chat(
        user_prompt=user_prompt,
        section_id=section_id,
        title=title,
        parent_title=parent_title,
    )
    _save_llm_raw_cache(
        input_text=content,
        raw_response=raw,
        section_id=section_id,
        title=title,
        parent_title=parent_title,
        doc_id=doc_id,
        kb_id=kb_id,
        file_name=file_name,
        parse_method=parse_method,
    )

    chunks = parse_llm_chunks(raw)
    _fill_chunk_defaults(chunks, section_id, parent_title, title)
    callback(0.0, f"LLM 章节分块完成 section_id={section_id}")
    return chunks


def build_chunk_user(section_id: str, section_title: str, parent_title: str | None, content: str) -> str:
    """构造发给 LLM 的用户消息。"""
    lines = [
        "当前章节信息：",
        f"- 章节号：{section_id}",
        f"- 章节标题：{section_title}",
    ]
    if parent_title:
        lines.append(f"- 上一级标题：{parent_title}")
        lines.append("要求：每个分块的 title 必须包含上一级标题。")
    lines.extend(["", "章节内容：", content])
    return "\n".join(lines)


def parse_llm_chunks(raw: str) -> list[dict[str, str]]:
    """解析 LLM 返回的 `---CHUNK---` 自定义格式。"""
    content = (raw or "").strip()
    think_idx = content.lower().find("</think>")
    if think_idx != -1:
        content = content[think_idx + len("</think>") :].strip()
    if CHUNK_DELIMITER not in content:
        raise ValueError("LLM 返回中未包含 ---CHUNK---")

    chunks = _parse_custom_chunk_format(content)
    if not chunks:
        raise ValueError("解析 ---CHUNK--- 后未得到有效分块")
    logger.info("解析 LLM 分块完成 chunk_count={}", len(chunks))
    return chunks


def _format_sections_file_lines(sections: list[dict[str, Any]]) -> list[str]:
    lines = ["# 目 次", ""]
    for section in sections:
        section_id = str(section.get("section_id") or "")
        title = str(section.get("title") or section_id).strip()
        lines.append(f"{section_id} {title}")

    lines.extend(["", SECTION_FILE_SEPARATOR, ""])
    for section in sections:
        section_id = str(section.get("section_id") or "")
        title = str(section.get("title") or section_id).strip()
        content = str(section.get("content") or "").strip()
        if title and title != section_id:
            lines.append(f"# {title}")
        lines.extend([f"# {section_id} {title}".strip() if title else f"# {section_id}", "", content, "", SECTION_FILE_SEPARATOR, ""])
    return lines


def _load_cached_llm_chunks(
    input_text: str,
    parse_method: str,
    section_id: str,
    title: str,
    parent_title: str | None,
) -> list[dict[str, str]] | None:
    input_sha256 = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    try:
        row = (
            PdfLlmSectionRawCache.objects.filter(
                input_sha256=input_sha256,
                parse_method=parse_method,
                status="1",
            )
            .order_by("-create_date")
            .first()
        )
    except DatabaseError as exc:
        logger.info("查询 LLM 分块缓存失败 section_id={} error={}", section_id, exc)
        return None

    if not row or not row.raw_response:
        return None

    logger.info("LLM 分块命中缓存 section_id={} parse_method={}", section_id, parse_method)
    try:
        chunks = parse_llm_chunks(row.raw_response)
    except ValueError as exc:
        logger.info("LLM 分块缓存解析失败，回退调用 LLM section_id={} error={}", section_id, exc)
        return None
    _fill_chunk_defaults(chunks, section_id, parent_title, title)
    return chunks


def _save_llm_raw_cache(
    *,
    input_text: str,
    raw_response: str,
    section_id: str,
    title: str,
    parent_title: str | None,
    doc_id: str | None,
    kb_id: str | None,
    file_name: str | None,
    parse_method: str,
) -> None:
    input_sha256 = hashlib.sha256(input_text.encode("utf-8")).hexdigest()
    try:
        row = (
            PdfLlmSectionRawCache.objects.filter(input_sha256=input_sha256, parse_method=parse_method)
            .order_by("-create_date")
            .first()
        )
        values = _build_raw_cache_values(
            raw_response=raw_response,
            section_id=section_id,
            title=title,
            parent_title=parent_title,
            doc_id=doc_id,
            kb_id=kb_id,
            file_name=file_name,
            input_text=input_text,
        )
        if row:
            for key, value in values.items():
                setattr(row, key, value)
            row.save(update_fields=list(values))
        else:
            PdfLlmSectionRawCache.objects.create(
                id=get_uuid(),
                input_sha256=input_sha256,
                parse_method=parse_method,
                create_date=datetime.now(),
                **values,
            )
    except DatabaseError as exc:
        logger.info("写入 LLM 分块缓存失败 section_id={} error={}", section_id, exc)


def _build_raw_cache_values(
    *,
    raw_response: str,
    section_id: str,
    title: str,
    parent_title: str | None,
    doc_id: str | None,
    kb_id: str | None,
    file_name: str | None,
    input_text: str,
) -> dict[str, Any]:
    return {
        "raw_response": raw_response,
        "section_id": section_id,
        "title": title,
        "parent_title": parent_title or "",
        "doc_id": doc_id,
        "kb_id": kb_id,
        "file_name": file_name,
        "section_content": input_text,
        "status": "1",
        "update_date": datetime.now(),
    }


def _extract_llm_chat(
    *,
    user_prompt: str,
    section_id: str,
    title: str,
    parent_title: str | None,
) -> str:
    sem = _get_extract_llm_chat_semaphore()
    sem.acquire()
    try:
        cfg = _resolve_prompt_options(
            section_id=section_id,
            title=title,
            parent_title=parent_title,
        )
        if not cfg.get("system_prompt"):
            raise ValueError("国标分块未配置 system_prompt")
        temperature = cfg.get("temperature")
        response = LLMService.chat(
            messages=[
                ChatMessage(role="system", content=cfg.get("system_prompt") or CHUNK_SYSTEM),
                ChatMessage(role="user", content=user_prompt),
            ],
            model_name=cfg.get("model_name") or getattr(settings, "LLM_MODEL_ID", None),
            temperature=temperature if temperature is not None else float(getattr(settings, "PDF_LLM_DEFAULT_TEMPERATURE", 0.2)),
            top_p=cfg.get("top_p"),
            max_tokens=cfg.get("max_tokens"),
            extra=cfg.get("extra_params") or {},
        )
    finally:
        sem.release()

    raw = (response.content or "").strip()
    if not raw:
        raise ValueError("LLM 分块返回为空")
    return raw


@dataclass(frozen=True, slots=True)
class _GbChunkConfigEntry:
    assistant_key: str
    section_name: str
    system_prompt: str | None
    model_name: str | None
    temperature: float | None
    top_p: float | None
    max_tokens: int | None
    extra_params: dict[str, Any]


_gb_chunk_config_cache: list[_GbChunkConfigEntry] | None = None
_gb_chunk_config_cache_lock = threading.Lock()

_SECTION_MATCHERS: tuple[tuple[str, Callable[[str, str], bool]], ...] = (
    ("前言", lambda section_id, full_path: section_id == "前言" or "前言" in full_path),
    ("术语和定义", lambda _section_id, full_path: "术语和定义" in full_path),
    ("特殊规定", lambda _section_id, full_path: "特殊规定" in full_path),
)


def clear_gb_chunk_config_cache() -> None:
    """管理端更新国标分块助理/提示词后调用，使进程内缓存立即失效。"""
    global _gb_chunk_config_cache
    with _gb_chunk_config_cache_lock:
        _gb_chunk_config_cache = None


def is_gb_chunk_related_key(key: str | None) -> bool:
    """判断 assistant_key / prompt_config_key 是否属于国标 MinerU 分块配置。"""
    return bool((key or "").strip().startswith(GB_CHUNK_ASSISTANT_PREFIX))


def _resolve_prompt_options(
    *,
    section_id: str,
    title: str,
    parent_title: str | None,
) -> dict[str, Any]:
    entries = _load_gb_chunk_configs()
    matched = _match_gb_chunk_entry(entries, section_id=section_id, title=title, parent_title=parent_title)
    if matched is None:
        return {"system_prompt": CHUNK_SYSTEM}

    cfg = {
        "system_prompt": matched.system_prompt or CHUNK_SYSTEM,
        "model_name": matched.model_name,
        "temperature": matched.temperature,
        "top_p": matched.top_p,
        "max_tokens": matched.max_tokens,
        "extra_params": matched.extra_params,
    }
    return cfg


def _load_gb_chunk_configs() -> list[_GbChunkConfigEntry]:
    global _gb_chunk_config_cache
    with _gb_chunk_config_cache_lock:
        if _gb_chunk_config_cache is not None:
            return _gb_chunk_config_cache

        entries: list[_GbChunkConfigEntry] = []
        try:
            assistants = list(
                AssistantConfigModel.objects.filter(
                    status="1",
                    assistant_type=AssistantType.TASK,
                    assistant_key__startswith=GB_CHUNK_ASSISTANT_PREFIX,
                ).order_by("id")
            )
            prompt_keys = [row.prompt_config_key for row in assistants if row.prompt_config_key]
            prompts = {
                row.config_key: row
                for row in PromptConfig.objects.filter(config_key__in=prompt_keys, status="1")
            }
            for assistant in assistants:
                prompt = prompts.get(assistant.prompt_config_key or "")
                if prompt is None:
                    continue
                entries.append(_build_gb_chunk_entry(assistant, prompt))
        except DatabaseError as exc:
            logger.info("加载国标分块配置失败 error={}", exc)

        _gb_chunk_config_cache = entries
        return entries


def _build_gb_chunk_entry(assistant: AssistantConfigModel, prompt: PromptConfig) -> _GbChunkConfigEntry:
    llm_setting = assistant.llm_setting if isinstance(assistant.llm_setting, dict) else {}
    extra_params = assistant.extra_params if isinstance(assistant.extra_params, dict) else {}
    merged_extra = extra_params.copy()
    for key, value in llm_setting.items():
        if key not in {"temperature", "top_p", "max_tokens"} and key not in merged_extra:
            merged_extra[key] = value

    max_tokens = assistant.max_tokens
    if max_tokens is None:
        max_tokens = llm_setting.get("max_tokens")

    model_name = (assistant.model_name or "").strip() or None
    system_prompt = (prompt.system_prompt or "").strip() or None
    return _GbChunkConfigEntry(
        assistant_key=assistant.assistant_key,
        section_name=(prompt.section_name or "").strip(),
        system_prompt=system_prompt,
        model_name=model_name,
        temperature=llm_setting.get("temperature"),
        top_p=llm_setting.get("top_p"),
        max_tokens=max_tokens,
        extra_params=merged_extra,
    )


def _match_gb_chunk_entry(
    entries: list[_GbChunkConfigEntry],
    *,
    section_id: str,
    title: str,
    parent_title: str | None,
) -> _GbChunkConfigEntry | None:
    if not entries:
        return None

    full_path = _section_full_path(section_id, title, parent_title)
    normalized_section_id = (section_id or "").strip()
    for section_name, predicate in _SECTION_MATCHERS:
        if predicate(normalized_section_id, full_path):
            matched = _find_entry_by_section_name(entries, section_name)
            if matched is not None:
                return matched

    return _find_entry_by_assistant_key(entries, GB_CHUNK_DEFAULT_KEY) or entries[0]


def _section_full_path(section_id: str, title: str, parent_title: str | None) -> str:
    parts: list[str] = []
    if parent_title and parent_title.strip():
        parts.append(parent_title.strip())
    if title and title.strip():
        parts.append(title.strip())
    elif section_id and section_id.strip():
        parts.append(section_id.strip())
    return ">".join(parts)


def _find_entry_by_section_name(
    entries: list[_GbChunkConfigEntry],
    section_name: str,
) -> _GbChunkConfigEntry | None:
    for entry in entries:
        if entry.section_name == section_name:
            return entry
    return None


def _find_entry_by_assistant_key(
    entries: list[_GbChunkConfigEntry],
    assistant_key: str,
) -> _GbChunkConfigEntry | None:
    for entry in entries:
        if entry.assistant_key == assistant_key:
            return entry
    return None


def _get_extract_llm_chat_semaphore() -> threading.BoundedSemaphore:
    global _extract_llm_chat_semaphore
    concurrency = max(1, int(getattr(settings, "MAX_CONCURRENT_CHUNK_BUILDERS", 1) or 1))
    with _extract_llm_chat_semaphore_lock:
        if _extract_llm_chat_semaphore is None:
            _extract_llm_chat_semaphore = threading.BoundedSemaphore(concurrency)
            logger.info("LLM 分块并发槽位 concurrency={}", concurrency)
        return _extract_llm_chat_semaphore


def _parse_custom_chunk_format(raw: str) -> list[dict[str, str]]:
    chunks: list[dict[str, str]] = []
    for part in raw.split(CHUNK_DELIMITER):
        parsed = _parse_chunk_part(part)
        if parsed is not None:
            chunks.append(parsed)
    return chunks


def _parse_chunk_part(part: str) -> dict[str, str] | None:
    part = part.strip()
    if not part:
        return None

    metadata: dict[str, str] = {}
    content_lines: list[str] = []
    found_content = False
    for line in part.split("\n"):
        if found_content:
            content_lines.append(line)
            continue
        if line.strip().startswith("content:"):
            found_content = True
            rest = line.split("content:", 1)[-1].strip()
            if rest:
                content_lines.append(rest)
            continue
        if ": " in line:
            key, _, value = line.partition(": ")
            if key.strip().lower() in {"title", "section_ref", "subject"}:
                metadata[key.strip().lower()] = value.strip()

    content = "\n".join(content_lines).strip()
    title = metadata.get("title", "").strip()
    if not content and not title:
        return None
    return {
        "title": title,
        "section_ref": metadata.get("section_ref", "").strip(),
        "subject": metadata.get("subject", "").strip(),
        "content": content,
    }


def _fill_chunk_defaults(
    chunks: list[dict[str, str]],
    section_id: str,
    parent_title: str | None,
    section_title: str,
) -> None:
    for chunk in chunks:
        chunk["section_ref"] = chunk.get("section_ref") or section_id
        _ensure_title_with_parent(chunk, parent_title, section_title)


def _ensure_title_with_parent(chunk: dict[str, str], parent_title: str | None, section_title: str) -> None:
    if not parent_title:
        return
    title = (chunk.get("title") or "").strip() or section_title
    if not title.startswith(parent_title):
        chunk["title"] = f"{parent_title} / {title}"


def _noop_callback(_progress: float, _message: str) -> None:
    return None
