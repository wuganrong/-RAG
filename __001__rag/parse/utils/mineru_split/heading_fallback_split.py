"""MinerU Markdown 标题回退切分。"""

from __future__ import annotations

# 1. Python 标准库
import re

# 3. 本地应用
from __001__rag.parse.utils.mineru_split.toc_split import find_toc_block

SectionTuple = tuple[str, str]
HeadingMatch = tuple[int, str, str]
SectionBlock = tuple[str, str, list[str]]

_LEVEL1_NUM_RE = re.compile(r"^#\s+(\d+)\s*(.*)$")
_LEVEL1_SPECIAL_RE = re.compile(r"^#\s*(前\s*言|引\s*言|参\s*考\s*文\s*献)\s*$", re.IGNORECASE)
_LEVEL1_APPENDIX_RE = re.compile(r"^#\s*附\s*录\s*([A-Z])\s*", re.IGNORECASE)
_LEVEL1_APPENDIX_ALT_RE = re.compile(r"^#\s*附录\s*[A-Z].*$", re.IGNORECASE)
_LEVEL2_RE = re.compile(r"^#\s+(\d+\.\d+)(?!\.|\d)\s*(.*)$")


def split_by_headings(content: str, max_section_chars: int = 5000) -> list[dict[str, str]]:
    """按一级标题切分；超长一级章节再按二级标题切分。"""
    lines = content.splitlines()
    if not lines:
        return []

    stripped_lines = _strip_toc_body_lines(lines)
    if not stripped_lines:
        return []

    level1_matches = _find_level1_matches(stripped_lines)
    if not level1_matches:
        return [{"section_id": "1", "title": "", "content": content.strip()}]

    sections: list[dict[str, str]] = []
    for idx, (line_idx, section_id, title) in enumerate(level1_matches):
        end_idx = level1_matches[idx + 1][0] if idx + 1 < len(level1_matches) else len(stripped_lines)
        block_lines = stripped_lines[line_idx:end_idx]
        sections.extend(_split_level1_block(section_id, title, block_lines, max_section_chars))
    return sections


def _is_level1_line(line: str) -> SectionTuple | None:
    stripped = line.strip()
    if not stripped.startswith("# "):
        return None
    rest = stripped[2:].strip()

    num_match = _LEVEL1_NUM_RE.match(stripped)
    if num_match:
        return _parse_level1_number(rest, num_match)

    special_match = _LEVEL1_SPECIAL_RE.match(stripped)
    if special_match:
        name = special_match.group(1).strip()
        return name.replace(" ", ""), name

    if _LEVEL1_APPENDIX_RE.match(stripped) or _LEVEL1_APPENDIX_ALT_RE.match(stripped):
        appendix_match = _LEVEL1_APPENDIX_RE.match(stripped)
        if appendix_match:
            letter = appendix_match.group(1).upper()
            return f"附录{letter}", rest[rest.find(letter) :].strip() or f"附录{letter}"
        return "附录", rest

    return None


def _is_level2_line(line: str) -> SectionTuple | None:
    stripped = line.strip()
    if not stripped.startswith("# "):
        return None
    match = _LEVEL2_RE.match(stripped)
    if not match:
        return None
    section_id = match.group(1)
    return section_id, (match.group(2) or "").strip() or section_id


def _parse_level1_number(rest: str, match: re.Match[str]) -> SectionTuple | None:
    number = match.group(1)
    title_part = (match.group(2) or "").strip()
    if title_part.startswith(".") or (len(rest) > len(number) and rest[len(number) : len(number) + 1] == "."):
        return None
    if title_part:
        last_token = title_part.rsplit(None, 1)[-1]
        if last_token.isdigit() and len(last_token) <= 3:
            return None
    return number, title_part if title_part else number


def _find_level1_matches(lines: list[str]) -> list[HeadingMatch]:
    result: list[HeadingMatch] = []
    for idx, line in enumerate(lines):
        section = _is_level1_line(line)
        if section:
            result.append((idx, section[0], section[1]))
    return result


def _find_level2_matches(lines: list[str]) -> list[HeadingMatch]:
    result: list[HeadingMatch] = []
    for idx, line in enumerate(lines):
        section = _is_level2_line(line)
        if section:
            result.append((idx, section[0], section[1]))
    return result


def _split_by_level2(lines: list[str], max_chars: int) -> list[SectionBlock]:
    block_content = "\n".join(lines)
    if len(block_content) <= max_chars:
        return []

    matches = _find_level2_matches(lines)
    if not matches:
        return []

    chunks: list[SectionBlock] = []
    for idx, (line_idx, section_id, title) in enumerate(matches):
        end_idx = matches[idx + 1][0] if idx + 1 < len(matches) else len(lines)
        chunks.append((section_id, title, lines[line_idx:end_idx]))
    return chunks


def _strip_toc_body_lines(lines: list[str]) -> list[str]:
    toc_range = find_toc_block(lines)
    if not toc_range:
        return lines
    start, end = toc_range
    return lines[:start] + lines[end:]


def _split_level1_block(
    section_id: str,
    title: str,
    block_lines: list[str],
    max_section_chars: int,
) -> list[dict[str, str]]:
    block_content = "\n".join(block_lines)
    if len(block_content) <= max_section_chars:
        return [_section(section_id, title or section_id, block_content)]

    sub_chunks = _split_by_level2(block_lines, max_section_chars)
    if not sub_chunks:
        return [_section(section_id, title or section_id, block_content)]

    sections: list[dict[str, str]] = []
    first_sub_line_idx = _first_level2_line_idx(block_lines)
    if first_sub_line_idx is not None:
        preface_content = "\n".join(block_lines[:first_sub_line_idx]).strip()
        if preface_content:
            sections.append(_section(section_id, title or section_id, "\n".join(block_lines[:first_sub_line_idx])))

    for sub_id, sub_title, sub_block in sub_chunks:
        sections.append(_section(sub_id, sub_title or sub_id, "\n".join(sub_block)))
    return sections


def _first_level2_line_idx(lines: list[str]) -> int | None:
    for idx, line in enumerate(lines):
        if _is_level2_line(line):
            return idx
    return None


def _section(section_id: str, title: str, content: str) -> dict[str, str]:
    return {"section_id": section_id, "title": title, "content": content}
