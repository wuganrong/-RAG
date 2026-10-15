"""MinerU Markdown 目录切分。"""

from __future__ import annotations

# 1. Python 标准库
import re

TocEntry = tuple[str, str]
HeadingMatch = tuple[int, str, str]
TocRange = tuple[int, int]


def _normalize_title_line(line: str) -> str:
    """去掉目录行末尾点号、空白和页码。"""
    title = line.strip()
    title = re.sub(r"[.\s]+(\d+|[IVXLCDM]+)\s*$", "", title)
    return title.strip()


def parse_toc(lines: list[str]) -> list[TocEntry]:
    """解析目录块，返回 `(section_id, title)` 列表。"""
    entries: list[TocEntry] = []
    num_re = re.compile(r"^(\d+(?:\.\d+)*)\s*(.+)$")
    appendix_re = re.compile(r"^附录\s*([A-Z])\s*[（(][^）)]*[）)]\s*(.*)$", re.IGNORECASE)

    for raw_line in lines:
        line = raw_line.strip()
        while line.startswith("#"):
            line = line.lstrip("#").strip()
        if not line or re.match(r"^GB\s*\d|^[\dIVX]+$", line):
            continue

        num_match = num_re.match(line)
        if num_match:
            section_id = num_match.group(1)
            title = _normalize_title_line(num_match.group(2))
            if title:
                entries.append((section_id, title))
            continue

        appendix_match = appendix_re.match(line)
        if appendix_match:
            letter = appendix_match.group(1).upper()
            title = _normalize_title_line(appendix_match.group(2)) if appendix_match.group(2) else f"附录{letter}"
            entries.append((f"附录{letter}", title))
            continue

        if "前言" in line and not any(entry[0] == "前言" for entry in entries):
            entries.append(("前言", "前言"))
        elif "参考文献" in line and not any(entry[0] == "参考文献" for entry in entries):
            entries.append(("参考文献", "参考文献"))

    return entries


def find_toc_block(lines: list[str]) -> TocRange | None:
    """返回目录正文区间 `(start, end)`，不含 `# 目次` 行。"""
    toc_start: int | None = None
    for idx, line in enumerate(lines):
        if re.match(r"^#\s*目\s*次\s*$", line.strip()):
            toc_start = idx
            break
    if toc_start is None:
        return None

    for idx in range(toc_start + 1, len(lines)):
        stripped = lines[idx].strip()
        if re.match(r"^#\s*前\s*言\s*$", stripped) or re.match(r"^#\s*引\s*言\s*$", stripped):
            return toc_start + 1, idx

    toc_end: int | None = None
    for idx in range(toc_start + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("# ") and len(stripped) > 2 and "目" not in stripped[:10]:
            toc_end = idx
            break
    return toc_start + 1, toc_end if toc_end is not None else len(lines)


def find_heading_matches(
    lines: list[str],
    toc_entries: list[TocEntry],
    search_start_idx: int = 0,
) -> list[HeadingMatch]:
    """按目录条目在正文中定位标题行。"""
    heading_lines = _collect_heading_lines(lines, search_start_idx)
    result: list[HeadingMatch] = []
    seen: set[str] = set()

    for section_id, title in toc_entries:
        if section_id in seen:
            continue
        matched = _match_toc_entry(heading_lines, section_id, title)
        if matched is None:
            continue
        result.append(matched)
        seen.add(section_id)

    result.sort(key=lambda item: item[0])
    return result


def split_by_toc(content: str) -> list[dict[str, str]]:
    """按 MinerU Markdown 目录切分，返回 section 字典列表。"""
    lines = content.splitlines()
    toc_range = find_toc_block(lines)
    if not toc_range:
        return []

    start, end = toc_range
    toc_entries = parse_toc(lines[start:end])
    if not toc_entries:
        return []

    matches = find_heading_matches(lines, toc_entries, search_start_idx=end)
    if not matches:
        return []

    sections: list[dict[str, str]] = []
    for idx, (line_idx, section_id, title) in enumerate(matches):
        end_idx = matches[idx + 1][0] if idx + 1 < len(matches) else len(lines)
        sections.append(
            {
                "section_id": section_id,
                "title": title.strip(),
                "content": "\n".join(lines[line_idx:end_idx]),
            }
        )
    return sections


def _collect_heading_lines(lines: list[str], search_start_idx: int) -> list[tuple[int, str]]:
    heading_lines: list[tuple[int, str]] = []
    for idx, line in enumerate(lines):
        if idx < search_start_idx:
            continue
        stripped = line.strip()
        if stripped.startswith("# ") and len(stripped) > 2:
            heading_lines.append((idx, stripped))
        if re.match(r"^附录\s*[A-Z]\s*$", stripped, re.IGNORECASE):
            heading_lines.append((idx, f"# {stripped}"))
        if re.search(r"参\s*考\s*文\s*献", stripped) and len(stripped) < 30:
            heading_lines.append((idx, "# 参考文献"))
    return heading_lines


def _match_toc_entry(
    heading_lines: list[tuple[int, str]],
    section_id: str,
    title: str,
) -> HeadingMatch | None:
    if section_id == "前言":
        return _match_by_pattern(heading_lines, r"前\s*言", section_id, title)
    if section_id == "参考文献":
        return _match_by_pattern(heading_lines, r"参考文献", section_id, title)
    if section_id.startswith("附录"):
        return _match_appendix(heading_lines, section_id, title)

    prefix_with_space = f"# {section_id} "
    exact = f"# {section_id}"
    for idx, heading in heading_lines:
        if heading.startswith(prefix_with_space) or heading.strip() == exact:
            return idx, section_id, title
    return None


def _match_by_pattern(
    heading_lines: list[tuple[int, str]],
    pattern: str,
    section_id: str,
    title: str,
) -> HeadingMatch | None:
    for idx, heading in heading_lines:
        if re.search(pattern, heading):
            return idx, section_id, title
    return None


def _match_appendix(heading_lines: list[tuple[int, str]], section_id: str, title: str) -> HeadingMatch | None:
    letter = section_id.replace("附录", "").strip()
    appendix_start_re = re.compile(r"^\s*附\s*录\s*", re.IGNORECASE)
    for idx, heading in heading_lines:
        content = heading.strip()[2:].strip() if heading.strip().startswith("# ") else heading.strip()
        if appendix_start_re.match(content) and letter.upper() in heading:
            return idx, section_id, title
    return None
